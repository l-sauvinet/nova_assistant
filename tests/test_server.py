import io
import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nova.config import Settings
from nova.core.agent import Agent
from nova.core.messages import ProviderResponse, ToolCall
from nova.interfaces.account import AccountManager, LoginSession, account_folder_name
from nova.interfaces.server import NovaSession, create_app
from nova.providers.claude_code import ClaudeCodeProvider
from nova.tools.file_access import FileAccessGuard
from nova.tools.files import FileManager, build_file_tools
from nova.tools.registry import ToolRegistry
from fakes import ScriptedProvider

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PERSONAL = "alice@example.com"
WORK = "bob@work.example"


class FakeLogins:
    def __init__(self, emails_by_folder):
        self.emails_by_folder = emails_by_folder

    def provider(self, config_dir):
        def run(command, **kwargs):
            email = self.emails_by_folder.get(config_dir)
            return subprocess.CompletedProcess(command, 0, json.dumps({"loggedIn": email is not None, "email": email}), "")

        return ClaudeCodeProvider(config_dir=config_dir, run_command=run)


def make_client(tmp_path: Path, responses=(), logins=None, provider_name="claude_code", namer=lambda provider, first_message, answer: None):
    settings = Settings(_env_file=None, provider=provider_name, trusted_dirs=[tmp_path], claude_code_accounts_dir=tmp_path / "accounts")
    logins = logins or FakeLogins({None: PERSONAL})
    scripted = ScriptedProvider(list(responses))

    def agent_factory(agent_settings, confirmer, observer):
        registry = ToolRegistry(build_file_tools(FileManager(FileAccessGuard([tmp_path / "trusted"], confirmer))), confirmer)
        return Agent(scripted, registry, system_prompt="You are NOVA.", observer=observer)

    session = NovaSession(settings, accounts=AccountManager(settings, make_provider=logins.provider), agent_factory=agent_factory, namer=namer, env_path=tmp_path / ".env")
    return TestClient(create_app(session, TOKEN)), session


def receive(websocket):
    """Next chat event, skipping the sidebar refresh notifications."""
    while (event := websocket.receive_json())["type"] == "conversation_saved":
        pass
    return event


def select(client, email=PERSONAL):
    assert client.post("/api/accounts/select", json={"email": email}, headers=AUTH).status_code == 200


def test_rest_requires_token(tmp_path: Path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_websocket_rejects_wrong_token_and_foreign_origin(tmp_path: Path):
    client, _ = make_client(tmp_path)
    for url, headers in (("/ws?token=wrong", {}), (f"/ws?token={TOKEN}", {"origin": "https://evil.example"})):
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(url, headers=headers):
                pass
        assert refused.value.code == 4401


def test_status_before_and_after_choosing_account(tmp_path: Path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/status", headers=AUTH).json()["account"] is None
    assert client.get("/api/accounts", headers=AUTH).json()["available"] == [{"email": PERSONAL, "everyday_login": True}]
    select(client)
    assert client.get("/api/status", headers=AUTH).json()["account"]["email"] == PERSONAL


def test_selecting_unknown_account_fails(tmp_path: Path):
    client, _ = make_client(tmp_path)
    assert client.post("/api/accounts/select", json={"email": "nobody@x.y"}, headers=AUTH).status_code == 404


def test_switching_account_keeps_every_login_available(tmp_path: Path, monkeypatch):
    folder = tmp_path / "accounts" / account_folder_name(WORK)
    folder.mkdir(parents=True)
    client, _ = make_client(tmp_path, logins=FakeLogins({None: PERSONAL, folder: WORK}))
    select(client, WORK)
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: commands.append(args))

    client.post("/api/accounts/switch", headers=AUTH)
    assert client.get("/api/status", headers=AUTH).json()["account"] is None
    assert [account["email"] for account in client.get("/api/accounts", headers=AUTH).json()["available"]] == [PERSONAL, WORK]
    assert commands == []


def test_removing_a_nova_account_signs_it_out_for_good(tmp_path: Path, monkeypatch):
    folder = tmp_path / "accounts" / account_folder_name(WORK)
    folder.mkdir(parents=True)
    logins = FakeLogins({None: PERSONAL, folder: WORK})
    client, _ = make_client(tmp_path, logins=logins)
    select(client, WORK)
    commands = []

    def fake_logout(command, env, **kwargs):
        commands.append((command, env["CLAUDE_CONFIG_DIR"]))
        del logins.emails_by_folder[folder]

    monkeypatch.setattr(subprocess, "run", fake_logout)
    removed = client.post("/api/accounts/remove", json={"email": WORK}, headers=AUTH)
    assert [account["email"] for account in removed.json()["available"]] == [PERSONAL]
    assert commands == [(["claude", "auth", "logout"], str(folder))] and not folder.exists()
    assert client.get("/api/status", headers=AUTH).json()["account"] is None
    assert client.post("/api/accounts/remove", json={"email": PERSONAL}, headers=AUTH).status_code == 400


def test_chat_answer(tmp_path: Path):
    client, _ = make_client(tmp_path, [ProviderResponse(text="Bonjour Alice !")])
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}", headers={"origin": "tauri://localhost"}) as websocket:
        websocket.send_json({"type": "user_message", "text": "Salut"})
        assert receive(websocket) == {"type": "thinking"}
        assert receive(websocket) == {"type": "assistant_message", "text": "Bonjour Alice !"}


