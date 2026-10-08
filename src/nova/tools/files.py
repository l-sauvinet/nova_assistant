import shutil
from pathlib import Path

from nova.tools.base import Tool, ToolError, object_schema
from nova.tools.file_access import FileAccessGuard

MAX_SEARCH_RESULTS = 200
MAX_LISTED_ENTRIES = 500


class FileManager:
    def __init__(self, access: FileAccessGuard, max_read_bytes: int = 200_000) -> None:
        self.access = access
        self.max_read_bytes = max_read_bytes

    def list_directory(self, path: str = ".") -> str:
        directory = self.access.resolve_for_read(path)
        if not directory.is_dir():
            raise ToolError(f"Not a directory: {directory}")
        entries = sorted(directory.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower()))
        if not entries:
            return f"{directory} is empty."
        lines = [f"Contents of {directory}:"]
        for entry in entries[:MAX_LISTED_ENTRIES]:
            if entry.is_dir():
                lines.append(f"[dir]  {entry.name}/")
            else:
                lines.append(f"[file] {entry.name} ({entry.stat().st_size} bytes)")
        if len(entries) > MAX_LISTED_ENTRIES:
            lines.append(f"... {len(entries) - MAX_LISTED_ENTRIES} more entries not shown.")
        return "\n".join(lines)

    def read_file(self, path: str) -> str:
        file_path = self._existing_file(self.access.resolve_for_read(path))
        return self._read_text(file_path)

    def _read_text(self, file_path: Path) -> str:
        size = file_path.stat().st_size
        if size > self.max_read_bytes:
            raise ToolError(f"{file_path} is too large to read ({size} bytes, limit {self.max_read_bytes}).")
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ToolError(f"{file_path} is not a UTF-8 text file.") from error

    def create_file(self, path: str, content: str) -> str:
        file_path = self.access.resolve_for_write(path)
        if file_path.is_dir():
            raise ToolError(f"{file_path} is a directory.")
        existed = file_path.exists()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"{'Overwrote' if existed else 'Created'} {file_path}."

    def create_file_confirmation(self, path: str, content: str) -> str | None:
        file_path = self.access.resolve_for_write(path)
        if file_path.is_file():
            return f"Écraser le fichier existant {file_path} ?"
        return None

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        file_path = self._existing_file(self.access.resolve_for_write(path))
        current = self._read_text(file_path)
        occurrences = current.count(old_text)
        if not old_text or occurrences == 0:
            raise ToolError(f"The text to replace was not found in {file_path}.")
        if occurrences > 1:
            raise ToolError(
                f"The text to replace appears {occurrences} times in {file_path}; give a longer, unique excerpt."
            )
        file_path.write_text(current.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {file_path}."

    def move_path(self, source: str, destination: str) -> str:
        source_path, destination_path = self._move_paths(source, destination)
        shutil.move(source_path, destination_path)
        return f"Moved {source_path} to {destination_path}."

    def move_path_confirmation(self, source: str, destination: str) -> str:
        source_path, destination_path = self._move_paths(source, destination)
        return f"Déplacer {source_path} vers {destination_path} ?"

    def delete_path(self, path: str) -> str:
        target = self._deletable(path)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return f"Deleted {target}."

    def delete_path_confirmation(self, path: str) -> str:
        target = self._deletable(path)
        if target.is_dir():
            count = sum(1 for _ in target.rglob("*"))
            return f"Supprimer le dossier {target} et ses {count} élément(s) ?"
        return f"Supprimer le fichier {target} ?"

    def search_files(self, pattern: str = "*", path: str = ".", text: str | None = None) -> str:
        directory = self.access.resolve_for_read(path)
        if not directory.is_dir():
            raise ToolError(f"Not a directory: {directory}")
        matches: list[Path] = []
        for candidate in directory.rglob(pattern):
            if len(matches) >= MAX_SEARCH_RESULTS:
                break
            if not self.access.can_read(candidate.resolve()):
                continue
            if text is not None and not self._file_contains(candidate, text):
                continue
            matches.append(candidate)
        if not matches:
            return "No matching files found."
        lines = [str(match) + ("/" if match.is_dir() else "") for match in matches]
        if len(matches) >= MAX_SEARCH_RESULTS:
            lines.append(f"Stopped after {MAX_SEARCH_RESULTS} results; refine the search.")
        return "\n".join(lines)

    def _file_contains(self, candidate: Path, text: str) -> bool:
        if not candidate.is_file() or candidate.stat().st_size > self.max_read_bytes:
            return False
        try:
            return text in candidate.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return False

    @staticmethod
    def _existing_file(file_path: Path) -> Path:
        if not file_path.is_file():
            raise ToolError(f"File not found: {file_path}")
        return file_path

    def _move_paths(self, source: str, destination: str) -> tuple[Path, Path]:
        source_path = self.access.resolve_for_write(source)
        destination_path = self.access.resolve_for_write(destination)
        if not source_path.exists():
            raise ToolError(f"Source not found: {source_path}")
        if self.access.is_protected(source_path):
            raise ToolError(f"{source_path} is a protected folder and cannot be moved.")
        if destination_path.is_dir():
            destination_path = destination_path / source_path.name
        if destination_path.exists():
            raise ToolError(f"Destination already exists: {destination_path}")
        return source_path, destination_path

    def _deletable(self, path: str) -> Path:
        target = self.access.resolve_for_write(path)
        if not target.exists():
            raise ToolError(f"Not found: {target}")
        if self.access.is_protected(target):
            raise ToolError(f"{target} is a protected folder and cannot be deleted.")
        return target


def build_file_tools(manager: FileManager) -> list[Tool]:
    path_property = {
        "type": "string",
        "description": (
            "Any path on this computer (absolute, ~ for home, or relative to NOVA's workspace). "
            "Folders outside the trusted ones need the user's approval, asked automatically."
        ),
    }
    return [
        Tool(
            name="list_directory",
            description="List the files and folders of a directory.",
            parameters=object_schema({"path": path_property}, required=[]),
            run=manager.list_directory,
            reads_private=True,
        ),
        Tool(
            name="read_file",
            description="Read the content of a UTF-8 text file.",
            parameters=object_schema({"path": path_property}, required=["path"]),
            run=manager.read_file,
            reads_outside=lambda path: f"le fichier {path}",
            reads_private=True,
        ),
        Tool(
            name="create_file",
            description="Create a text file (parent folders are created). Overwriting an existing file requires user confirmation.",
            parameters=object_schema(
                {"path": path_property, "content": {"type": "string", "description": "Full file content."}},
                required=["path", "content"],
            ),
            run=manager.create_file,
            confirmation_prompt=manager.create_file_confirmation,
            effect="changes",
            action="créer un fichier",
        ),
        Tool(
            name="edit_file",
            description="Replace one unique excerpt of a text file with new text.",
            parameters=object_schema(
                {
                    "path": path_property,
                    "old_text": {"type": "string", "description": "Exact excerpt to replace; must appear once."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                required=["path", "old_text", "new_text"],
            ),
            run=manager.edit_file,
            effect="changes",
            action="modifier un fichier",
        ),
        Tool(
            name="move_path",
            description="Move or rename a file or folder. Requires user confirmation. Never overwrites.",
            parameters=object_schema(
                {"source": path_property, "destination": path_property},
                required=["source", "destination"],
            ),
            run=manager.move_path,
            confirmation_prompt=manager.move_path_confirmation,
            effect="changes",
        ),
        Tool(
            name="delete_path",
            description="Delete a file or a folder with its content. Requires user confirmation.",
            parameters=object_schema({"path": path_property}, required=["path"]),
            run=manager.delete_path,
            confirmation_prompt=manager.delete_path_confirmation,
            effect="changes",
        ),
        Tool(
            name="search_files",
            description="Recursively search files by name (glob pattern) and optionally by text content.",
            parameters=object_schema(
                {
                    "pattern": {"type": "string", "description": "Glob on file names, e.g. '*.md'. Defaults to '*'."},
                    "path": {**path_property, "description": "Folder to search in. Defaults to NOVA's workspace."},
                    "text": {"type": "string", "description": "Only keep text files containing this string."},
                },
                required=[],
            ),
            run=manager.search_files,
            reads_private=True,
        ),
    ]
