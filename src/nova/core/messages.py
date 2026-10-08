from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant", "tool"]
MediaKind = Literal["image", "svg", "html", "file"]
AttachmentKind = Literal["image", "document"]


@dataclass(frozen=True)
class ToolSpec:
    """Provider-agnostic description of a tool: name, description and JSON Schema of its arguments."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Media:
    """A file produced by a tool (generated image, SVG, HTML page) that the app can display."""

    path: str
    kind: MediaKind
    title: str


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False
    media: list[Media] = field(default_factory=list)
    warning: str = ""
    """Shown to the user when the content looked like an attack on NOVA (empty otherwise)."""


@dataclass(frozen=True)
class Attachment:
    """A file the user attached to a message, prepared for the model on the user's machine."""

    path: str
    name: str
    media_type: str
    kind: AttachmentKind
    text: str = ""
    """Extracted content of a document (empty for pictures)."""
    images: list[str] = field(default_factory=list)
    """Model-ready pictures: the resized photo, or rendered pages of a scanned PDF."""
    note: str = ""
    warning: str = ""
    """Shown to the user when the content looked like an attack on NOVA (empty otherwise)."""


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