def test_chat_without_account_reports_error(tmp_path: Path):
    client, _ = make_client(tmp_path, [ProviderResponse(text="x")])
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "Salut"})
        receive(websocket)
        error = receive(websocket)
        assert error["type"] == "error" and "Claude account" in error["message"]


def test_other_providers_need_no_account(tmp_path: Path):
    client, _ = make_client(tmp_path, [ProviderResponse(text="ok")], provider_name="ollama")
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "Salut"})
        receive(websocket)
        assert receive(websocket)["text"] == "ok"


def test_tool_progress_and_confirmation_round_trip(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.txt").write_text("secret")
    (tmp_path / "trusted").mkdir()
    client, _ = make_client(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(outside / "note.txt")})]),
            ProviderResponse(text="Le fichier dit secret."),
        ],
    )
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "Lis la note"})
        assert receive(websocket)["type"] == "thinking"
        started = receive(websocket)
        assert started["type"] == "tool_started" and started["name"] == "read_file"
        request = receive(websocket)
        assert request["type"] == "confirmation_request" and str(outside) in request["question"]
        websocket.send_json({"type": "confirmation_answer", "id": request["id"], "approved": True})
        assert receive(websocket) == {"type": "tool_finished", "id": "c1", "name": "read_file", "is_error": False}
        assert receive(websocket)["text"] == "Le fichier dit secret."


def test_refused_confirmation(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.txt").write_text("secret")
    (tmp_path / "trusted").mkdir()
    client, _ = make_client(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(outside / "note.txt")})]),
            ProviderResponse(text="Accès refusé."),
        ],
    )
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "Lis la note"})
        receive(websocket), receive(websocket)
        request = receive(websocket)
        websocket.send_json({"type": "confirmation_answer", "id": request["id"], "approved": False})
        assert receive(websocket)["is_error"] is True


def test_reset(tmp_path: Path):
    client, session = make_client(tmp_path, [ProviderResponse(text="Un")])
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "premier"})
        receive(websocket), receive(websocket)
        websocket.send_json({"type": "reset"})
        assert receive(websocket) == {"type": "reset_done"}
    assert session.agent.history == [] and session.conversation is None


class FakeLoginProcess:
    """Mimics `claude auth login`: prints the sign-in URL, then waits for the pasted code."""

    def __init__(self, logins, folder):
        self.logins, self.folder = logins, folder
        self.stdout = io.StringIO(
            "Opening browser to sign in…\nIf the browser didn't open, visit: "
            "\x1b]8;;https://claude.com/cai/oauth/authorize?code=true&x=1\x07https://claude.com/cai/oauth/authorize?code=true&x=1\x1b]8;;\x07\n"
            "Paste code here if prompted > "
        )
        self.stdin = io.StringIO()
        self.returncode = None

    def wait(self, timeout=None):
        if self.stdin.getvalue().strip() == "GOOD-CODE":
            self.logins.emails_by_folder[self.folder] = "perso@example.com"
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_login_session_extracts_url_and_submits_code(tmp_path: Path):
    settings = Settings(_env_file=None, claude_code_accounts_dir=tmp_path / "accounts")
    logins = FakeLogins({})
    manager = AccountManager(settings, make_provider=logins.provider)
    folder = tmp_path / "accounts" / "perso_example_com"
    session = LoginSession(manager, "perso@example.com", popen=lambda *args, **kwargs: FakeLoginProcess(logins, folder))

    assert session.sign_in_url() == "https://claude.com/cai/oauth/authorize?code=true&x=1"
    assert session.browser_link(timeout_seconds=0) is None
    account = session.submit_code("GOOD-CODE")
    assert account.email == "perso@example.com" and account.config_dir == folder
    assert manager.chosen_account().email == "perso@example.com"


