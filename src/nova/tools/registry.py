import json
from typing import Any

from nova.core.messages import Attachment, ToolCall, ToolResult, ToolSpec
from nova.security.exposure import Exposure, describe_findings, model_note
from nova.tools.base import Tool, ToolError, ToolOutput
from nova.tools.confirmation import Confirmer

CANCELLED_BY_USER = "Action cancelled by the user."
MAX_ARGUMENT_CHARS = 300


class ToolRegistry:
    def __init__(self, tools: list[Tool], confirmer: Confirmer, exposure: Exposure | None = None) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._confirmer = confirmer
        self.exposure = exposure or Exposure()

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def start_request(self, attachments: list[Attachment]) -> None:
        """A new user message: forget what the previous one read, and count its attachments as read."""
        self.exposure.start_request()
        for attachment in attachments:
            self.exposure.saw_private()
            self.exposure.saw_outside(attachment.name, attachment.text)

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return self._error(call, f"Unknown tool: {call.name}")

        argument_problem = self._check_arguments(tool, call.arguments)
        if argument_problem is not None:
            return self._error(call, argument_problem)

        try:
            if not self._approved(tool, call.arguments):
                return ToolResult(call_id=call.id, name=call.name, content=CANCELLED_BY_USER)
            output = tool.run(**call.arguments)
        except (ToolError, OSError) as error:
            return self._error(call, str(error))
        text, media = (output.text, output.media) if isinstance(output, ToolOutput) else (output, [])
        if tool.reads_private:
            self.exposure.saw_private()
        warning = ""
        if tool.reads_outside is not None:
            source = tool.reads_outside(**call.arguments)
            findings = self.exposure.saw_outside(source, text)
            warning = describe_findings(source, findings) if findings else ""
            text = f"{model_note(findings)}\n\n{text}"
        return ToolResult(call_id=call.id, name=call.name, content=text, media=media, warning=warning)

    def _approved(self, tool: Tool, arguments: dict[str, Any]) -> bool:
        question = tool.confirmation_prompt(**arguments) if tool.confirmation_prompt is not None else None
        warnings = [tool.danger(**arguments) if tool.danger is not None else None]
        if self.exposure.needs_approval(tool.effect):
            warnings.append(self.exposure.warning())
            question = question or self._default_question(tool, arguments)
        if question is None:
            return True
        return self._confirmer.confirm(question, warning="\n\n".join(w for w in warnings if w) or None)

    @staticmethod
    def _default_question(tool: Tool, arguments: dict[str, Any]) -> str:
        details = "\n".join(f"{name} : {shorten(value)}" for name, value in arguments.items())
        return f"Autoriser NOVA à {tool.action or f'utiliser « {tool.name} »'} ?\n{details}"

    @staticmethod
    def _check_arguments(tool: Tool, arguments: dict) -> str | None:
        known = set(tool.parameters.get("properties", {}))
        missing = [name for name in tool.parameters.get("required", []) if name not in arguments]
        unexpected = [name for name in arguments if name not in known]
        if missing:
            return f"Missing required arguments for {tool.name}: {', '.join(missing)}"
        if unexpected:
            return f"Unexpected arguments for {tool.name}: {', '.join(unexpected)}"
        return None

    @staticmethod
    def _error(call: ToolCall, message: str) -> ToolResult:
        return ToolResult(call_id=call.id, name=call.name, content=message, is_error=True)


def shorten(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= MAX_ARGUMENT_CHARS else text[:MAX_ARGUMENT_CHARS] + "…"
