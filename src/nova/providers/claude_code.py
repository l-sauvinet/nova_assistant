"""Provider backed by the Claude Code CLI in headless mode (`claude -p`), using the user's subscription.

Claude Code's built-in tools are disabled (`--tools ""`), so the CLI can never touch the machine itself.
Each NOVA conversation keeps its own Claude Code session (`--session-id`, then `--resume`): only the new
messages are sent, and the model reuses its prompt cache for the rest. The CLI output is read as a live event stream: when the model calls a NOVA tool by name, NOVA takes that
call and stops the CLI before it can answer "No such tool"; the model can also list calls in its structured
output (`--json-schema`). NOVA's agent loop executes them, so confirmations and permissions stay under its control.
"""

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from nova.core.messages import Message, ProviderResponse, ToolCall, ToolSpec
from nova.providers.attachments import image_base64, image_paths, user_text
from nova.providers.base import Provider, ProviderError, ProviderSession

CLI_NOT_FOUND_MESSAGE = (
    "La CLI Claude Code (`{cli_path}`) est introuvable sur cet ordinateur. Installe-la depuis "
    "https://claude.com/claude-code, connecte-toi une fois avec `claude` dans un terminal, puis relance NOVA."
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["answer", "tool_calls"]},
        "text": {"type": "string", "description": "Answer to the user, or a short note before tool calls."},
        "tool_calls": {
            "type": "array",
            "description": "NOVA tools to run, when kind is tool_calls.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
    },
    "required": ["kind", "text"],
}

TOOL_PROTOCOL = """\
# NOVA tools
NOVA runs the tools listed below on the user's machine; they are always available.
- To use one, call it directly by its name with its arguments, like a normal function. NOVA intercepts
  the call, runs it, and the result appears in the conversation as a [tool result] entry; then continue.
  (Listing calls in StructuredOutput with kind="tool_calls" also works.)
- To reply to the user: call StructuredOutput with kind="answer" and the reply in `text`.
- Never tell the user a tool is unavailable: use it.

Tool catalogue (name, description, JSON Schema of arguments):
{tools}
"""

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessStarter = Callable[..., subprocess.Popen]

API_BILLING_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
SESSION_NOT_FOUND = "No conversation found"


class SessionNotFoundError(ProviderError):
    pass