def test_sign_in_link_is_caught_instead_of_opening_the_default_browser(tmp_path: Path):
    settings = Settings(_env_file=None, claude_code_accounts_dir=tmp_path / "accounts")
    manager = AccountManager(settings, make_provider=FakeLogins({}).provider)
    folder = tmp_path / "accounts" / "perso_example_com"
    environments = []

    def popen(command, env, **kwargs):
        environments.append(env)
        script = Path(env["BROWSER"])
        assert script.read_text().startswith("#!/bin/sh")
        (folder / ".nova-sign-in-link").write_text("https://claude.com/cai/oauth/authorize?redirect_uri=http%3A%2F%2Flocalhost%3A4000%2Fcallback\n")
        return FakeLoginProcess(FakeLogins({}), folder)

    session = LoginSession(manager, "perso@example.com", popen=popen)
    assert session.browser_link() == "https://claude.com/cai/oauth/authorize?redirect_uri=http%3A%2F%2Flocalhost%3A4000%2Fcallback"
    assert Path(environments[0]["BROWSER"]).parent == folder


def test_login_session_with_bad_code(tmp_path: Path):
    settings = Settings(_env_file=None, claude_code_accounts_dir=tmp_path / "accounts")
    logins = FakeLogins({})
    manager = AccountManager(settings, make_provider=logins.provider)
    folder = tmp_path / "accounts" / "perso_example_com"
    session = LoginSession(manager, "perso@example.com", popen=lambda *args, **kwargs: FakeLoginProcess(logins, folder))
    session.sign_in_url()
    with pytest.raises(Exception, match="faux ou a expiré"):
        session.submit_code("BAD")


def test_sign_in_finished_in_the_browser_needs_no_code(tmp_path: Path):
    logins = FakeLogins({})
    client, session = make_client(tmp_path, logins=logins)
    folder = tmp_path / "accounts" / "perso_example_com"
    process = FakeLoginProcess(logins, folder)
    session.login = LoginSession(session.accounts, "perso@example.com", popen=lambda *args, **kwargs: process)
    assert client.get("/api/accounts/login/status", headers=AUTH).json() == {"account": None}

    logins.emails_by_folder[folder] = "perso@example.com"
    process.returncode = 0
    assert client.get("/api/accounts/login/status", headers=AUTH).json()["account"]["email"] == "perso@example.com"
    assert client.get("/api/status", headers=AUTH).json()["account"]["email"] == "perso@example.com"


def test_pasting_a_code_after_the_browser_already_finished_does_not_break(tmp_path: Path):
    logins = FakeLogins({})
    manager = AccountManager(Settings(_env_file=None, claude_code_accounts_dir=tmp_path / "accounts"), make_provider=logins.provider)
    folder = tmp_path / "accounts" / "perso_example_com"
    process = FakeLoginProcess(logins, folder)
    session = LoginSession(manager, "perso@example.com", popen=lambda *args, **kwargs: process)
    logins.emails_by_folder[folder] = "perso@example.com"
    process.returncode = 0
    process.stdin.close()
    assert session.submit_code("ANY").email == "perso@example.com"


def test_sign_in_with_the_wrong_browser_account_is_undone_and_explained(tmp_path: Path, monkeypatch):
    logins = FakeLogins({})
    manager = AccountManager(Settings(_env_file=None, claude_code_accounts_dir=tmp_path / "accounts"), make_provider=logins.provider)
    folder = tmp_path / "accounts" / "perso_example_com"
    process = FakeLoginProcess(logins, folder)
    session = LoginSession(manager, "perso@example.com", popen=lambda *args, **kwargs: process)
    logins.emails_by_folder[folder] = WORK
    process.returncode = 0
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda command, env, **kwargs: commands.append(command))
    with pytest.raises(Exception, match=f"connectée à {WORK}, pas à perso@example.com"):
        session.finished()
    assert commands == [["claude", "auth", "logout"]] and manager.chosen_account() is None


