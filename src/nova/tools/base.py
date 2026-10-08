from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nova.core.messages import Media, ToolSpec
from nova.security.exposure import Effect


class ToolError(Exception):
    """Expected failure of a tool; its message is sent back to the model."""


@dataclass(frozen=True)
class ToolOutput:
    """What a tool returns when it also produced files to show (otherwise it simply returns a str)."""

    text: str
    media: list[Media]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., "str | ToolOutput"]
    confirmation_prompt: Callable[..., str | None] | None = None
    """Returns a question to ask the user before running, or None when no confirmation is needed."""
    effect: Effect = "none"
    """Changing the computer or sending data out needs approval once outside content was read (see Exposure)."""
    action: str = ""
    """What the tool does, in French after "Autoriser NOVA à" (e.g. "modifier un fichier"), for approvals
    asked because of outside content when the tool has no question of its own."""
    reads_outside: Callable[..., str] | None = None
    """For tools returning outside content (web, files): names its source for the user from the arguments."""
    reads_private: bool = False
    """The tool returns the user's own data (file contents, folder listings)."""
    danger: Callable[..., str | None] | None = None
    """Returns a warning shown with the confirmation when the arguments look dangerous."""

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
