from pathlib import Path

import pytest

from nova.core.messages import ToolCall
from nova.tools.base import ToolError
from nova.tools.file_access import AccessDeniedError, FileAccessGuard
from nova.tools.files import FileManager, build_file_tools
from nova.tools.registry import CANCELLED_BY_USER, ToolRegistry
from fakes import ScriptedConfirmer


@pytest.fixture
def trusted_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "trusted"
    directory.mkdir()
    return directory


@pytest.fixture
def outside_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "outside"
    directory.mkdir()
    (directory / "secret.txt").write_text("secret")
    return directory


class Setup:
    def __init__(self, trusted_dir: Path, answer: bool = False, answers: list[bool] | None = None) -> None:
        self.confirmer = ScriptedConfirmer(answer, answers)
        self.access = FileAccessGuard([trusted_dir], self.confirmer)
        self.manager = FileManager(self.access, max_read_bytes=1_000)
        self.registry = ToolRegistry(build_file_tools(self.manager), self.confirmer)

    def run(self, name: str, **arguments):
        return self.registry.execute(ToolCall(id="call-1", name=name, arguments=arguments))


@pytest.fixture
def manager(trusted_dir: Path) -> FileManager:
    return Setup(trusted_dir).manager


class TestAccessGuard:
    def test_relative_path_resolves_inside_workspace(self, trusted_dir: Path):
        guard = FileAccessGuard([trusted_dir], ScriptedConfirmer())
        assert guard.resolve("notes/a.txt") == trusted_dir.resolve() / "notes" / "a.txt"

    def test_without_trusted_dirs_workspace_is_home(self):
        assert FileAccessGuard([], ScriptedConfirmer()).base_dir == Path.home().resolve()

    def test_trusted_folder_needs_no_approval(self, trusted_dir: Path):
        confirmer = ScriptedConfirmer(False)
        FileAccessGuard([trusted_dir], confirmer).resolve_for_write("a.txt")
        assert confirmer.questions == []

    def test_outside_folder_is_refused_when_user_says_no(self, trusted_dir: Path, outside_dir: Path):
        confirmer = ScriptedConfirmer(False)
        with pytest.raises(AccessDeniedError):
            FileAccessGuard([trusted_dir], confirmer).resolve_for_read(str(outside_dir / "secret.txt"))
        assert str(outside_dir) in confirmer.questions[0]

    def test_parent_traversal_also_asks(self, trusted_dir: Path):
        confirmer = ScriptedConfirmer(False)
        with pytest.raises(AccessDeniedError):
            FileAccessGuard([trusted_dir], confirmer).resolve_for_read("../outside/secret.txt")

    def test_symlink_leaving_trusted_folder_asks(self, trusted_dir: Path, outside_dir: Path):
        (trusted_dir / "link").symlink_to(outside_dir)
        with pytest.raises(AccessDeniedError):
            FileAccessGuard([trusted_dir], ScriptedConfirmer(False)).resolve_for_read("link/secret.txt")

    def test_read_approval_is_asked_once_per_folder(self, trusted_dir: Path, outside_dir: Path):
        (outside_dir / "sub").mkdir()
        confirmer = ScriptedConfirmer(True)
        guard = FileAccessGuard([trusted_dir], confirmer)
        guard.resolve_for_read(str(outside_dir / "secret.txt"))
        guard.resolve_for_read(str(outside_dir / "sub"))
        assert len(confirmer.questions) == 1

    def test_read_approval_does_not_grant_write(self, trusted_dir: Path, outside_dir: Path):
        confirmer = ScriptedConfirmer(answers=[True, False])
        guard = FileAccessGuard([trusted_dir], confirmer)
        guard.resolve_for_read(str(outside_dir / "secret.txt"))
        with pytest.raises(AccessDeniedError):
            guard.resolve_for_write(str(outside_dir / "secret.txt"))
        assert "modifier" in confirmer.questions[1]

    def test_write_approval_grants_read(self, trusted_dir: Path, outside_dir: Path):
        confirmer = ScriptedConfirmer(True)
        guard = FileAccessGuard([trusted_dir], confirmer)
        guard.resolve_for_write(str(outside_dir / "secret.txt"))
        guard.resolve_for_read(str(outside_dir / "secret.txt"))
        assert len(confirmer.questions) == 1

    def test_refusal_is_not_remembered(self, trusted_dir: Path, outside_dir: Path):
        confirmer = ScriptedConfirmer(answers=[False, True])
        guard = FileAccessGuard([trusted_dir], confirmer)
        with pytest.raises(AccessDeniedError):
            guard.resolve_for_read(str(outside_dir))
        assert guard.resolve_for_read(str(outside_dir)) == outside_dir.resolve()

    def test_protected_folders(self, trusted_dir: Path, outside_dir: Path):
        guard = FileAccessGuard([trusted_dir], ScriptedConfirmer())
        assert guard.is_protected(Path("/"))
        assert guard.is_protected(Path.home().resolve())
        assert guard.is_protected(trusted_dir.resolve())
        assert not guard.is_protected(outside_dir.resolve())