def test_cors_allows_the_app_window_only(tmp_path: Path):
    client, _ = make_client(tmp_path)
    preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    allowed = client.options("/api/status", headers={"Origin": "http://tauri.localhost", **preflight})
    assert allowed.headers.get("access-control-allow-origin") == "http://tauri.localhost"
    refused = client.options("/api/status", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in refused.headers


def test_cors_lets_the_app_use_every_method_its_api_client_sends(tmp_path: Path):
    client, _ = make_client(tmp_path)
    client_source = (Path(__file__).parents[1] / "desktop" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    methods = {"GET", "POST"} | set(re.findall(r'"(PUT|PATCH|DELETE)"', client_source))
    for method in methods:
        preflight = {"Origin": "http://tauri.localhost", "Access-Control-Request-Method": method, "Access-Control-Request-Headers": "authorization"}
        assert client.options("/api/conversations/abc", headers=preflight).status_code == 200, method


def test_generated_media_are_announced_and_served(tmp_path: Path):
    from nova.tools.creative import CreativeStudio, build_creative_tools

    class FixedImage:
        def generate(self, prompt, width, height):
            return b"\xff\xd8fake", "image/jpeg"

    settings = Settings(_env_file=None, provider="ollama", trusted_dirs=[tmp_path])
    scripted = ScriptedProvider([
        ProviderResponse(text="", tool_calls=[
            ToolCall(id="i1", name="generate_image", arguments={"prompt": "chalet"}),
            ToolCall(id="a1", name="create_artifact", arguments={"title": "Page", "kind": "html", "content": "<p>hi</p>"}),
        ]),
        ProviderResponse(text="Voilà !"),
    ])

    def agent_factory(agent_settings, confirmer, observer):
        access = FileAccessGuard([tmp_path], confirmer)
        registry = ToolRegistry(build_creative_tools(CreativeStudio(access, FixedImage())), confirmer)
        return Agent(scripted, registry, system_prompt="s", observer=observer)

    client = TestClient(create_app(NovaSession(settings, agent_factory=agent_factory), TOKEN))
    finished = []
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "Fais une image et une page"})
        while True:
            event = receive(websocket)
            if event["type"] == "tool_finished":
                finished.append(event)
            if event["type"] == "assistant_message":
                break

    image, page = finished[0]["media"][0], finished[1]["media"][0]
    assert image["kind"] == "image" and image["title"] == "chalet"
    served = client.get(image["url"])
    assert served.status_code == 200 and served.content == b"\xff\xd8fake" and served.headers["content-type"] == "image/jpeg"
    html = client.get(page["url"])
    assert html.headers["content-security-policy"] == "sandbox allow-scripts"
    assert client.get("/media/not-a-real-id").status_code == 404


def test_documents_can_be_downloaded_opened_and_saved(tmp_path: Path, monkeypatch):
    from nova.tools.documents import DocumentStudio, build_document_tools

    settings = Settings(_env_file=None, provider="ollama", trusted_dirs=[tmp_path])
    scripted = ScriptedProvider([
        ProviderResponse(text="", tool_calls=[ToolCall(id="d1", name="create_document", arguments={"title": "Bonjour", "format": "pdf", "content": "# Bonjour"})]),
        ProviderResponse(text="Voici ton PDF."),
    ])

    def agent_factory(agent_settings, confirmer, observer):
        registry = ToolRegistry(build_document_tools(DocumentStudio(FileAccessGuard([tmp_path], confirmer))), confirmer)
        return Agent(scripted, registry, system_prompt="s", observer=observer)

    opened = []
    monkeypatch.setattr("nova.interfaces.server.open_with_default_app", lambda path: opened.append(path))
    client = TestClient(create_app(NovaSession(settings, agent_factory=agent_factory), TOKEN))
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "Un PDF bonjour"})
        while (event := receive(websocket))["type"] != "tool_finished":
            pass
    document = event["media"][0]
    assert document["kind"] == "file" and document["file_name"] == "bonjour.pdf" and document["size"] > 0

    inline = client.get(document["url"])
    assert inline.headers["content-type"] == "application/pdf" and inline.headers["content-disposition"].startswith("inline")
    attachment = client.get(document["url"] + "?download=true")
    assert attachment.headers["content-disposition"].startswith("attachment") and 'bonjour.pdf' in attachment.headers["content-disposition"]

    assert client.post(f"/api/media/{document['id']}/open").status_code == 401
    assert client.post(f"/api/media/{document['id']}/open", headers=AUTH).status_code == 200
    assert opened == [Path(document["path"])]

    destination = tmp_path / "Téléchargements" / "bonjour.pdf"
    saved = client.post(f"/api/media/{document['id']}/save", json={"destination": str(destination)}, headers=AUTH)
    assert saved.status_code == 200 and destination.read_bytes().startswith(b"%PDF")
    assert client.post("/api/media/unknown/open", headers=AUTH).status_code == 404


