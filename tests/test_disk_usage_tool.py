from pathlib import Path

import pytest

from nova.tools.file_access import AccessDeniedError, FileAccessGuard
from nova.tools.disk_usage import DiskUsageAnalyzer, human_size
from fakes import ScriptedConfirmer


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "video.mp4").write_bytes(b"x" * 5_000)
    (tmp_path / "big" / "nested").mkdir()
    (tmp_path / "big" / "nested" / "part.bin").write_bytes(b"x" * 3_000)
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "note.txt").write_bytes(b"x" * 100)
    (tmp_path / "loose.txt").write_bytes(b"x" * 10)
    return tmp_path


def analyzer_for(root: Path, timeout: int = 60, confirm: bool = False) -> DiskUsageAnalyzer:
    return DiskUsageAnalyzer(FileAccessGuard([root], ScriptedConfirmer(confirm)), scan_timeout_seconds=timeout)


def test_reports_total_and_subfolders_largest_first(tree: Path):
    report = analyzer_for(tree).folder_sizes(str(tree))
    assert f"Total size of {tree.resolve()}: 7.9 KB" in report
    assert report.index("big/") < report.index("small/")
    assert "7.8 KB  big/" in report


def test_reports_largest_files(tree: Path):
    report = analyzer_for(tree).folder_sizes(str(tree))
    files_section = report.split("Largest files found:")[1]
    assert files_section.index("video.mp4") < files_section.index("part.bin")


def test_limit_restricts_listed_subfolders(tree: Path):
    report = analyzer_for(tree).folder_sizes(str(tree), limit=1)
    assert "big/" in report and "small/" not in report


def test_symlinks_are_not_followed(tree: Path, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (elsewhere / "huge.bin").write_bytes(b"x" * 50_000)
    (tree / "link").symlink_to(elsewhere)
    assert "huge.bin" not in analyzer_for(tree).folder_sizes(str(tree))


def test_timeout_marks_result_as_partial(tree: Path):
    assert "sizes are partial" in analyzer_for(tree, timeout=0).folder_sizes(str(tree))


def test_folder_outside_trusted_needs_approval(tree: Path, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    with pytest.raises(AccessDeniedError):
        analyzer_for(tree, confirm=False).folder_sizes(str(other))


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024**3) == "5.0 GB"
