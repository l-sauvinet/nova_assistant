"""Grants the user read access to a Windows folder they are locked out of (another account's profile...).

Windows asks for administrator approval (UAC); the folder path travels through an environment variable,
never inside the PowerShell script, so no path can inject a command.
"""

import os
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

from nova.device.filesystem import FileExplorerError, entry_payload
from nova.device.opener import is_wsl

Runner = Callable[..., subprocess.CompletedProcess]

ACCESS_TIMEOUT_SECONDS = 600
UAC_DECLINED = 1223
PATH_VARIABLE = "NOVA_ACCESS_PATH"
GRANT_SCRIPT = (
    "$user = \"$env:USERDOMAIN\\$env:USERNAME\"; "
    f"$target = $env:{PATH_VARIABLE}; "
    "try { "
    "$process = Start-Process -FilePath icacls.exe "
    "-ArgumentList @(('\"' + $target + '\"'), '/grant', ('\"' + $user + ':(OI)(CI)RX\"')) "
    "-Verb RunAs -WindowStyle Hidden -Wait -PassThru "
    f"}} catch {{ exit {UAC_DECLINED} }}; "
    "exit $process.ExitCode"
)


def windows_path(folder: Path, run: Runner) -> str:
    if platform.system() == "Windows":
        return str(folder)
    parts = folder.parts
    if is_wsl() and len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1:
        converted = run(["wslpath", "-w", str(folder)], capture_output=True, text=True, encoding="utf-8", timeout=10).stdout.strip()
        if converted:
            return converted
    raise FileExplorerError("Demander l'accès ne marche que pour les dossiers Windows (C:, D:…).")


def request_access(raw_path: str, run: Runner = subprocess.run) -> dict:
    folder = Path(raw_path)
    if not folder.is_dir():
        raise FileExplorerError("Ce dossier n'existe plus.")
    if os.access(folder, os.R_OK | os.X_OK):
        return entry_payload(folder)
    target = windows_path(folder, run)
    environment = {**os.environ, PATH_VARIABLE: target, "WSLENV": f"{os.environ.get('WSLENV', '')}:{PATH_VARIABLE}".strip(":")}
    try:
        result = run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", GRANT_SCRIPT],
            capture_output=True,
            timeout=ACCESS_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            env=environment,
            cwd="/mnt/c" if Path("/mnt/c").is_dir() else None,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FileExplorerError(f"Windows n'a pas répondu : {error}") from error
    if result.returncode == UAC_DECLINED:
        raise FileExplorerError("Accès non accordé : la fenêtre de Windows a été refusée.")
    if result.returncode != 0:
        raise FileExplorerError(f"Windows n'a pas pu donner l'accès (code {result.returncode}).")
    if not os.access(folder, os.R_OK | os.X_OK):
        raise FileExplorerError("Windows a accepté, mais le dossier reste fermé. Réessaie après un redémarrage de NOVA.")
    return entry_payload(folder)
