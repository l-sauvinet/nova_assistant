from pathlib import Path

from nova.core.messages import Media, Message, ToolCall, ToolResult
from nova.interfaces.history import ConversationStore, title_from


def test_conversation_round_trip_keeps_agent_history_and_display(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conversation = store.new("Fais-moi un PDF bonjour")
    conversation.messages += [
        Message(role="user", content="Fais-moi un PDF bonjour"),
        Message(role="assistant", tool_calls=[ToolCall(id="c1", name="create_document", arguments={"title": "Bonjour"})]),
        Message(role="tool", tool_results=[ToolResult(call_id="c1", name="create_document", content="ok", media=[Media("/w/b.pdf", "file", "Bonjour")])]),
    ]
    conversation.add_item({"kind": "user", "text": "Fais-moi un PDF bonjour"})
    conversation.add_item({"kind": "tool", "id": "c1", "name": "create_document", "arguments": {}, "status": "running", "media": []})
    conversation.update_tool("c1", "done", [Media("/w/b.pdf", "file", "Bonjour")])
    store.save(conversation)

    loaded = store.load(conversation.id)
    assert loaded.title == "Fais-moi un PDF bonjour"
    assert loaded.messages == conversation.messages
    assert loaded.items[1] == {"kind": "tool", "id": "c1", "name": "create_document", "arguments": {}, "status": "done",
                               "media": [{"path": "/w/b.pdf", "kind": "file", "title": "Bonjour"}]}


def test_list_is_most_recent_first(tmp_path: Path):
    store = ConversationStore(tmp_path)
    old, recent = store.new("ancienne"), store.new("récente")
    old.updated_at, recent.updated_at = "2026-09-01T10:00:00+00:00", "2026-09-29T10:00:00+00:00"
    store.save(old)
    store.save(recent)
    assert [summary["title"] for summary in store.list()] == ["récente", "ancienne"]


def test_rename_and_delete(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conversation = store.new("x")
    store.save(conversation)
    assert store.rename(conversation.id, "  Recette   de crêpes ").title == "Recette de crêpes"
    assert store.delete(conversation.id) and store.list() == []
    assert not store.delete(conversation.id)


def test_corrupted_or_foreign_files_are_ignored(tmp_path: Path):
    (tmp_path / "abc.json").write_text("{not json")
    store = ConversationStore(tmp_path)
    assert store.list() == [] and store.load("../../etc/passwd") is None


def test_missing_folder_means_no_conversations(tmp_path: Path):
    assert ConversationStore(tmp_path / "nope").list() == []


def test_titles_come_from_the_first_message():
    assert title_from("  Quel   temps fait-il ?\n") == "Quel temps fait-il ?"
    long_title = title_from("a" * 200)
    assert len(long_title) == 60 and long_title.endswith("…")
    assert title_from("   ") == "Nouvelle conversation"
