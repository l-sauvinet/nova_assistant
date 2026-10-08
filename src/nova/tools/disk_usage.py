import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from nova.tools.base import Tool, ToolError, object_schema
from nova.tools.file_access import FileAccessGuard


@dataclass
class ScanStats:
    deadline: float
    device: int | None
    unreadable_entries: int = 0
    timed_out: bool = False
    largest_files: list[tuple[int, str]] = field(default_factory=list)


class DiskUsageAnalyzer:
    def __init__(self, access: FileAccessGuard, scan_timeout_seconds: int = 60) -> None:
        self.access = access
        self.scan_timeout_seconds = scan_timeout_seconds

    def folder_sizes(self, path: str = "~", limit: int = 10, stay_on_same_disk: bool = True) -> str:
        root = self.access.resolve_for_read(path)
        if not root.is_dir():
            raise ToolError(f"Not a directory: {root}")
        stats = ScanStats(
            deadline=time.monotonic() + self.scan_timeout_seconds,
            device=root.stat().st_dev if stay_on_same_disk else None,
        )
        children: list[tuple[int, str]] = []
        loose_files_size = 0
        for entry in self._entries(root, stats):
            if self._is_real_directory(entry):
                if stats.device is not None and entry.stat(follow_symlinks=False).st_dev != stats.device:
                    continue
                children.append((self._directory_size(entry.path, stats), entry.name + "/"))
            else:
                loose_files_size += self._file_size(entry, stats)
        total = loose_files_size + sum(size for size, _ in children)

        lines = [f"Total size of {root}: {human_size(total)}", "", f"Largest items directly inside {root}:"]
        for size, name in sorted(children, reverse=True)[:limit]:
            lines.append(f"  {human_size(size):>10}  {name}")
        lines.append(f"  {human_size(loose_files_size):>10}  (files directly in this folder)")
        lines += ["", "Largest files found:"]
        for size, file_path in sorted(stats.largest_files, reverse=True)[:limit]:
            lines.append(f"  {human_size(size):>10}  {file_path}")
        if stay_on_same_disk:
            lines.append("\nOther disks/mounts inside this folder (e.g. /mnt/c) were skipped.")
        if stats.unreadable_entries:
            lines.append(f"{stats.unreadable_entries} entries could not be read (permissions) and were skipped.")
        if stats.timed_out:
            lines.append(f"Scan stopped after {self.scan_timeout_seconds}s: sizes are partial (underestimated).")
        return "\n".join(lines)

    def _directory_size(self, directory: str, stats: ScanStats) -> int:
        total = 0
        pending = [directory]
        while pending:
            if time.monotonic() > stats.deadline:
                stats.timed_out = True
                return total
            for entry in self._entries(Path(pending.pop()), stats):
                if self._is_real_directory(entry):
                    if stats.device is None or entry.stat(follow_symlinks=False).st_dev == stats.device:
                        pending.append(entry.path)
                else:
                    total += self._file_size(entry, stats)
        return total

    def _file_size(self, entry: os.DirEntry, stats: ScanStats) -> int:
        try:
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            stats.unreadable_entries += 1
            return 0
        if entry.is_file(follow_symlinks=False):
            stats.largest_files.append((size, entry.path))
            if len(stats.largest_files) > 200:
                stats.largest_files = sorted(stats.largest_files, reverse=True)[:50]
        return size

    @staticmethod
    def _is_real_directory(entry: os.DirEntry) -> bool:
        try:
            return entry.is_dir(follow_symlinks=False)
        except OSError:
            return False

    @staticmethod
    def _entries(directory: Path, stats: ScanStats) -> list[os.DirEntry]:
        try:
            with os.scandir(directory) as iterator:
                return list(iterator)
        except OSError:
            stats.unreadable_entries += 1
            return []


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def build_disk_usage_tools(analyzer: DiskUsageAnalyzer) -> list[Tool]:
    return [
        Tool(
            name="folder_sizes",
            description=(
                "Compute the total size of a folder, the size of each of its subfolders (largest first) "
                "and the largest files inside it. For a whole drive, give its root: 'C:\\' on Windows, "
                "'/mnt/c' from WSL, '/' for the Linux system."
            ),
            parameters=object_schema(
                {
                    "path": {"type": "string", "description": "Folder to analyse. Defaults to the home folder (~)."},
                    "limit": {"type": "integer", "description": "How many subfolders/files to show. Default 10."},
                    "stay_on_same_disk": {
                        "type": "boolean",
                        "description": "Skip other disks mounted inside (e.g. /mnt/c when scanning /). Default true.",
                    },
                },
                required=[],
            ),
            run=analyzer.folder_sizes,
            reads_private=True,
        )
    ]
