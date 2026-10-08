"""Local server used by the desktop app: REST for status/accounts/location, a WebSocket for the chat.

Listens on 127.0.0.1 only and requires a per-launch secret token, so web pages open in a browser
cannot drive NOVA. The agent runs in a worker thread; confirmations travel to the app and back.
"""

import asyncio
import concurrent.futures
import json
import mimetypes
import secrets
import shutil
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nova.config import Settings
from nova.core.agent import Agent, MaxTurnsExceededError
from nova.core.messages import Attachment, Media, ToolCall, ToolResult
from nova.device import filesystem
from nova.device.access import request_access
from nova.device.attachments import prepare_attachment
from nova.device.location import Location, LocationDetector
from nova.device.opener import open_with_default_app
from nova.device.safety import opening_warning
from nova.interfaces.account import (
    AccountManager,
    AccountSelectionError,
    ClaudeAccount,
    LoginSession,
)
from nova.interfaces.assembly import build_agent, use_claude_account
from nova.interfaces.history import Conversation, ConversationStore
from nova.interfaces.models import UnknownModelError, choices_for, choose_model, current_model
from nova.interfaces.setup import save_location
from nova.interfaces.titles import generate_title
from nova.providers.base import ProviderError

CONFIRMATION_TIMEOUT_SECONDS = 600
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml", ".html": "text/html",
    ".pdf": "application/pdf", ".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
}


class EmailBody(BaseModel):
    email: str


class CodeBody(BaseModel):
    code: str


class PlaceBody(BaseModel):
    place: str


class DestinationBody(BaseModel):
    destination: str


class ModelBody(BaseModel):
    model: str


class TitleBody(BaseModel):
    title: str


class PathBody(BaseModel):
    path: str


class OpenBody(BaseModel):
    path: str
    confirmed: bool = False
    """True once the user saw the warning about this file and chose to open it anyway."""


class ConfirmedBody(BaseModel):
    confirmed: bool = False


class RenameBody(BaseModel):
    path: str
    name: str


class NewFolderBody(BaseModel):
    parent: str
    name: str


class MediaLibrary:
    """Files produced by tools, served under unguessable ids so the app can display them.
    Only registered files are reachable: /media never serves an arbitrary path."""

    def __init__(self) -> None:
        self._paths: dict[str, Path] = {}

    def register(self, media: Media) -> dict[str, Any]:
        media_id = secrets.token_urlsafe(24)
        path = Path(media.path)
        self._paths[media_id] = path
        return {
            "id": media_id,
            "kind": media.kind,
            "title": media.title,
            "path": media.path,
            "file_name": path.name,
            "size": path.stat().st_size if path.is_file() else 0,
            "url": f"/media/{media_id}",
        }

    def path(self, media_id: str) -> Path | None:
        return self._paths.get(media_id)


class ChatChannel:
    """Bridges the agent's worker thread and the app's WebSocket (confirmations and live progress)."""

    def __init__(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop, media: MediaLibrary | None = None) -> None:
        self.websocket = websocket
        self.loop = loop
        self.media = media or MediaLibrary()
        self.pending: dict[str, concurrent.futures.Future[bool]] = {}

    def send(self, event: dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(self.websocket.send_json(event), self.loop)

    def confirm(self, question: str, warning: str | None = None) -> bool:
        request_id = str(uuid.uuid4())
        answer: concurrent.futures.Future[bool] = concurrent.futures.Future()
        self.pending[request_id] = answer
        self.send({"type": "confirmation_request", "id": request_id, "question": question, "warning": warning})
        try:
            return answer.result(timeout=CONFIRMATION_TIMEOUT_SECONDS)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError):
            return False
        finally:
            self.pending.pop(request_id, None)

    def answer(self, request_id: str, approved: bool) -> None:
        future = self.pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(approved)

    def cancel_all(self) -> None:
        for future in list(self.pending.values()):
            future.cancel()

    def on_tool_call(self, call: ToolCall) -> None:
        self.send({"type": "tool_started", "id": call.id, "name": call.name, "arguments": call.arguments})

    def on_tool_result(self, result: ToolResult) -> None:
        event = {"type": "tool_finished", "id": result.call_id, "name": result.name, "is_error": result.is_error}
        if result.warning:
            event["warning"] = result.warning
        if result.media:
            event["media"] = [self.media.register(media) for media in result.media]
        self.send(event)


