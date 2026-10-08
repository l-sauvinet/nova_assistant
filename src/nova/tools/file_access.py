from enum import Enum
from pathlib import Path

from nova.security.exposure import Exposure
from nova.tools.base import ToolError
from nova.tools.confirmation import Confirmer


class AccessDeniedError(ToolError):
    pass


class AccessLevel(Enum):
    READ = "read"
    WRITE = "write"


class FileAccessGuard:
    """Decides which folders NOVA may read or modify.

    Trusted folders (NOVA_TRUSTED_DIRS) are open for reading and writing. Any other folder of the
    computer requires the user's approval, asked once per folder and access level, and remembered
    for the session. A write approval also grants reading.
    """

    def __init__(self, trusted_dirs: list[Path], confirmer: Confirmer, exposure: Exposure | None = None) -> None:
        self.trusted_dirs = [directory.expanduser().resolve() for directory in trusted_dirs]
        self.confirmer = confirmer
        self.exposure = exposure
        self.base_dir = self.trusted_dirs[0] if self.trusted_dirs else Path.home().resolve()
        self._granted: dict[AccessLevel, list[Path]] = {AccessLevel.READ: [], AccessLevel.WRITE: []}

    def resolve(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()

    def resolve_for_read(self, raw_path: str) -> Path:
        return self._require(self.resolve(raw_path), AccessLevel.READ)

    def resolve_for_write(self, raw_path: str) -> Path:
        return self._require(self.resolve(raw_path), AccessLevel.WRITE)

    def can_read(self, resolved_path: Path) -> bool:
        return self._is_covered(resolved_path, AccessLevel.READ)

    def is_protected(self, resolved_path: Path) -> bool:
        """Folders too important to be deleted or moved as a whole, even with confirmation."""
        return (
            resolved_path == Path(resolved_path.anchor)
            or resolved_path == Path.home().resolve()
            or resolved_path in self.trusted_dirs
            or resolved_path.is_mount()
        )

    def _require(self, resolved_path: Path, level: AccessLevel) -> Path:
        if self._is_covered(resolved_path, level):
            return resolved_path
        folder = resolved_path if resolved_path.is_dir() else resolved_path.parent
        action = "lire" if level is AccessLevel.READ else "lire ET modifier"
        warning = self.exposure.warning() if self.exposure is not None else None
        if not self.confirmer.confirm(f"Autoriser NOVA à {action} le dossier {folder} (et ses sous-dossiers) ?", warning=warning):
            raise AccessDeniedError(
                f"The user refused {level.value} access to {folder}. Do not retry unless the user asks."
            )
        self._granted[level].append(folder)
        return resolved_path

    def _is_covered(self, resolved_path: Path, level: AccessLevel) -> bool:
        levels = [AccessLevel.WRITE] if level is AccessLevel.WRITE else [AccessLevel.READ, AccessLevel.WRITE]
        folders = self.trusted_dirs + [folder for granted in levels for folder in self._granted[granted]]
        return any(resolved_path.is_relative_to(folder) for folder in folders)
