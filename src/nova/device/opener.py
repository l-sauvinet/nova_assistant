"""Opens a file with the user's default application (the "real render": PDF reader, Word, image viewer...)."""

import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

ProcessStarter = Callable[..., object]


def is_wsl() -> bool:
    return "microsoft" in platform.release().lower()


def open_command(path: Path, system: str | None = None, wsl: bool | None = None) -> list[str] | None:
    """Command that opens `path` with the default app, or None on Windows (os.startfile is used)."""
    system = system or platform.system()
    if system == "Windows":
        return None
    if system == "Darwin":
        return ["open", str(path)]
    if wsl if wsl is not None else is_wsl():
        if shutil.which("wslview"):
            return ["wslview", str(path)]
        windows_path = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, encoding="utf-8").stdout.strip()
        return ["explorer.exe", windows_path or str(path)]
    return ["xdg-open", str(path)]


def open_with_default_app(path: Path, start_process: ProcessStarter = subprocess.Popen) -> None:
    command = open_command(path)
    if command is None:
        os.startfile(path)  # type: ignore[attr-defined]
        return
    start_process(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
