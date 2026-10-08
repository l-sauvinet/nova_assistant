from abc import ABC, abstractmethod
from dataclasses import dataclass

from nova.core.messages import Message, ProviderResponse, ToolSpec


class ProviderError(Exception):
    pass


@dataclass
class ProviderSession:
    """What the model already holds of one conversation, so a provider that keeps sessions (Claude Code)
    sends only the new messages. Providers without sessions ignore it."""

    id: str | None = None
    sent_messages: int = 0
    fingerprint: str = ""


class Provider(ABC):
    @abstractmethod
    def complete(
        self, system_prompt: str, messages: list[Message], tools: list[ToolSpec], session: ProviderSession | None = None
    ) -> ProviderResponse: ...
