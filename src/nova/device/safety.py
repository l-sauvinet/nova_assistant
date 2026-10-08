"""Checks a file before NOVA opens it with its default app, since opening a program or a script runs it.

Three signals, cheapest first: the extension (programs, scripts, shortcuts), the "mark of the web" Windows
puts on downloaded files, and, for files that are risky on either count, a Microsoft Defender scan.
"""

import os
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

Runner = Callable[..., subprocess.CompletedProcess]

RUNNABLE_SUFFIXES = {
    ".exe", ".msi", ".msix", ".appx", ".com", ".scr", ".pif", ".cpl", ".msc", ".jar",
    ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".sh",
    ".lnk", ".url", ".scf", ".reg", ".application", ".appref-ms", ".chm",
    ".iso", ".img", ".vhd", ".vhdx",
    ".docm", ".xlsm", ".pptm",
}
INTERNET_ZONE = 3
DEFENDER_TIMEOUT_SECONDS = 60
DEFENDER_THREAT_FOUND = 2


def downloaded_from_internet(path: Path) -> bool:
    """Windows records where a downloaded file came from in its Zone.Identifier stream (ZoneId 3 or 4)."""
    if platform.system() != "Windows":
        return False
    try:
        marker = Path(f"{path}:Zone.Identifier").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for line in marker.splitlines():
        if line.strip().lower().startswith("zoneid="):
            try:
                return int(line.split("=", 1)[1]) >= INTERNET_ZONE
            except ValueError:
                return False
    return False


def defender_executable() -> Path | None:
    if platform.system() != "Windows":
        return None
    executable = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"
    return executable if executable.is_file() else None


def defender_found_threat(path: Path, run: Runner = subprocess.run) -> bool:
    """Scans one file without letting Defender delete it (the user decides). False when Defender is absent."""
    executable = defender_executable()
    if executable is None:
        return False
    try:
        result = run(
            [str(executable), "-Scan", "-ScanType", "3", "-File", str(path), "-DisableRemediation"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEFENDER_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == DEFENDER_THREAT_FOUND


def opening_warning(path: Path, run: Runner = subprocess.run) -> str | None:
    """Why opening `path` could harm the computer, in French for the user; None when it looks safe."""
    runnable = path.suffix.lower() in RUNNABLE_SUFFIXES
    downloaded = downloaded_from_internet(path)
    if not runnable and not downloaded:
        return None
    if defender_found_threat(path, run):
        return (
            f"🛑 Microsoft Defender a trouvé une menace dans « {path.name} ». Ne l'ouvre pas : "
            "supprime-le, ou ouvre la Sécurité Windows pour en savoir plus."
        )
    if not runnable:
        return None
    reasons = ["c'est un programme ou un script : l'ouvrir le lance sur ton ordinateur"]
    if downloaded:
        reasons.append("il vient d'Internet")
    return f"⚠️ Attention avec « {path.name} » : {', '.join(reasons)}. Ouvre-le seulement si tu sais d'où il vient."