class ChannelProxy:
    """Stable confirmer/observer for the agent, pointing at whichever app window is connected.
    Also records tool steps into the current conversation so they reappear when it is reopened."""

    def __init__(self, session: "NovaSession") -> None:
        self.session = session
        self.channel: ChatChannel | None = None

    def confirm(self, question: str, warning: str | None = None) -> bool:
        return self.channel.confirm(question, warning) if self.channel is not None else False

    def on_tool_call(self, call: ToolCall) -> None:
        if self.session.conversation is not None:
            self.session.conversation.add_item(
                {"kind": "tool", "id": call.id, "name": call.name, "arguments": call.arguments, "status": "running", "media": []}
            )
        if self.channel is not None:
            self.channel.on_tool_call(call)

    def on_tool_result(self, result: ToolResult) -> None:
        if self.session.conversation is not None:
            self.session.conversation.update_tool(result.call_id, "error" if result.is_error else "done", result.media, result.warning)
        if self.channel is not None:
            self.channel.on_tool_result(result)


class NovaSession:
    """Single-user state of the running app: chosen account, agent, sign-in in progress."""

    def __init__(
        self,
        settings: Settings,
        accounts: AccountManager | None = None,
        location_detector: LocationDetector | None = None,
        agent_factory=build_agent,
        store: ConversationStore | None = None,
        namer=generate_title,
        env_path: Path = Path(".env"),
        opening_check=opening_warning,
    ) -> None:
        self.settings = settings
        self.opening_check = opening_check
        self.env_path = env_path
        self.namer = namer
        self.accounts = accounts or AccountManager(settings)
        self.location_detector = location_detector
        self.agent_factory = agent_factory
        self.proxy = ChannelProxy(self)
        self.media = MediaLibrary()
        self.store = store or ConversationStore(settings.conversations_dir)
        self.conversation: Conversation | None = None
        self.uploads: dict[str, Attachment] = {}
        self.agent: Agent | None = None
        self.account: ClaudeAccount | None = None
        self.login: LoginSession | None = None
        self.busy = threading.Lock()

    def needs_account(self) -> bool:
        return self.settings.provider == "claude_code"

    def restore_account(self) -> ClaudeAccount | None:
        if not self.needs_account():
            return None
        if self.account is None:
            chosen = self.accounts.chosen_account()
            if chosen is not None and self.accounts.is_still_logged_in(chosen):
                self.account = chosen
            elif chosen is not None:
                self.accounts.forget()
        return self.account

    def use_account(self, account: ClaudeAccount) -> None:
        self.accounts.remember(account)
        self.account = account
        self.agent = None

    def switch_account(self) -> None:
        self.accounts.forget()
        self.account = None
        self.agent = None

    def remove_account(self, email: str) -> None:
        self.accounts.remove(email)
        if self.account is not None and self.account.email.lower() == email.lower():
            self.account = None
            self.agent = None

    def get_agent(self) -> Agent:
        if self.agent is None:
            if self.needs_account() and self.restore_account() is None:
                raise AccountSelectionError("Choose a Claude account first.")
            settings = use_claude_account(self.settings, self.account) if self.account else self.settings
            self.agent = self.agent_factory(settings, self.proxy, self.proxy)
            self.agent.history = self.conversation.messages if self.conversation is not None else []
            self.agent.session = self.conversation.provider_session if self.conversation is not None else None
        return self.agent

    def start_conversation_if_needed(self, first_message: str) -> Conversation:
        if self.conversation is None:
            self.conversation = self.store.new(first_message)
            if self.agent is not None:
                self.conversation.messages.extend(self.agent.history)
                self.agent.history = self.conversation.messages
                self.agent.session = self.conversation.provider_session
        return self.conversation

    def open_conversation(self, conversation: Conversation) -> None:
        self.conversation = conversation
        if self.agent is not None:
            self.agent.history = conversation.messages
            self.agent.session = conversation.provider_session

    def new_conversation(self) -> None:
        self.conversation = None
        if self.agent is not None:
            self.agent.history = []
            self.agent.session = None

    def save_conversation(self) -> dict[str, str] | None:
        if self.conversation is None:
            return None
        self.store.save(self.conversation)
        return self.conversation.summary()

    def attachment_payload(self, attachment: Attachment) -> dict[str, Any]:
        kind = "image" if attachment.kind == "image" else "file"
        payload = self.media.register(Media(path=attachment.path, kind=kind, title=attachment.name))
        return payload | {"warning": attachment.warning} if attachment.warning else payload

    def display_items(self, conversation: Conversation) -> list[dict[str, Any]]:
        items = []
        for item in conversation.items:
            if item.get("kind") == "user" and item.get("attachments"):
                attachments = [self.attachment_payload(Attachment(**entry)) for entry in item["attachments"]]
                items.append({**item, "attachments": attachments})
            elif item.get("kind") == "tool":
                media = [self.media.register(Media(**entry)) for entry in item.get("media", [])]
                items.append({**item, "status": "error" if item.get("status") == "running" else item.get("status"), "media": media})
            else:
                items.append(item)
        return items

    def use_model(self, model: str) -> None:
        self.settings = choose_model(self.settings, model, self.env_path)
        self.agent = None

    def set_location(self, location: Location) -> None:
        save_location(self.env_path, location)
        self.settings = self.settings.model_copy(
            update={
                "location_city": location.city,
                "location_region": location.region,
                "location_country": location.country,
                "location_latitude": location.latitude,
                "location_longitude": location.longitude,
                "location_source": location.source,
            }
        )
        self.agent = None

    def detector(self) -> LocationDetector:
        if self.location_detector is None:
            self.location_detector = LocationDetector()
        return self.location_detector


