from typing import Protocol

from nova.core.messages import Attachment, Message, ToolCall, ToolResult, ToolSpec
from nova.providers.base import Provider, ProviderSession


class ToolExecutor(Protocol):
    """Runs tools on behalf of the agent. Local today, remote (Tauri app) later."""

    def specs(self) -> list[ToolSpec]: ...

    def start_request(self, attachments: list[Attachment]) -> None:
        """Called before each user message, with the files attached to it."""

    def execute(self, call: ToolCall) -> ToolResult: ...


class AgentObserver(Protocol):
    """Receives live progress (e.g. to show "reading ~/hades..." in the desktop app)."""

    def on_tool_call(self, call: ToolCall) -> None: ...

    def on_tool_result(self, result: ToolResult) -> None: ...


class SilentObserver:
    def on_tool_call(self, call: ToolCall) -> None:
        pass

    def on_tool_result(self, result: ToolResult) -> None:
        pass


class MaxTurnsExceededError(Exception):
    pass


class Agent:
    def __init__(
        self,
        provider: Provider,
        executor: ToolExecutor,
        system_prompt: str,
        max_turns: int = 10,
        observer: AgentObserver | None = None,
    ) -> None:
        self.provider = provider
        self.executor = executor
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.observer = observer or SilentObserver()
        self.history: list[Message] = []
        self.session: ProviderSession | None = None

    def ask(self, user_input: str, attachments: list[Attachment] | None = None) -> str:
        history_length_before = len(self.history)
        try:
            return self._run_turns(user_input, attachments or [])
        except BaseException:
            del self.history[history_length_before:]
            raise

    def _run_turns(self, user_input: str, attachments: list[Attachment]) -> str:
        self.history.append(Message(role="user", content=user_input, attachments=attachments))
        self.executor.start_request(attachments)
        tool_specs = self.executor.specs()

        for _ in range(self.max_turns):
            response = self.provider.complete(self.system_prompt, self.history, tool_specs, session=self.session)
            self.history.append(
                Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
            if not response.tool_calls:
                return response.text

            results = [self._execute(call) for call in response.tool_calls]
            self.history.append(Message(role="tool", tool_results=results))

        raise MaxTurnsExceededError(
            f"NOVA stopped after {self.max_turns} turns without a final answer."
        )

    def _execute(self, call: ToolCall) -> ToolResult:
        self.observer.on_tool_call(call)
        result = self.executor.execute(call)
        self.observer.on_tool_result(result)
        return result

    def reset(self) -> None:
        self.history.clear()
        if self.session is not None:
            self.session = ProviderSession()
