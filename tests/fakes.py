from nova.core.messages import Message, ProviderResponse, ToolSpec
from nova.providers.base import Provider, ProviderSession


class ScriptedProvider(Provider):
    """Returns pre-written responses in order and records what it received."""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = list(responses)
        self.received_histories: list[list[Message]] = []
        self.received_tools: list[list[ToolSpec]] = []
        self.received_sessions: list[ProviderSession | None] = []

    def complete(
        self, system_prompt: str, messages: list[Message], tools: list[ToolSpec], session: ProviderSession | None = None
    ) -> ProviderResponse:
        self.received_sessions.append(session)
        self.received_histories.append(list(messages))
        self.received_tools.append(list(tools))
        return self.responses.pop(0)


class ScriptedConfirmer:
    """Answers confirmations with `answer`, or with `answers` in order when given."""

    def __init__(self, answer: bool = False, answers: list[bool] | None = None) -> None:
        self.answer = answer
        self.answers = list(answers) if answers is not None else None
        self.questions: list[str] = []
        self.warnings: list[str | None] = []

    def confirm(self, question: str, warning: str | None = None) -> bool:
        self.questions.append(question)
        self.warnings.append(warning)
        if self.answers is not None:
            return self.answers.pop(0)
        return self.answer