def chat_turn(websocket, text):
    websocket.send_json({"type": "user_message", "text": text})
    while (event := websocket.receive_json())["type"] not in ("assistant_message", "error"):
        pass
    return event


def test_conversations_are_saved_listed_reopened_and_continued(tmp_path: Path):
    (tmp_path / "trusted").mkdir()
    (tmp_path / "trusted" / "note.txt").write_text("rdv 14h")
    client, session = make_client(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "note.txt"})]),
            ProviderResponse(text="Rendez-vous à 14h."),
            ProviderResponse(text="Salut !"),
            ProviderResponse(text="Toujours 14h."),
        ],
    )
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        chat_turn(websocket, "Lis ma note")
        first_id = client.get("/api/conversations", headers=AUTH).json()["current"]
        assert client.post("/api/conversations/new", headers=AUTH).status_code == 200
        chat_turn(websocket, "Bonjour")

    listing = client.get("/api/conversations", headers=AUTH).json()
    assert [conversation["title"] for conversation in listing["conversations"]] == ["Bonjour", "Lis ma note"]

    opened = client.post(f"/api/conversations/{first_id}/open", headers=AUTH).json()
    assert [item["kind"] for item in opened["items"]] == ["user", "tool", "assistant"]
    assert opened["items"][1]["status"] == "done" and opened["items"][1]["name"] == "read_file"

    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        assert chat_turn(websocket, "Et l'heure ?")["text"] == "Toujours 14h."
    continued = session.agent.provider.received_histories[-1]
    assert [message.content for message in continued if message.role == "user"] == ["Lis ma note", "Et l'heure ?"]
    assert len(client.post(f"/api/conversations/{first_id}/open", headers=AUTH).json()["items"]) == 5


def test_model_can_be_changed_from_the_chat_and_is_kept_for_next_launches(tmp_path: Path):
    client, session = make_client(tmp_path)
    select(client)
    listed = client.get("/api/models", headers=AUTH).json()
    assert [option["id"] for option in listed["options"]] == ["haiku", "sonnet", "opus", "fable"]
    session.get_agent()

    chosen = client.post("/api/models", json={"model": "opus"}, headers=AUTH).json()
    assert chosen["current"] == "opus" and session.settings.claude_code_model == "opus"
    assert session.agent is None
    assert "NOVA_CLAUDE_CODE_MODEL='opus'" in (tmp_path / ".env").read_text()
    assert client.post("/api/models", json={"model": "gpt-4"}, headers=AUTH).status_code == 400


def test_models_without_a_catalogue_offer_no_choice(tmp_path: Path):
    client, _ = make_client(tmp_path, provider_name="ollama")
    assert client.get("/api/models", headers=AUTH).json()["options"] == []


def test_each_conversation_keeps_its_own_model_session_across_restarts(tmp_path: Path):
    client, session = make_client(tmp_path, [ProviderResponse(text="a"), ProviderResponse(text="b"), ProviderResponse(text="c")])
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        chat_turn(websocket, "Premier sujet")
        first = session.conversation
        first.provider_session.id = "session-du-premier-sujet"
        chat_turn(websocket, "Suite")
        client.post("/api/conversations/new", headers=AUTH)
        chat_turn(websocket, "Autre sujet")
    received = session.agent.provider.received_sessions
    assert received[0] is received[1] is first.provider_session
    assert received[2] is session.conversation.provider_session and received[2].id is None

    reloaded = session.store.load(first.id)
    assert reloaded.provider_session.id == "session-du-premier-sujet"


