import io
import json

import pytest

from nova.core.messages import Message, ToolCall, ToolResult, ToolSpec
from nova.providers.base import ProviderError, ProviderSession
from nova.providers.claude_code import ClaudeCodeProvider, read_event_stream, render_transcript

TOOLS = [ToolSpec(name="read_file", description="Read a file.", parameters={"type": "object"})]
TOOL_NAMES = {"read_file", "generate_image"}


def assistant(*blocks) -> str:
    return json.dumps({"type": "assistant", "message": {"content": list(blocks)}})


def result(**fields) -> str:
    return json.dumps({"type": "result", "is_error": False, "result": "", **fields})


def structured(**output) -> dict:
    return {"type": "tool_use", "id": "s1", "name": "StructuredOutput", "input": output}


def stream(*lines: str) -> list[str]:
    return [line + "\n" for line in lines]


class KeptInput(io.StringIO):
    def close(self):
        self.kept = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.stdin = KeptInput()
        self.returncode = None
        self.final_code = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        if self.returncode is None:
            self.returncode = self.final_code
        return self.returncode


class ProcessRecorder:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.commands: list[list[str]] = []
        self.environments: list[dict] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.environments.append(kwargs["env"])
        return self.process


def test_direct_tool_call_is_intercepted():
    lines = stream(
        assistant({"type": "tool_use", "id": "t1", "name": "generate_image", "input": {"prompt": "chalet"}}),
        '{"type": "user", "message": {"content": [{"type": "tool_result", "content": "No such tool"}]}}',
        assistant({"type": "text", "text": "Désolé, outil indisponible"}),
    )
    response, _ = read_event_stream(lines, TOOL_NAMES)
    assert response.tool_calls == [ToolCall(id="t1", name="generate_image", arguments={"prompt": "chalet"})]


def test_unknown_direct_call_is_ignored_and_structured_answer_used():
    lines = stream(
        assistant({"type": "tool_use", "id": "x", "name": "Bash", "input": {}}),
        assistant(structured(kind="answer", text="Bonjour")),
    )
    response, _ = read_event_stream(lines, TOOL_NAMES)
    assert response.text == "Bonjour" and response.tool_calls == []


def test_tool_calls_listed_in_structured_output():
    lines = stream(assistant(structured(kind="tool_calls", text="", tool_calls=[{"name": "read_file", "arguments": {"path": "a"}}])))
    response, _ = read_event_stream(lines, TOOL_NAMES)
    assert response.tool_calls[0].name == "read_file" and response.tool_calls[0].arguments == {"path": "a"}


def test_final_result_event_is_a_fallback():
    response, _ = read_event_stream(stream(result(structured_output={"kind": "answer", "text": "ok"})), TOOL_NAMES)
    assert response.text == "ok"
    response, _ = read_event_stream(stream(result(result="texte brut")), TOOL_NAMES)
    assert response.text == "texte brut"


def test_error_result_raises():
    with pytest.raises(ProviderError, match="rate limited"):
        read_event_stream(stream(json.dumps({"type": "result", "is_error": True, "result": "rate limited"})), TOOL_NAMES)


def test_non_json_lines_are_kept_for_error_messages():
    response, other = read_event_stream(["Not logged in\n"], TOOL_NAMES)
    assert response is None and other == ["Not logged in"]


def test_command_streams_without_builtin_tools_and_sends_transcript_on_stdin(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    recorder = ProcessRecorder(FakeProcess(stream(assistant(structured(kind="answer", text="hi")))))
    provider = ClaudeCodeProvider(model="haiku", start_process=recorder)
    assert provider.complete("You are NOVA.", [Message(role="user", content="Salut")], TOOLS).text == "hi"

    command = recorder.commands[0]
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--model") + 1] == "haiku"
    system_prompt = command[command.index("--system-prompt") + 1]
    assert "You are NOVA." in system_prompt and "read_file" in system_prompt
    assert "Salut" in recorder.process.stdin.kept
    assert "ANTHROPIC_API_KEY" not in recorder.environments[0]


def test_cli_is_stopped_once_the_decision_is_known():
    process = FakeProcess(stream(assistant({"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a"}})))
    ClaudeCodeProvider(start_process=ProcessRecorder(process)).complete("s", [Message(role="user", content="x")], TOOLS)
    assert process.killed


def test_failure_without_decision_raises_with_cli_output():
    provider = ClaudeCodeProvider(start_process=ProcessRecorder(FakeProcess(["Not logged in\n"], returncode=1)))
    with pytest.raises(ProviderError, match="Not logged in"):
        provider.complete("s", [Message(role="user", content="x")], TOOLS)


def test_missing_cli_raises_provider_error():
    def missing(*args, **kwargs):
        raise FileNotFoundError("claude")

    with pytest.raises(ProviderError, match="introuvable"):
        ClaudeCodeProvider(start_process=missing).complete("s", [Message(role="user", content="x")], TOOLS)


