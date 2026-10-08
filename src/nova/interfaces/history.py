"""Saved conversations, like the Claude app sidebar: one JSON file per conversation on the user's machine.

Each file keeps both what the agent needs to continue (its message history) and what the app shows
(the chat items: messages, tool steps, produced files).
"""

import json
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nova.core.messages import Attachment, Media, Message, ToolCall, ToolResult
from nova.providers.base import ProviderSession

TITLE_MAX_LENGTH = 60
DEFAULT_TITLE = "Nouvelle conversation"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def title_from(text: str) -> str:
    title = " ".join(text.split())
    if len(title) <= TITLE_MAX_LENGTH:
        return title or DEFAULT_TITLE
    return title[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


def provider_session_from(data: Any) -> ProviderSession:
    if not isinstance(data, dict):
        return ProviderSession()
    try:
        return ProviderSession(id=data.get("id"), sent_messages=int(data.get("sent_messages", 0)), fingerprint=str(data.get("fingerprint", "")))
    except (TypeError, ValueError):
        return ProviderSession()


def message_to_dict(message: Message) -> dict[str, Any]:
    return asdict(message)


def message_from_dict(data: dict[str, Any]) -> Message:
    return Message(
        role=data["role"],
        content=data.get("content", ""),
        tool_calls=[ToolCall(**call) for call in data.get("tool_calls", [])],
        tool_results=[
            ToolResult(**{**result, "media": [Media(**media) for media in result.get("media", [])]})
            for result in data.get("tool_results", [])
        ],
        attachments=[Attachment(**attachment) for attachment in data.get("attachments", [])],
    )


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[Message] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    """What the app displays: {"kind": "user"|"assistant"|"error", "text"} or
    {"kind": "tool", "id", "name", "arguments", "status", "media": [{"path", "kind", "title"}], "warning"?}."""
    needs_title: bool = False
    """True until the model has named the conversation (or the user renamed it)."""
    provider_session: ProviderSession = field(default_factory=ProviderSession)

    def summary(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title, "created_at": self.created_at, "updated_at": self.updated_at}

    def to_dict(self) -> dict[str, Any]:
        return self.summary() | {
            "messages": [message_to_dict(message) for message in self.messages],
            "items": self.items,
            "needs_title": self.needs_title,
            "provider_session": asdict(self.provider_session),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        return cls(
            id=data["id"],
            title=data.get("title", DEFAULT_TITLE),
            created_at=data.get("created_at", now_iso()),
            updated_at=data.get("updated_at", now_iso()),
            messages=[message_from_dict(message) for message in data.get("messages", [])],
            items=list(data.get("items", [])),
            needs_title=bool(data.get("needs_title", False)),
            provider_session=provider_session_from(data.get("provider_session")),
        )

    def add_item(self, item: dict[str, Any]) -> None:
        self.items.append(item)
        self.updated_at = now_iso()

    def update_tool(self, call_id: str, status: str, media: list[Media], warning: str = "") -> None:
        for item in reversed(self.items):
            if item.get("kind") == "tool" and item.get("id") == call_id:
                item["status"] = status
                item["media"] = [asdict(entry) for entry in media]
                if warning:
                    item["warning"] = warning
                break
        self.updated_at = now_iso()


class ConversationStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.expanduser()
        self._writing = threading.Lock()

    def new(self, first_message: str) -> Conversation:
        timestamp = now_iso()
        return Conversation(id=secrets.token_hex(8), title=title_from(first_message), created_at=timestamp, updated_at=timestamp, needs_title=True)

    def save(self, conversation: Conversation) -> None:
        """Safe from two threads at once (a turn and the title naming share the temporary file)."""
        with self._writing:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(conversation.id)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(conversation.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(path)

    def load(self, conversation_id: str) -> Conversation | None:
        try:
            return Conversation.from_dict(json.loads(self._path(conversation_id).read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list(self) -> list[dict[str, str]]:
        if not self.directory.is_dir():
            return []
        summaries = []
        for path in self.directory.glob("*.json"):
            conversation = self.load(path.stem)
            if conversation is not None:
                summaries.append(conversation.summary())
        return sorted(summaries, key=lambda summary: summary["updated_at"], reverse=True)

    def rename(self, conversation_id: str, title: str) -> Conversation | None:
        conversation = self.load(conversation_id)
        if conversation is None:
            return None
        conversation.title = title_from(title)
        conversation.needs_title = False
        self.save(conversation)
        return conversation

    def delete(self, conversation_id: str) -> bool:
        path = self._path(conversation_id)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def _path(self, conversation_id: str) -> Path:
        if not conversation_id.isalnum():
            raise ValueError("Invalid conversation id.")
        return self.directory / f"{conversation_id}.json"