def test_first_answer_gives_the_conversation_a_model_written_title(tmp_path: Path):
    asked = []

    def namer(provider, first_message, answer):
        asked.append((first_message, answer))
        return "Heure du rendez-vous"

    client, session = make_client(tmp_path, [ProviderResponse(text="À 14h."), ProviderResponse(text="Oui.")], namer=namer)
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        chat_turn(websocket, "c'est quand mon rdv ?")
        while (event := websocket.receive_json())["type"] != "conversation_titled":
            pass
        assert event["conversation"]["title"] == "Heure du rendez-vous"
        chat_turn(websocket, "Sûr ?")

    assert asked == [("c'est quand mon rdv ?", "À 14h.")]
    listing = client.get("/api/conversations", headers=AUTH).json()["conversations"]
    assert [conversation["title"] for conversation in listing] == ["Heure du rendez-vous"]


def test_a_title_chosen_by_the_user_is_never_replaced(tmp_path: Path):
    client, session = make_client(tmp_path, [ProviderResponse(text="ok")], namer=lambda *args: "Titre auto")
    select(client)
    session.start_conversation_if_needed("Premier message")
    session.save_conversation()
    conversation_id = session.conversation.id
    client.post(f"/api/conversations/{conversation_id}/rename", json={"title": "Mon sujet"}, headers=AUTH)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        chat_turn(websocket, "Salut")
    assert client.get("/api/conversations", headers=AUTH).json()["conversations"][0]["title"] == "Mon sujet"


def test_rename_and_delete_conversations(tmp_path: Path):
    client, session = make_client(tmp_path, [ProviderResponse(text="ok")])
    select(client)
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        chat_turn(websocket, "Premier message")
    conversation_id = client.get("/api/conversations", headers=AUTH).json()["current"]

    renamed = client.post(f"/api/conversations/{conversation_id}/rename", json={"title": "Mon sujet"}, headers=AUTH)
    assert renamed.json()["conversation"]["title"] == "Mon sujet"
    assert client.delete(f"/api/conversations/{conversation_id}", headers=AUTH).status_code == 200
    assert client.get("/api/conversations", headers=AUTH).json() == {"current": None, "conversations": []}
    assert client.delete("/api/conversations/unknown", headers=AUTH).status_code == 404
    assert client.post("/api/conversations/unknown/open", headers=AUTH).status_code == 404


def test_reopened_conversation_shows_its_files_again(tmp_path: Path):
    from nova.tools.documents import DocumentStudio, build_document_tools

    settings = Settings(_env_file=None, provider="ollama", trusted_dirs=[tmp_path])
    scripted = ScriptedProvider([
        ProviderResponse(text="", tool_calls=[ToolCall(id="d1", name="create_document", arguments={"title": "Bonjour", "format": "txt", "content": "bonjour"})]),
        ProviderResponse(text="Voilà."),
    ])

    def agent_factory(agent_settings, confirmer, observer):
        registry = ToolRegistry(build_document_tools(DocumentStudio(FileAccessGuard([tmp_path], confirmer))), confirmer)
        return Agent(scripted, registry, system_prompt="s", observer=observer)

    session = NovaSession(settings, agent_factory=agent_factory)
    client = TestClient(create_app(session, TOKEN))
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        chat_turn(websocket, "Un fichier bonjour")
    conversation_id = session.conversation.id

    restarted = NovaSession(settings, agent_factory=agent_factory)
    fresh_client = TestClient(create_app(restarted, TOKEN))
    items = fresh_client.post(f"/api/conversations/{conversation_id}/open", headers=AUTH).json()["items"]
    document = items[1]["media"][0]
    assert document["file_name"] == "bonjour.txt"
    assert fresh_client.get(document["url"]).text == "bonjour"


