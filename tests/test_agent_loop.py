from pathlib import Path

import pytest

from nova.core.agent import Agent, MaxTurnsExceededError
from nova.core.messages import ProviderResponse, ToolCall
from nova.tools.file_access import FileAccessGuard
from nova.tools.files import FileManager, build_file_tools
from nova.tools.registry import CANCELLED_BY_USER, ToolRegistry
from fakes import ScriptedConfirmer, ScriptedProvider


def make_agent(tmp_path: Path, responses: list[ProviderResponse], confirm: bool = True, max_turns: int = 5):
    provider = ScriptedProvider(responses)
    confirmer = ScriptedConfirmer(confirm)
    registry = ToolRegistry(build_file_tools(FileManager(FileAccessGuard([tmp_path], confirmer))), confirmer)
    return Agent(provider, registry, system_prompt="You are NOVA.", max_turns=max_turns), provider


def test_direct_answer_without_tools(tmp_path: Path):
    agent, provider = make_agent(tmp_path, [ProviderResponse(text="Bonjour !")])
    assert agent.ask("Salut") == "Bonjour !"
    assert [message.role for message in agent.history] == ["user", "assistant"]
    assert len(provider.received_tools[0]) == 7


def test_tool_call_result_is_sent_back_to_provider(tmp_path: Path):
    (tmp_path / "note.txt").write_text("rendez-vous à 14h", encoding="utf-8")
    agent, provider = make_agent(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "note.txt"})]),
            ProviderResponse(text="Ta note dit : rendez-vous à 14h."),
        ],
    )
    assert agent.ask("Lis ma note") == "Ta note dit : rendez-vous à 14h."
    second_call_history = provider.received_histories[1]
    tool_message = second_call_history[-1]
    assert tool_message.role == "tool"
    assert tool_message.tool_results[0].content.endswith("\n\nrendez-vous à 14h")
    assert not tool_message.tool_results[0].is_error


def test_several_tool_calls_in_one_turn(tmp_path: Path):
    agent, provider = make_agent(
        tmp_path,
        [
            ProviderResponse(
                text="",
                tool_calls=[
                    ToolCall(id="1", name="create_file", arguments={"path": "a.txt", "content": "A"}),
                    ToolCall(id="2", name="create_file", arguments={"path": "b.txt", "content": "B"}),
                ],
            ),
            ProviderResponse(text="Deux fichiers créés."),
        ],
    )
    agent.ask("Crée a et b")
    assert (tmp_path / "a.txt").read_text() == "A"
    assert (tmp_path / "b.txt").read_text() == "B"
    assert [result.call_id for result in provider.received_histories[1][-1].tool_results] == ["1", "2"]


def test_refused_folder_access_is_reported_to_provider_not_raised(tmp_path: Path):
    agent, provider = make_agent(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "/etc/passwd"})]),
            ProviderResponse(text="Je n'ai pas accès à ce fichier."),
        ],
        confirm=False,
    )
    assert agent.ask("Lis /etc/passwd") == "Je n'ai pas accès à ce fichier."
    result = provider.received_histories[1][-1].tool_results[0]
    assert result.is_error and "refused" in result.content


def test_unknown_tool_is_reported_to_provider(tmp_path: Path):
    agent, provider = make_agent(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="1", name="send_email", arguments={})]),
            ProviderResponse(text="Je ne sais pas encore envoyer de mails."),
        ],
    )
    agent.ask("Envoie un mail")
    assert provider.received_histories[1][-1].tool_results[0].is_error


def test_refused_confirmation_leaves_file_and_informs_provider(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("important")
    agent, provider = make_agent(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="1", name="delete_path", arguments={"path": "keep.txt"})]),
            ProviderResponse(text="Suppression annulée."),
        ],
        confirm=False,
    )
    agent.ask("Supprime keep.txt")
    assert (tmp_path / "keep.txt").exists()
    assert provider.received_histories[1][-1].tool_results[0].content == CANCELLED_BY_USER


def test_conversation_history_is_kept_between_requests(tmp_path: Path):
    agent, provider = make_agent(tmp_path, [ProviderResponse(text="Un"), ProviderResponse(text="Deux")])
    agent.ask("premier")
    agent.ask("second")
    assert [message.content for message in provider.received_histories[1]] == ["premier", "Un", "second"]


def test_reset_clears_history(tmp_path: Path):
    agent, _ = make_agent(tmp_path, [ProviderResponse(text="Un")])
    agent.ask("premier")
    agent.reset()
    assert agent.history == []


def test_max_turns_stops_endless_tool_loop_and_rolls_back_history(tmp_path: Path):
    looping_call = ProviderResponse(text="", tool_calls=[ToolCall(id="1", name="list_directory", arguments={})])
    agent, _ = make_agent(tmp_path, [looping_call] * 3, max_turns=3)
    with pytest.raises(MaxTurnsExceededError):
        agent.ask("Boucle")
    assert agent.history == []


def test_provider_failure_rolls_back_history(tmp_path: Path):
    agent, _ = make_agent(tmp_path, [])
    with pytest.raises(IndexError):
        agent.ask("Bonjour")
    assert agent.history == []


def test_observer_sees_each_tool_call_and_result(tmp_path: Path):
    events = []

    class RecordingObserver:
        def on_tool_call(self, call):
            events.append(("call", call.name))

        def on_tool_result(self, result):
            events.append(("result", result.name, result.is_error))

    agent, _ = make_agent(
        tmp_path,
        [
            ProviderResponse(text="", tool_calls=[ToolCall(id="1", name="list_directory", arguments={})]),
            ProviderResponse(text="Vide."),
        ],
    )
    agent.observer = RecordingObserver()
    agent.ask("Liste")
    assert events == [("call", "list_directory"), ("result", "list_directory", False)]