class TestOutsideTrustedFolders:
    def test_read_outside_with_approval(self, trusted_dir: Path, outside_dir: Path):
        setup = Setup(trusted_dir, answer=True)
        assert setup.run("read_file", path=str(outside_dir / "secret.txt")).content.endswith("\n\nsecret")

    def test_read_outside_refused(self, trusted_dir: Path, outside_dir: Path):
        result = Setup(trusted_dir, answer=False).run("read_file", path=str(outside_dir / "secret.txt"))
        assert result.is_error and "refused" in result.content

    def test_edit_outside_asks_write_access(self, trusted_dir: Path, outside_dir: Path):
        setup = Setup(trusted_dir, answer=True)
        setup.run("edit_file", path=str(outside_dir / "secret.txt"), old_text="secret", new_text="public")
        assert (outside_dir / "secret.txt").read_text() == "public"
        assert "modifier" in setup.confirmer.questions[0]

    def test_delete_outside_asks_access_then_deletion(self, trusted_dir: Path, outside_dir: Path):
        setup = Setup(trusted_dir, answers=[True, False])
        result = setup.run("delete_path", path=str(outside_dir / "secret.txt"))
        assert result.content == CANCELLED_BY_USER
        assert (outside_dir / "secret.txt").exists()
        assert len(setup.confirmer.questions) == 2


class TestListAndRead:
    def test_list_directory_shows_folders_then_files(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "b.txt").write_text("hello")
        (trusted_dir / "a_folder").mkdir()
        listing = manager.list_directory()
        assert listing.index("a_folder/") < listing.index("b.txt")
        assert "(5 bytes)" in listing

    def test_list_empty_directory(self, manager: FileManager):
        assert "is empty" in manager.list_directory()

    def test_read_file_returns_content(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "note.md").write_text("# Title", encoding="utf-8")
        assert manager.read_file("note.md") == "# Title"

    def test_read_missing_file_fails(self, manager: FileManager):
        with pytest.raises(ToolError, match="File not found"):
            manager.read_file("missing.txt")

    def test_read_too_large_file_fails(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "big.txt").write_text("x" * 2_000)
        with pytest.raises(ToolError, match="too large"):
            manager.read_file("big.txt")

    def test_read_binary_file_fails(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "image.bin").write_bytes(b"\xff\xfe\x00\x81")
        with pytest.raises(ToolError, match="not a UTF-8"):
            manager.read_file("image.bin")


class TestCreateAndEdit:
    def test_create_new_file_needs_no_confirmation(self, trusted_dir: Path):
        setup = Setup(trusted_dir, answer=False)
        assert not setup.run("create_file", path="sub/new.txt", content="hi").is_error
        assert (trusted_dir / "sub" / "new.txt").read_text() == "hi"
        assert setup.confirmer.questions == []

    def test_overwrite_asks_confirmation_and_respects_refusal(self, trusted_dir: Path):
        (trusted_dir / "note.txt").write_text("original")
        setup = Setup(trusted_dir, answer=False)
        assert setup.run("create_file", path="note.txt", content="replaced").content == CANCELLED_BY_USER
        assert (trusted_dir / "note.txt").read_text() == "original"
        assert "Écraser" in setup.confirmer.questions[0]

    def test_overwrite_proceeds_when_confirmed(self, trusted_dir: Path):
        (trusted_dir / "note.txt").write_text("original")
        result = Setup(trusted_dir, answer=True).run("create_file", path="note.txt", content="replaced")
        assert "Overwrote" in result.content
        assert (trusted_dir / "note.txt").read_text() == "replaced"

    def test_edit_replaces_unique_excerpt(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "todo.txt").write_text("buy milk\ncall mom\n")
        manager.edit_file("todo.txt", old_text="call mom", new_text="call dad")
        assert (trusted_dir / "todo.txt").read_text() == "buy milk\ncall dad\n"

    def test_edit_fails_when_excerpt_is_missing(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "todo.txt").write_text("buy milk")
        with pytest.raises(ToolError, match="not found"):
            manager.edit_file("todo.txt", old_text="eggs", new_text="bread")

    def test_edit_fails_when_excerpt_is_ambiguous(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "todo.txt").write_text("a a")
        with pytest.raises(ToolError, match="2 times"):
            manager.edit_file("todo.txt", old_text="a", new_text="b")