def test_uploaded_files_reach_the_model_and_stay_in_history(tmp_path: Path):
    client, session = make_client(tmp_path, [ProviderResponse(text="Une note de rendez-vous.")])
    select(client)
    uploaded = client.post("/api/uploads", files={"file": ("note.txt", b"rdv chez le dentiste 14h", "text/plain")}, headers=AUTH)
    assert uploaded.status_code == 200
    upload = uploaded.json()
    assert upload["attachment"]["file_name"] == "note.txt" and upload["attachment"]["kind"] == "file"
    assert client.post("/api/uploads", files={"file": ("x.txt", b"x")}).status_code == 401

    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "", "attachments": [upload["upload_id"], "unknown-id"]})
        while (event := websocket.receive_json())["type"] != "assistant_message":
            pass

    sent = session.agent.provider.received_histories[0][-1]
    assert [attachment.name for attachment in sent.attachments] == ["note.txt"]
    assert sent.attachments[0].text == "rdv chez le dentiste 14h"

    listing = client.get("/api/conversations", headers=AUTH).json()
    assert listing["conversations"][0]["title"] == "note.txt"
    items = client.post(f"/api/conversations/{listing['current']}/open", headers=AUTH).json()["items"]
    shown = items[0]["attachments"][0]
    assert shown["file_name"] == "note.txt" and client.get(shown["url"]).text == "rdv chez le dentiste 14h"


def test_attached_files_can_be_used_by_tools_without_asking(tmp_path: Path):
    from nova.interfaces.assembly import build_agent

    settings = Settings(_env_file=None, provider="ollama", trusted_dirs=[tmp_path / "work"])
    (settings.uploads_dir.expanduser() / "abc").mkdir(parents=True)
    attached = settings.uploads_dir.expanduser() / "abc" / "doc.txt"
    attached.write_text("contenu")
    agent = build_agent(settings, confirmer=None)
    result = agent.executor.execute(ToolCall(id="1", name="read_file", arguments={"path": str(attached)}))
    assert result.content.endswith("\n\ncontenu")


def test_file_explorer_endpoints(tmp_path: Path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr("nova.device.filesystem.windows_profile_from_wsl", lambda: None)
    client, session = make_client(tmp_path, [ProviderResponse(text="C'est une photo verte.")])
    select(client)
    Image.new("RGB", (400, 300), "green").save(tmp_path / "photo.png")

    assert client.get("/api/files/list", params={"path": str(tmp_path)}).status_code == 401
    listing = client.get("/api/files/list", params={"path": str(tmp_path)}, headers=AUTH).json()
    assert "photo.png" in [entry["name"] for entry in listing["entries"]]
    assert client.get("/api/files/list", params={"path": str(tmp_path / "nope")}, headers=AUTH).status_code == 400
    assert client.get("/api/files/places", headers=AUTH).json()["places"]

    thumb = client.get("/api/files/thumbnail", params={"path": str(tmp_path / "photo.png"), "token_value": TOKEN})
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert client.get("/api/files/thumbnail", params={"path": str(tmp_path / "photo.png")}).status_code == 401

    preview = client.post("/api/files/preview", json={"path": str(tmp_path / "photo.png")}, headers=AUTH).json()["media"]
    assert preview["kind"] == "image" and client.get(preview["url"]).status_code == 200

    folder = client.post("/api/files/folder", json={"parent": str(tmp_path), "name": "Classement"}, headers=AUTH).json()["entry"]
    uploaded = client.post("/api/files/upload", params={"folder": folder["path"]}, files={"file": ("a.txt", b"hello")}, headers=AUTH)
    assert uploaded.json()["entry"]["path"] == str(tmp_path / "Classement" / "a.txt")
    renamed = client.post("/api/files/rename", json={"path": str(tmp_path / "Classement" / "a.txt"), "name": "b.txt"}, headers=AUTH)
    assert renamed.json()["entry"]["name"] == "b.txt"

    attached = client.post("/api/files/attach", json={"path": str(tmp_path / "photo.png")}, headers=AUTH).json()
    with client.websocket_connect(f"/ws?token={TOKEN}") as websocket:
        websocket.send_json({"type": "user_message", "text": "Qu'est-ce que c'est ?", "attachments": [attached["upload_id"]]})
        while websocket.receive_json()["type"] != "assistant_message":
            pass
    sent = session.agent.provider.received_histories[0][-1]
    assert sent.attachments[0].path == str(tmp_path / "photo.png") and sent.attachments[0].images
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Classement", "accounts", "photo.png"]