def account_payload(account: ClaudeAccount | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {"email": account.email, "everyday_login": account.config_dir is None}


def location_payload(location: Location | None) -> dict[str, Any] | None:
    return asdict(location) | {"label": location.describe()} if location is not None else None


def create_app(session: NovaSession, token: str) -> FastAPI:
    app = FastAPI(title="NOVA local server")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(ALLOWED_ORIGINS),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def require_token(authorization: str = Header(default="")) -> None:
        if not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="Invalid NOVA token.")

    protected = [Depends(require_token)]

    @app.get("/api/status", dependencies=protected)
    def status() -> dict[str, Any]:
        return {
            "provider": session.settings.provider,
            "needs_account": session.needs_account(),
            "account": account_payload(session.restore_account()),
            "location": location_payload(session.settings.location()),
            "trusted_dirs": [str(directory) for directory in session.settings.trusted_dirs],
        }

    @app.get("/api/accounts", dependencies=protected)
    def accounts() -> dict[str, Any]:
        try:
            available = [account_payload(account) for account in session.accounts.known_accounts()]
        except ProviderError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"current": account_payload(session.restore_account()), "available": available}

    @app.post("/api/accounts/select", dependencies=protected)
    def select_account(body: EmailBody) -> dict[str, Any]:
        try:
            known_accounts = session.accounts.known_accounts()
        except ProviderError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        for account in known_accounts:
            if account.email.lower() == body.email.lower():
                session.use_account(account)
                return {"account": account_payload(account)}
        raise HTTPException(status_code=404, detail=f"{body.email} is not signed in. Add it first.")

    @app.post("/api/accounts/login/start", dependencies=protected)
    def start_login(body: EmailBody) -> dict[str, str]:
        if session.login is not None:
            session.login.cancel()
        try:
            session.login = LoginSession(session.accounts, body.email.strip())
            code_url = session.login.sign_in_url()
            return {"url": session.login.browser_link() or code_url, "code_url": code_url}
        except (AccountSelectionError, OSError) as error:
            session.login = None
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/accounts/login/finish", dependencies=protected)
    def finish_login(body: CodeBody) -> dict[str, Any]:
        if session.login is None:
            raise HTTPException(status_code=400, detail="No sign-in in progress.")
        try:
            account = session.login.submit_code(body.code)
        except AccountSelectionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            session.login = None
        session.use_account(account)
        return {"account": account_payload(account)}

    @app.get("/api/accounts/login/status", dependencies=protected)
    def login_status() -> dict[str, Any]:
        login = session.login
        if login is None:
            raise HTTPException(status_code=400, detail="Aucune connexion en cours.")
        try:
            account = login.finished()
        except AccountSelectionError as error:
            session.login = None
            raise HTTPException(status_code=400, detail=str(error)) from error
        if account is None:
            return {"account": None}
        session.login = None
        session.use_account(account)
        return {"account": account_payload(account)}

    @app.post("/api/accounts/switch", dependencies=protected)
    def switch_account() -> dict[str, bool]:
        session.switch_account()
        return {"ok": True}

    @app.post("/api/accounts/remove", dependencies=protected)
    def remove_account(body: EmailBody) -> dict[str, Any]:
        try:
            session.remove_account(body.email)
        except AccountSelectionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"available": [account_payload(account) for account in session.accounts.known_accounts()]}

    def models_payload() -> dict[str, Any]:
        return {"current": current_model(session.settings), "options": [asdict(choice) for choice in choices_for(session.settings)]}

    @app.get("/api/models", dependencies=protected)
    def models() -> dict[str, Any]:
        return models_payload()

    @app.post("/api/models", dependencies=protected)
    def select_model(body: ModelBody) -> dict[str, Any]:
        try:
            session.use_model(body.model)
        except UnknownModelError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return models_payload()

    @app.post("/api/location/detect", dependencies=protected)
    def detect_location() -> dict[str, Any]:
        return {"location": location_payload(session.detector().detect())}

    @app.post("/api/location/search", dependencies=protected)
    def search_location(body: PlaceBody) -> dict[str, Any]:
        location = session.detector().geocode(body.place)
        if location is None:
            raise HTTPException(status_code=404, detail=f"Could not find '{body.place}'.")
        return {"location": location_payload(location)}

    @app.post("/api/location", dependencies=protected)
    def save(body: dict[str, Any]) -> dict[str, Any]:
        try:
            location = Location(**{key: body[key] for key in Location.__dataclass_fields__})
        except (KeyError, TypeError) as error:
            raise HTTPException(status_code=422, detail="Invalid location.") from error
        session.set_location(location)
        return {"location": location_payload(location)}

    def media_path(media_id: str) -> Path:
        path = session.media.path(media_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Ce fichier n'existe plus.")
        return path

    @app.get("/media/{media_id}")
    def media(media_id: str, download: bool = False) -> FileResponse:
        path = media_path(media_id)
        headers = {"Content-Security-Policy": "sandbox allow-scripts"} if path.suffix.lower() in {".html", ".htm"} else {}
        media_type = MEDIA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(
            path,
            media_type=media_type,
            headers=headers,
            filename=path.name,
            content_disposition_type="attachment" if download else "inline",
        )

    def open_checked(path: Path, confirmed: bool) -> dict[str, Any]:
        """Programs, scripts and downloaded files are checked first: the app shows the warning and asks
        again with `confirmed` once the user chose to open anyway (a threat found by Defender included)."""
        if not confirmed:
            warning = session.opening_check(path)
            if warning is not None:
                return {"ok": False, "warning": warning}
        try:
            open_with_default_app(path)
        except OSError as error:
            raise HTTPException(status_code=500, detail=f"Impossible d'ouvrir : {error}") from error
        return {"ok": True}

    @app.post("/api/media/{media_id}/open", dependencies=protected)
    def open_media(media_id: str, body: ConfirmedBody | None = None) -> dict[str, Any]:
        return open_checked(media_path(media_id), body is not None and body.confirmed)

    @app.post("/api/media/{media_id}/save", dependencies=protected)
    def save_media(media_id: str, body: DestinationBody) -> dict[str, str]:
        destination = Path(body.destination).expanduser()
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(media_path(media_id), destination)
        except OSError as error:
            raise HTTPException(status_code=500, detail=f"Impossible d'enregistrer le fichier : {error}") from error
        return {"path": str(destination)}

    @app.post("/api/uploads", dependencies=protected)
    def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        upload_id = secrets.token_hex(8)
        folder = session.settings.uploads_dir.expanduser() / upload_id
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / (Path(file.filename or "fichier").name or "fichier")
        written = 0
        with destination.open("wb") as output:
            while chunk := file.file.read(UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    output.close()
                    shutil.rmtree(folder, ignore_errors=True)
                    raise HTTPException(status_code=413, detail="Fichier trop gros (200 Mo maximum).")
                output.write(chunk)
        attachment = prepare_attachment(destination, folder / ".nova-cache")
        session.uploads[upload_id] = attachment
        return {"upload_id": upload_id, "attachment": session.attachment_payload(attachment)}

    def explorer(action):
        try:
            return action()
        except filesystem.FileExplorerError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/files/places", dependencies=protected)
    def places() -> dict[str, Any]:
        nova_folders = [
            ("Créations de NOVA", (session.settings.trusted_dirs[0] / "NOVA").expanduser() if session.settings.trusted_dirs else Path.home() / "NOVA"),
            ("Espace de travail", session.settings.trusted_dirs[0].expanduser() if session.settings.trusted_dirs else Path.home()),
        ]
        return {"places": [asdict(place) for place in filesystem.list_places(nova_folders)]}

    @app.get("/api/files/list", dependencies=protected)
    def list_files(path: str) -> dict[str, Any]:
        return explorer(lambda: filesystem.list_folder(path))

    @app.get("/api/files/search", dependencies=protected)
    def search(path: str, query: str) -> dict[str, Any]:
        return explorer(lambda: filesystem.search_files(path, query))

    @app.get("/api/files/thumbnail")
    def file_thumbnail(path: str, token_value: str = "") -> Response:
        if not secrets.compare_digest(token_value, token):
            raise HTTPException(status_code=401, detail="Invalid NOVA token.")
        data = explorer(lambda: filesystem.thumbnail(path))
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})

    @app.post("/api/files/preview", dependencies=protected)
    def preview(body: PathBody) -> dict[str, Any]:
        path = Path(body.path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Fichier introuvable.")
        suffix = path.suffix.lower()
        kind = "image" if suffix in filesystem.THUMBNAIL_SUFFIXES else "svg" if suffix == ".svg" else "html" if suffix in {".html", ".htm"} else "file"
        return {"media": session.media.register(Media(path=str(path), kind=kind, title=path.name))}

    @app.post("/api/files/attach", dependencies=protected)
    def attach(body: PathBody) -> dict[str, Any]:
        path = Path(body.path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Fichier introuvable.")
        upload_id = secrets.token_hex(8)
        attachment = prepare_attachment(path, session.settings.uploads_dir.expanduser() / upload_id / ".nova-cache")
        session.uploads[upload_id] = attachment
        return {"upload_id": upload_id, "attachment": session.attachment_payload(attachment)}

    @app.post("/api/files/folder", dependencies=protected)
    def new_folder(body: NewFolderBody) -> dict[str, Any]:
        return {"entry": explorer(lambda: filesystem.create_folder(body.parent, body.name))}

    @app.post("/api/files/rename", dependencies=protected)
    def rename_file(body: RenameBody) -> dict[str, Any]:
        return {"entry": explorer(lambda: filesystem.rename(body.path, body.name))}

    @app.post("/api/files/trash", dependencies=protected)
    def trash(body: PathBody) -> dict[str, bool]:
        explorer(lambda: filesystem.move_to_trash(body.path))
        return {"ok": True}

    @app.post("/api/files/request-access", dependencies=protected)
    def request_folder_access(body: PathBody) -> dict[str, Any]:
        return {"entry": explorer(lambda: request_access(body.path))}

    @app.post("/api/files/open", dependencies=protected)
    def open_path(body: OpenBody) -> dict[str, Any]:
        path = Path(body.path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Introuvable.")
        return open_checked(path, body.confirmed or path.is_dir())

    @app.post("/api/files/upload", dependencies=protected)
    def upload_into(folder: str, file: UploadFile = File(...)) -> dict[str, Any]:
        target_folder = Path(folder)
        if not target_folder.is_dir():
            raise HTTPException(status_code=404, detail="Dossier introuvable.")
        destination = explorer(lambda: filesystem.unique_destination(target_folder, file.filename or "fichier"))
        try:
            with destination.open("wb") as output:
                shutil.copyfileobj(file.file, output, UPLOAD_CHUNK_BYTES)
        except OSError as error:
            raise HTTPException(status_code=500, detail=f"Impossible d'enregistrer : {error}") from error
        return {"entry": filesystem.entry_payload(destination)}

    def require_idle() -> None:
        if session.busy.locked():
            raise HTTPException(status_code=409, detail="NOVA est encore en train de répondre.")

    @app.get("/api/conversations", dependencies=protected)
    def conversations() -> dict[str, Any]:
        current = session.conversation.id if session.conversation is not None else None
        return {"current": current, "conversations": session.store.list()}

    @app.post("/api/conversations/new", dependencies=protected)
    def new_conversation() -> dict[str, bool]:
        require_idle()
        session.new_conversation()
        return {"ok": True}

    @app.post("/api/conversations/{conversation_id}/open", dependencies=protected)
    def open_conversation(conversation_id: str) -> dict[str, Any]:
        require_idle()
        conversation = session.store.load(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        session.open_conversation(conversation)
        return {"conversation": conversation.summary(), "items": session.display_items(conversation)}

    @app.post("/api/conversations/{conversation_id}/rename", dependencies=protected)
    def rename_conversation(conversation_id: str, body: TitleBody) -> dict[str, Any]:
        if session.conversation is not None and session.conversation.id == conversation_id:
            session.conversation.title = body.title.strip() or session.conversation.title
            session.conversation.needs_title = False
            return {"conversation": session.save_conversation()}
        conversation = session.store.rename(conversation_id, body.title)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        return {"conversation": conversation.summary()}

    @app.delete("/api/conversations/{conversation_id}", dependencies=protected)
    def delete_conversation(conversation_id: str) -> dict[str, bool]:
        is_current = session.conversation is not None and session.conversation.id == conversation_id
        if is_current:
            require_idle()
        try:
            deleted = session.store.delete(conversation_id)
        except ValueError:
            deleted = False
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        if is_current:
            session.new_conversation()
        return {"ok": True}

    @app.websocket("/ws")
    async def chat(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if websocket.query_params.get("token") != token or (origin is not None and origin not in ALLOWED_ORIGINS):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        channel = ChatChannel(websocket, asyncio.get_running_loop(), session.media)
        session.proxy.channel = channel
        try:
            while True:
                message = await websocket.receive_json()
                await handle_chat_message(session, channel, message)
        except (WebSocketDisconnect, json.JSONDecodeError):
            pass
        finally:
            channel.cancel_all()
            if session.proxy.channel is channel:
                session.proxy.channel = None

    return app


async def handle_chat_message(session: NovaSession, channel: ChatChannel, message: dict[str, Any]) -> None:
    kind = message.get("type")
    if kind == "confirmation_answer":
        channel.answer(str(message.get("id")), bool(message.get("approved")))
    elif kind == "reset":
        if session.busy.locked():
            await channel.websocket.send_json({"type": "error", "message": "NOVA est encore en train de répondre."})
            return
        session.new_conversation()
        await channel.websocket.send_json({"type": "reset_done"})
    elif kind == "user_message":
        text = str(message.get("text", "")).strip()
        attachments = [session.uploads[upload_id] for upload_id in message.get("attachments") or [] if upload_id in session.uploads]
        if not text and not attachments:
            return
        if not session.busy.acquire(blocking=False):
            await channel.websocket.send_json({"type": "error", "message": "NOVA est encore en train de répondre."})
            return
        asyncio.get_running_loop().run_in_executor(None, run_agent_turn, session, channel, text, attachments)


def run_agent_turn(session: NovaSession, channel: ChatChannel, text: str, attachments: list[Attachment] | None = None) -> None:
    """Runs one request. The answer is sent only once the conversation is saved and NOVA is free again,
    so the app can immediately start a new conversation or open another one."""
    final_events: list[dict[str, Any]] = []
    answered: tuple[Agent, Conversation, str, str] | None = None
    try:
        channel.send({"type": "thinking"})
        agent = session.get_agent()
        attachments = attachments or []
        first_message = text or ", ".join(attachment.name for attachment in attachments)
        conversation = session.start_conversation_if_needed(first_message)
        user_item: dict[str, Any] = {"kind": "user", "text": text}
        if attachments:
            user_item["attachments"] = [asdict(attachment) for attachment in attachments]
        conversation.add_item(user_item)
        channel.send({"type": "conversation_saved", "conversation": session.save_conversation()})
        try:
            answer = agent.ask(text, attachments)
        except (ProviderError, MaxTurnsExceededError, AccountSelectionError, OSError, ValueError) as error:
            conversation.add_item({"kind": "error", "text": str(error)})
            final_events.append({"type": "error", "message": str(error)})
        else:
            conversation.add_item({"kind": "assistant", "text": answer})
            final_events.append({"type": "assistant_message", "text": answer})
            answered = (agent, conversation, first_message, answer)
        final_events.insert(0, {"type": "conversation_saved", "conversation": session.save_conversation()})
    except (ProviderError, AccountSelectionError, OSError, ValueError) as error:
        final_events.append({"type": "error", "message": str(error)})
    finally:
        session.busy.release()
    for event in final_events:
        channel.send(event)
    if answered is not None and answered[1].needs_title:
        name_conversation(session, channel, *answered)


def name_conversation(session: NovaSession, channel: ChatChannel, agent: Agent, conversation: Conversation, first_message: str, answer: str) -> None:
    """Runs after the answer is shown, so naming never delays it, and never marks NOVA busy: a message sent
    meanwhile is handled normally (its turn saves the new title too)."""
    title = session.namer(agent.provider, first_message, answer)
    if not conversation.needs_title:
        return
    conversation.needs_title = False
    if not title:
        return
    conversation.title = title
    session.store.save(conversation)
    channel.send({"type": "conversation_titled", "conversation": conversation.summary()})


def run_server(settings: Settings | None = None) -> None:
    import os

    import uvicorn

    settings = settings or Settings()
    token = os.environ.get("NOVA_SERVER_TOKEN") or secrets.token_urlsafe(32)
    app = create_app(NovaSession(settings), token)
    print(json.dumps({"event": "nova_server_ready", "port": settings.server_port, "token": token}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=settings.server_port, log_level="warning")
