"""Describes the user's computer to the model: system, shell, home and personal folders, detected at launch.

Nothing about a particular machine is written in the prompt files: NOVA is installed on other people's computers.
"""

import ctypes
import os
import platform
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal

from nova.device.opener import is_wsl

Shell = Literal["bash", "powershell"]

PERSONAL_FOLDERS = [
    ("Bureau", "Desktop", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"),
    ("Documents", "Documents", "FDD39AD0-238F-46AF-ADB4-6C85480369C7"),
    ("Téléchargements", "Downloads", "374DE290-123F-4565-9164-39C4925E467B"),
    ("Images", "Pictures", "33E28130-4E1E-4676-835A-98395C3BC3BB"),
    ("Musique", "Music", "4BD8D571-6D19-48D3-BE97-422220080E43"),
    ("Vidéos", "Videos", "18989B1D-99B5-455B-841C-AB7C74E4DDFC"),
]


def default_shell() -> Shell:
    return "powershell" if platform.system() == "Windows" else "bash"


def windows_known_folder(folder_id: str) -> Path | None:
    """Where Windows really keeps a personal folder (often moved into OneDrive), not just ~/Desktop."""

    class GUID(ctypes.Structure):
        _fields_ = [("data", ctypes.c_ubyte * 16)]

    guid = GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    path = ctypes.c_wchar_p()
    try:
        result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
    try:
        return Path(path.value) if result == 0 and path.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)  # type: ignore[attr-defined]


def personal_folders(profile: Path, windows: bool) -> list[tuple[str, str, Path]]:
    """(French label, English name, path) of the personal folders that exist."""
    folders = []
    for label, name, folder_id in PERSONAL_FOLDERS:
        path = (windows_known_folder(folder_id) if windows else None) or profile / name
        if path.is_dir():
            folders.append((label, name, path))
    return folders


def folder_lines(profile: Path, windows: bool) -> list[str]:
    lines = [f"- {name} / {label}: {path}" for label, name, path in personal_folders(profile, windows)]
    onedrive = os.environ.get("OneDrive") if windows else None
    if onedrive and Path(onedrive).is_dir():
        lines.append(f"- OneDrive: {onedrive}")
    elif (profile / "OneDrive").is_dir():
        lines.append(f"- OneDrive: {profile / 'OneDrive'}")
    return lines


@lru_cache(maxsize=1)
def machine_context() -> str:
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        header = [
            f"Windows {platform.release()}. run_command uses Windows PowerShell 5.1 (not bash): write PowerShell.",
            f"Home folder (~): {home}. Drives: C:\\, D:\\...",
        ]
        folders = folder_lines(home, windows=True)
    elif is_wsl():
        from nova.device.filesystem import windows_profile_from_wsl

        profile = windows_profile_from_wsl()
        header = [
            "Linux (WSL) with Windows alongside. run_command uses bash; Windows programs are reachable too "
            "(powershell.exe, cmd.exe /c).",
            f"Linux home (~): {home}. Windows drives are under /mnt/c, /mnt/d...",
        ]
        if profile is not None:
            header.append(f"Windows home: {profile}. When showing a Windows path, you may also give its Windows form (C:\\...).")
        folders = folder_lines(profile, windows=False) if profile is not None else folder_lines(home, windows=False)
    else:
        header = [f"{'macOS' if system == 'Darwin' else 'Linux'}. run_command uses bash.", f"Home folder (~): {home}."]
        folders = folder_lines(home, windows=False)
    lines = ["# The user's computer", *header]
    if folders:
        lines += ["When the user mentions one of their folders (\"mon bureau\", \"mes documents\"...), use these paths:", *folders]
    return "\n".join(lines)