class TestMoveAndDelete:
    def test_move_is_cancelled_when_refused(self, trusted_dir: Path):
        (trusted_dir / "a.txt").write_text("a")
        setup = Setup(trusted_dir, answer=False)
        assert setup.run("move_path", source="a.txt", destination="b.txt").content == CANCELLED_BY_USER
        assert (trusted_dir / "a.txt").exists()
        assert len(setup.confirmer.questions) == 1

    def test_move_into_directory_when_confirmed(self, trusted_dir: Path):
        (trusted_dir / "a.txt").write_text("a")
        (trusted_dir / "archive").mkdir()
        Setup(trusted_dir, answer=True).run("move_path", source="a.txt", destination="archive")
        assert (trusted_dir / "archive" / "a.txt").read_text() == "a"
        assert not (trusted_dir / "a.txt").exists()

    def test_move_never_overwrites(self, trusted_dir: Path):
        (trusted_dir / "a.txt").write_text("a")
        (trusted_dir / "b.txt").write_text("b")
        setup = Setup(trusted_dir, answer=True)
        assert setup.run("move_path", source="a.txt", destination="b.txt").is_error
        assert (trusted_dir / "b.txt").read_text() == "b"
        assert setup.confirmer.questions == []

    def test_move_outside_refused_before_move_confirmation(self, trusted_dir: Path, outside_dir: Path):
        (trusted_dir / "a.txt").write_text("a")
        setup = Setup(trusted_dir, answer=False)
        result = setup.run("move_path", source="a.txt", destination=str(outside_dir / "a.txt"))
        assert result.is_error and "refused" in result.content
        assert (trusted_dir / "a.txt").exists()
        assert len(setup.confirmer.questions) == 1

    def test_delete_is_cancelled_when_refused(self, trusted_dir: Path):
        (trusted_dir / "a.txt").write_text("a")
        assert Setup(trusted_dir, answer=False).run("delete_path", path="a.txt").content == CANCELLED_BY_USER
        assert (trusted_dir / "a.txt").exists()

    def test_delete_directory_when_confirmed(self, trusted_dir: Path):
        folder = trusted_dir / "old"
        folder.mkdir()
        (folder / "x.txt").write_text("x")
        setup = Setup(trusted_dir, answer=True)
        setup.run("delete_path", path="old")
        assert not folder.exists()
        assert "1 élément(s)" in setup.confirmer.questions[0]

    def test_trusted_root_cannot_be_deleted(self, trusted_dir: Path):
        result = Setup(trusted_dir, answer=True).run("delete_path", path=str(trusted_dir))
        assert result.is_error and "protected" in result.content
        assert trusted_dir.exists()

    def test_home_cannot_be_deleted(self, trusted_dir: Path):
        result = Setup(trusted_dir, answer=True).run("delete_path", path="~")
        assert result.is_error and "protected" in result.content


class TestSearch:
    def test_search_by_name_pattern(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "deep" / "er").mkdir(parents=True)
        (trusted_dir / "deep" / "er" / "report.md").write_text("q3")
        (trusted_dir / "other.txt").write_text("x")
        result = manager.search_files(pattern="*.md")
        assert "report.md" in result
        assert "other.txt" not in result

    def test_search_by_content(self, manager: FileManager, trusted_dir: Path):
        (trusted_dir / "a.txt").write_text("invoice 42")
        (trusted_dir / "b.txt").write_text("nothing")
        result = manager.search_files(text="invoice")
        assert "a.txt" in result
        assert "b.txt" not in result

    def test_search_without_match(self, manager: FileManager):
        assert manager.search_files(pattern="*.pdf") == "No matching files found."

    def test_search_skips_symlinks_to_unapproved_folders(self, manager: FileManager, trusted_dir: Path, outside_dir: Path):
        (trusted_dir / "escape.txt").symlink_to(outside_dir / "secret.txt")
        assert "escape.txt" not in manager.search_files(pattern="*.txt")


class TestRegistry:
    def test_unknown_tool_returns_error(self, trusted_dir: Path):
        assert Setup(trusted_dir).run("format_disk").is_error

    def test_missing_argument_returns_error(self, trusted_dir: Path):
        result = Setup(trusted_dir).run("read_file")
        assert result.is_error and "path" in result.content

    def test_unexpected_argument_returns_error(self, trusted_dir: Path):
        result = Setup(trusted_dir).run("read_file", path="a.txt", force=True)
        assert result.is_error and "force" in result.content

    def test_specs_expose_all_file_tools(self, trusted_dir: Path):
        assert {spec.name for spec in Setup(trusted_dir).registry.specs()} == {
            "list_directory", "read_file", "create_file", "edit_file", "move_path", "delete_path", "search_files",
        }