class ClaudeCodeProvider(Provider):
    def __init__(
        self,
        cli_path: str = "claude",
        model: str | None = None,
        timeout_seconds: int = 300,
        config_dir: Path | None = None,
        sessions_dir: Path = Path("~/.nova/claude-sessions"),
        run_command: CommandRunner = subprocess.run,
        start_process: ProcessStarter = subprocess.Popen,
    ) -> None:
        self.cli_path = cli_path
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.config_dir = config_dir.expanduser() if config_dir is not None else None
        self.sessions_dir = sessions_dir.expanduser()
        self.run_command = run_command
        self.start_process = start_process

    def cli_environment(self) -> dict[str, str]:
        """Uses NOVA's own Claude account folder, and never an API key, so usage stays on the subscription."""
        environment = {key: value for key, value in os.environ.items() if key not in API_BILLING_VARIABLES}
        if self.config_dir is not None:
            environment["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        return environment

    def account_email(self) -> str | None:
        """Email of the Claude account the CLI is logged into, or None when logged out."""
        try:
            completed = self.run_command(
                [self.cli_path, "auth", "status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                env=self.cli_environment(),
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as error:
            raise ProviderError(CLI_NOT_FOUND_MESSAGE.format(cli_path=self.cli_path)) from error
        except subprocess.TimeoutExpired as error:
            raise ProviderError("Claude Code CLI did not answer `claude auth status`.") from error
        try:
            status = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        return status.get("email") if status.get("loggedIn") else None

    def logout_command(self) -> list[str]:
        return [self.cli_path, "auth", "logout"]

    def login_command(self, email: str | None) -> list[str]:
        command = [self.cli_path, "auth", "login", "--claudeai"]
        if email:
            command += ["--email", email]
        return command

    def complete(
        self, system_prompt: str, messages: list[Message], tools: list[ToolSpec], session: ProviderSession | None = None
    ) -> ProviderResponse:
        full_prompt = build_system_prompt(system_prompt, tools)
        tool_names = {tool.name for tool in tools}
        if session is None:
            return self._run(self.build_command(full_prompt), build_input_message(messages), tool_names, Path(tempfile.gettempdir()))
        fingerprint = hashlib.sha256(f"{self.config_dir}\n{full_prompt}".encode()).hexdigest()
        try:
            if session.id and session.fingerprint == fingerprint and 0 < session.sent_messages < len(messages):
                try:
                    response = self._run(
                        self.build_command(full_prompt, ["--resume", session.id]),
                        build_input_message(messages[session.sent_messages :], continuation=True),
                        tool_names,
                        self.sessions_dir,
                    )
                    session.sent_messages = len(messages) + 1
                    return response
                except SessionNotFoundError:
                    pass
            session.id, session.fingerprint = str(uuid.uuid4()), fingerprint
            response = self._run(
                self.build_command(full_prompt, ["--session-id", session.id]), build_input_message(messages), tool_names, self.sessions_dir
            )
        except ProviderError:
            session.id, session.sent_messages = None, 0
            raise
        session.sent_messages = len(messages) + 1
        return response

    def _run(self, command: list[str], input_message: dict[str, Any], tool_names: set[str], cwd: Path) -> ProviderResponse:
        """`cwd` matters: Claude Code files its sessions per working directory, so a session is resumed from where it began."""
        cwd.mkdir(parents=True, exist_ok=True)
        try:
            process = self.start_process(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=cwd,
                env=self.cli_environment(),
            )
        except FileNotFoundError as error:
            raise ProviderError(CLI_NOT_FOUND_MESSAGE.format(cli_path=self.cli_path)) from error

        timed_out = threading.Event()

        def stop_on_timeout() -> None:
            timed_out.set()
            process.kill()

        timer = threading.Timer(self.timeout_seconds, stop_on_timeout)
        timer.start()
        try:
            process.stdin.write(json.dumps(input_message) + "\n")
            process.stdin.close()
            response, other_output = read_event_stream(process.stdout, tool_names)
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()

        if response is not None:
            return response
        if timed_out.is_set():
            raise ProviderError(f"Claude Code CLI timed out after {self.timeout_seconds}s")
        details = "\n".join(other_output).strip()[-500:]
        if SESSION_NOT_FOUND in details:
            raise SessionNotFoundError(details)
        raise ProviderError(f"Claude Code CLI failed (exit {process.returncode}): {details}")

    def build_command(self, system_prompt: str, session_options: list[str] | None = None) -> list[str]:
        command = [
            self.cli_path,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--tools", "",
            "--strict-mcp-config",
            *(session_options if session_options is not None else ["--no-session-persistence"]),
            "--system-prompt", system_prompt,
            "--json-schema", json.dumps(OUTPUT_SCHEMA),
        ]
        if self.model:
            command += ["--model", self.model]
        return command


def build_system_prompt(system_prompt: str, tools: list[ToolSpec]) -> str:
    if not tools:
        return system_prompt
    tool_descriptions = json.dumps(
        [{"name": tool.name, "description": tool.description, "parameters": tool.parameters} for tool in tools],
        indent=2,
    )
    return f"{system_prompt}\n\n{TOOL_PROTOCOL.format(tools=tool_descriptions)}"


def render_transcript(messages: list[Message], continuation: bool = False) -> str:
    header = "New entries since your last turn:" if continuation else "Conversation so far (the last entry is the most recent):"
    lines = [header, ""]
    for message in messages:
        if message.role == "user":
            lines.append(f"[user]\n{user_text(message)}")
        elif message.role == "assistant":
            if message.content:
                lines.append(f"[assistant]\n{message.content}")
            for call in message.tool_calls:
                lines.append(f"[assistant tool call] {call.name} {json.dumps(call.arguments, ensure_ascii=False)}")
        else:
            for result in message.tool_results:
                status = "error" if result.is_error else "ok"
                lines.append(f"[tool result: {result.name} ({status})]\n{result.content}")
        lines.append("")
    lines.append("Write the next assistant turn.")
    return "\n".join(lines)


def build_input_message(messages: list[Message], continuation: bool = False) -> dict[str, Any]:
    """One user turn for `--input-format stream-json`: attached pictures, then the conversation transcript
    (or, when resuming a session, only the entries the model has not seen yet)."""
    content: list[dict[str, Any]] = []
    for path in image_paths(messages):
        media_type, data = image_base64(path)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    content.append({"type": "text", "text": render_transcript(messages, continuation)})
    return {"type": "user", "message": {"role": "user", "content": content}}


def read_event_stream(lines: Iterable[str], tool_names: set[str]) -> tuple[ProviderResponse | None, list[str]]:
    """Returns the model's decision as soon as it is known, plus any non-JSON output (errors)."""
    other_output: list[str] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                other_output.append(line.rstrip())
            continue
        if event.get("type") == "assistant":
            response = response_from_assistant_message(event.get("message", {}), tool_names)
            if response is not None:
                return response, other_output
        elif event.get("type") == "result":
            if event.get("is_error"):
                if any(SESSION_NOT_FOUND in str(error) for error in event.get("errors") or []):
                    raise SessionNotFoundError(str(event["errors"]))
                raise ProviderError(f"Claude Code CLI error: {event.get('result') or event.get('subtype')}")
            if isinstance(event.get("structured_output"), dict):
                return response_from_structured_output(event["structured_output"]), other_output
            return ProviderResponse(text=(event.get("result") or "").strip()), other_output
    return None, other_output


def response_from_assistant_message(message: dict[str, Any], tool_names: set[str]) -> ProviderResponse | None:
    blocks = message.get("content") or []
    text = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()
    direct_calls = [
        ToolCall(id=block.get("id") or str(uuid.uuid4()), name=block["name"], arguments=dict(block.get("input") or {}))
        for block in blocks
        if block.get("type") == "tool_use" and block.get("name") in tool_names
    ]
    if direct_calls:
        return ProviderResponse(text=text, tool_calls=direct_calls)
    for block in blocks:
        if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
            return response_from_structured_output(block.get("input") or {})
    return None


def response_from_structured_output(output: dict[str, Any]) -> ProviderResponse:
    tool_calls = [
        ToolCall(id=str(uuid.uuid4()), name=call["name"], arguments=dict(call.get("arguments") or {}))
        for call in output.get("tool_calls") or []
        if isinstance(call, dict) and call.get("name")
    ]
    if output.get("kind") != "tool_calls":
        tool_calls = []
    return ProviderResponse(text=(output.get("text") or "").strip(), tool_calls=tool_calls)
