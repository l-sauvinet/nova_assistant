import subprocess
from pathlib import Path

import pytest

from nova.device import access
from nova.device.filesystem import FileExplorerError


class FakeWindows:
    def __init__(self, folder: Path, returncode: int = 0, grants: bool = True):
        self.folder, self.returncode, self.grants = folder, returncode, grants
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append((command, kwargs))
        if command[0] == "wslpath":
            return subprocess.CompletedProcess(command, 0, stdout="C:\\Users\\Utilisateur\n")
        if self.grants and self.returncode == 0:
            self.folder.chmod(0o755)
        return subprocess.CompletedProcess(command, self.returncode)


@pytest.fixture
def locked(tmp_path: Path, monkeypatch):
    folder = tmp_path / "Utilisateur"
    folder.mkdir()
    folder.chmod(0o111)
    monkeypatch.setattr(access, "windows_path", lambda path, run: "C:\\Users\\Utilisateur")
    yield folder
    folder.chmod(0o755)


def test_granting_access_passes_the_path_outside_the_script(locked: Path):
    windows = FakeWindows(locked)
    entry = access.request_access(str(locked), run=windows)
    assert entry["readable"] and entry["is_dir"]
    command, options = windows.calls[-1]
    assert command[0] == "powershell.exe" and "Utilisateur" not in command[-1]
    assert options["env"][access.PATH_VARIABLE] == "C:\\Users\\Utilisateur"
    assert access.PATH_VARIABLE in options["env"]["WSLENV"]


def test_declined_windows_prompt_is_reported(locked: Path):
    with pytest.raises(FileExplorerError, match="refusée"):
        access.request_access(str(locked), run=FakeWindows(locked, returncode=access.UAC_DECLINED))


def test_failed_grant_is_reported(locked: Path):
    with pytest.raises(FileExplorerError, match="code 5"):
        access.request_access(str(locked), run=FakeWindows(locked, returncode=5))
    with pytest.raises(FileExplorerError, match="reste fermé"):
        access.request_access(str(locked), run=FakeWindows(locked, grants=False))


def test_already_readable_folder_needs_no_prompt(tmp_path: Path):
    windows = FakeWindows(tmp_path)
    assert access.request_access(str(tmp_path), run=windows)["readable"]
    assert windows.calls == []


def test_only_windows_folders_can_be_unlocked(tmp_path: Path, monkeypatch):
    folder = tmp_path / "prive"
    folder.mkdir()
    folder.chmod(0o111)
    monkeypatch.setattr(access.platform, "system", lambda: "Linux")
    try:
        with pytest.raises(FileExplorerError, match="dossiers Windows"):
            access.request_access(str(folder), run=FakeWindows(folder))
    finally:
        folder.chmod(0o755)


def test_wsl_drive_paths_are_converted(monkeypatch):
    monkeypatch.setattr(access.platform, "system", lambda: "Linux")
    monkeypatch.setattr(access, "is_wsl", lambda: True)
    windows = FakeWindows(Path("/mnt/c/Users/Utilisateur"))
    assert access.windows_path(Path("/mnt/c/Users/Utilisateur"), windows) == "C:\\Users\\Utilisateur"
    assert windows.calls[0][0] == ["wslpath", "-w", "/mnt/c/Users/Utilisateur"]