def test_transcript_includes_tool_calls_and_results():
    transcript = render_transcript(
        [
            Message(role="user", content="Lis a"),
            Message(role="assistant", tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "a"})]),
            Message(role="tool", tool_results=[ToolResult(call_id="1", name="read_file", content="contenu")]),
        ]
    )
    assert '[assistant tool call] read_file {"path": "a"}' in transcript
    assert "[tool result: read_file (ok)]\ncontenu" in transcript


class ScriptedCli:
    """Starts a fresh fake `claude -p` per call, each with its own scripted output."""

    def __init__(self, *outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[list[str], str, str]] = []

    def __call__(self, command, **kwargs):
        process = FakeProcess(self.outputs.pop(0))
        self.calls.append((command, process, str(kwargs["cwd"])))
        return process

    def sent(self, index: int) -> str:
        return self.calls[index][1].stdin.kept


def answer(text: str) -> list[str]:
    return stream(assistant(structured(kind="answer", text=text)))


def test_a_conversation_session_is_resumed_with_only_the_new_messages(tmp_path):
    cli = ScriptedCli(answer("Bonjour !"), answer("Véloce."))
    provider = ClaudeCodeProvider(start_process=cli, sessions_dir=tmp_path / "sessions")
    session = ProviderSession()
    history = [Message(role="user", content="Salut")]
    provider.complete("You are NOVA.", history, TOOLS, session=session)
    history += [Message(role="assistant", content="Bonjour !"), Message(role="user", content="Un synonyme de rapide ?")]
    provider.complete("You are NOVA.", history, TOOLS, session=session)

    first, second = cli.calls[0][0], cli.calls[1][0]
    assert first[first.index("--session-id") + 1] == session.id and "--no-session-persistence" not in first
    assert second[second.index("--resume") + 1] == session.id
    assert "Salut" in cli.sent(0) and "Salut" not in cli.sent(1) and "Un synonyme de rapide ?" in cli.sent(1)
    assert cli.calls[0][2] == cli.calls[1][2] == str(tmp_path / "sessions")
    assert session.sent_messages == 4


def test_tool_results_are_sent_on_the_resumed_session():
    cli = ScriptedCli(
        stream(assistant({"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a"}})),
        answer("C'est lu."),
    )
    provider = ClaudeCodeProvider(start_process=cli)
    session = ProviderSession()
    history = [Message(role="user", content="Lis a")]
    call = provider.complete("s", history, TOOLS, session=session).tool_calls[0]
    history += [
        Message(role="assistant", tool_calls=[call]),
        Message(role="tool", tool_results=[ToolResult(call_id=call.id, name="read_file", content="contenu de a")]),
    ]
    assert provider.complete("s", history, TOOLS, session=session).text == "C'est lu."
    assert "--resume" in cli.calls[1][0]
    sent = json.loads(cli.sent(1))["message"]["content"][-1]["text"]
    assert sent.startswith("New entries since your last turn:")
    assert "[tool result: read_file (ok)]\ncontenu de a" in sent and "Lis a" not in sent


def test_a_vanished_session_is_rebuilt_from_the_whole_history():
    vanished = stream(result(is_error=True, subtype="error_during_execution", errors=["No conversation found with session ID: x"]))
    cli = ScriptedCli(answer("Bonjour !"), vanished, answer("Véloce."))
    provider = ClaudeCodeProvider(start_process=cli)
    session = ProviderSession()
    history = [Message(role="user", content="Salut")]
    provider.complete("s", history, TOOLS, session=session)
    old_id = session.id
    history += [Message(role="assistant", content="Bonjour !"), Message(role="user", content="Un synonyme ?")]
    assert provider.complete("s", history, TOOLS, session=session).text == "Véloce."
    assert "--session-id" in cli.calls[2][0] and session.id != old_id
    assert "Salut" in cli.sent(2) and "Un synonyme ?" in cli.sent(2)


def test_another_account_or_prompt_starts_a_new_session(tmp_path):
    cli = ScriptedCli(answer("a"), answer("b"))
    session = ProviderSession()
    history = [Message(role="user", content="Salut")]
    ClaudeCodeProvider(start_process=cli).complete("s", history, TOOLS, session=session)
    history += [Message(role="assistant", content="a"), Message(role="user", content="Et ?")]
    ClaudeCodeProvider(start_process=cli, config_dir=tmp_path / "autre-compte").complete("s", history, TOOLS, session=session)
    assert "--session-id" in cli.calls[1][0] and "Salut" in cli.sent(1)


def test_a_failed_call_forgets_the_session():
    cli = ScriptedCli(stream(result(is_error=True, result="Overloaded")))
    session = ProviderSession(id="old", sent_messages=3, fingerprint="f")
    with pytest.raises(ProviderError, match="Overloaded"):
        ClaudeCodeProvider(start_process=cli).complete("s", [Message(role="user", content="x")], TOOLS, session=session)
    assert session.id is None and session.sent_messages == 0


def test_one_off_calls_keep_no_session():
    cli = ScriptedCli(answer("Titre"))
    ClaudeCodeProvider(start_process=cli).complete("s", [Message(role="user", content="x")], [])
    assert "--no-session-persistence" in cli.calls[0][0] and "--resume" not in cli.calls[0][0]
