"""File explorer backend: what the user browses in the app's "Fichiers" section, on WSL, Linux or Windows.

These actions come from the user clicking in the app (not from the model), so they are not limited to
NOVA's trusted folders; deleting always goes to the recycle bin.
"""

import os
import platform
import string
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from nova.device.machine import personal_folders
from nova.device.opener import is_wsl

MAX_ENTRIES = 5000
MAX_SEARCH_RESULTS = 300
SEARCH_TIMEOUT_SECONDS = 8
THUMBNAIL_EDGE = 320
THUMBNAIL_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
SKIPPED_SEARCH_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "proc", "sys", "$Recycle.Bin", "AppData"}
FORBIDDEN_NAME_CHARACTERS = set('/\\:*?"<>|')
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
WINDOWS_SYSTEM_NAMES = {
    "appdata", "application data", "cookies", "local settings", "menu démarrer", "start menu", "mes documents",
    "my documents", "modèles", "templates", "recent", "sendto", "voisinage d'impression", "voisinage réseau",
    "printhood", "nethood", "intelgraphicsprofiles", "desktop.ini", "thumbs.db", "$recycle.bin",
    "system volume information", "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp",
    "config.msi", "recovery", "documents and settings", "programdata",
}


class FileExplorerError(Exception):
    pass


@dataclass(frozen=True)
class Place:
    label: str
    path: str
    icon: str
    group: str


@lru_cache(maxsize=1)
def windows_profile_from_wsl() -> Path | None:
    try:
        output = subprocess.run(
            ["cmd.exe", "/c", "echo %USERPROFILE%"],
            capture_output=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            cwd="/mnt/c" if Path("/mnt/c").is_dir() else None,
        ).stdout.decode("cp850", errors="replace")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        profile = lines[-1] if lines else ""
        if not profile or "%" in profile:
            return None
        converted = subprocess.run(["wslpath", profile], capture_output=True, text=True, encoding="utf-8", timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    path = Path(converted)
    return path if converted and path.is_dir() else None


def user_folders(profile: Path, group: str) -> list[Place]:
    folders = personal_folders(profile, windows=platform.system() == "Windows")
    return [Place(label, str(path), name.lower(), group) for label, name, path in folders]


def list_places(extra: list[tuple[str, Path]] | None = None) -> list[Place]:
    places: list[Place] = []
    home = Path.home()
    if platform.system() == "Windows":
        places.append(Place("Dossier personnel", str(home), "home", "Favoris"))
        places += user_folders(home, "Favoris")
        drives = os.listdrives() if hasattr(os, "listdrives") else [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]
        places += [Place(f"Disque {drive[0]}:", drive, "drive", "Disques") for drive in drives]
    else:
        wsl = is_wsl()
        profile = windows_profile_from_wsl() if wsl else None
        if profile is not None:
            places.append(Place("Dossier Windows", str(profile), "home", "Favoris"))
            places += user_folders(profile, "Favoris")
        places.append(Place("Dossier personnel (Linux)" if wsl else "Dossier personnel", str(home), "home", "Favoris" if not wsl else "Linux"))
        if not wsl:
            places += user_folders(home, "Favoris")
        mounts = Path("/mnt")
        if wsl and mounts.is_dir():
            places += [
                Place(f"Disque {drive.name.upper()}:", str(drive), "drive", "Disques")
                for drive in sorted(mounts.iterdir())
                if len(drive.name) == 1 and drive.is_dir()
            ]
        places.append(Place("Système Linux" if wsl else "Système", "/", "system", "Linux" if wsl else "Disques"))
    for label, path in extra or []:
        if path.is_dir():
            places.append(Place(label, str(path), "nova", "NOVA"))
    return places


def entry_payload(path: Path) -> dict:
    try:
        stat = path.stat()
        is_dir = path.is_dir()
    except OSError:
        return {"name": path.name, "path": str(path), "is_dir": False, "size": None, "modified": None, "extension": "", "hidden": True, "readable": False}
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": is_dir,
        "size": None if is_dir else stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
        "extension": "" if is_dir else path.suffix.lower().lstrip("."),
        "hidden": is_hidden(path, stat),
        "readable": os.access(path, os.R_OK | (os.X_OK if is_dir else 0)),
    }


def is_hidden(path: Path, stat: os.stat_result) -> bool:
    """Like the Windows and Linux file managers: dotfiles, Windows hidden/system files and profile internals."""
    name = path.name.lower()
    attributes = getattr(stat, "st_file_attributes", 0)
    return (
        name.startswith(".")
        or name.startswith("ntuser.")
        or name in WINDOWS_SYSTEM_NAMES
        or bool(attributes & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
    )


def list_folder(raw_path: str) -> dict:
    folder = Path(raw_path).expanduser()
    if not folder.is_dir():
        raise FileExplorerError(f"Dossier introuvable : {folder}")
    try:
        children = list(folder.iterdir())
    except PermissionError as error:
        raise FileExplorerError(f"Windows ne te laisse pas ouvrir « {folder.name or folder} » : ce dossier est protégé ou appartient à un autre compte.") from error
    entries = [entry_payload(child) for child in children[:MAX_ENTRIES]]
    entries.sort(key=lambda entry: (not entry["is_dir"], entry["name"].lower()))
    parent = str(folder.parent) if folder.parent != folder else None
    return {"path": str(folder), "name": folder.name or str(folder), "parent": parent, "entries": entries, "truncated": len(children) > MAX_ENTRIES}


def search_files(raw_root: str, query: str, deadline_seconds: float = SEARCH_TIMEOUT_SECONDS) -> dict:
    root = Path(raw_root).expanduser()
    needle = query.strip().lower()
    if not needle:
        raise FileExplorerError("Tape ce que tu cherches.")
    deadline = time.monotonic() + deadline_seconds
    results, timed_out = [], False
    for current, directories, files in os.walk(root, onerror=lambda error: None):
        directories[:] = [name for name in directories if name not in SKIPPED_SEARCH_DIRS and not name.startswith(".")]
        for name in directories + files:
            if needle in name.lower():
                results.append(entry_payload(Path(current) / name))
                if len(results) >= MAX_SEARCH_RESULTS:
                    return {"root": str(root), "query": query, "entries": results, "truncated": True}
        if time.monotonic() > deadline:
            timed_out = True
            break
    return {"root": str(root), "query": query, "entries": results, "truncated": timed_out}


def thumbnail(raw_path: str) -> bytes:
    from PIL import Image, ImageOps

    path = Path(raw_path)
    if path.suffix.lower() not in THUMBNAIL_SUFFIXES:
        raise FileExplorerError("Pas d'aperçu pour ce type de fichier.")
    try:
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE))
            output = BytesIO()
            image.convert("RGB").save(output, "JPEG", quality=78)
    except OSError as error:
        raise FileExplorerError(f"Image illisible : {error}") from error
    return output.getvalue()


def valid_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or cleaned in {".", ".."} or FORBIDDEN_NAME_CHARACTERS & set(cleaned):
        raise FileExplorerError('Nom invalide (caractères interdits : / \\ : * ? " < > |).')
    return cleaned


def create_folder(raw_parent: str, name: str) -> dict:
    target = Path(raw_parent) / valid_name(name)
    if target.exists():
        raise FileExplorerError(f"« {target.name} » existe déjà.")
    try:
        target.mkdir()
    except OSError as error:
        raise FileExplorerError(f"Impossible de créer le dossier : {error}") from error
    return entry_payload(target)


def rename(raw_path: str, new_name: str) -> dict:
    source = Path(raw_path)
    target = source.with_name(valid_name(new_name))
    if not source.exists():
        raise FileExplorerError("Ce fichier n'existe plus.")
    if target.exists():
        raise FileExplorerError(f"« {target.name} » existe déjà.")
    try:
        source.rename(target)
    except OSError as error:
        raise FileExplorerError(f"Impossible de renommer : {error}") from error
    return entry_payload(target)


def move_to_trash(raw_path: str) -> None:
    from send2trash import send2trash
    from send2trash.exceptions import TrashPermissionError

    path = Path(raw_path)
    if not path.exists():
        raise FileExplorerError("Ce fichier n'existe plus.")
    if path == Path(path.anchor) or path == Path.home():
        raise FileExplorerError("Ce dossier est protégé.")
    try:
        send2trash(str(path))
    except (OSError, TrashPermissionError) as error:
        raise FileExplorerError(f"Impossible de mettre à la corbeille : {error}") from error


def unique_destination(folder: Path, name: str) -> Path:
    candidate = folder / valid_name(Path(name).name or "fichier")
    counter = 2
    while candidate.exists():
        candidate = folder / f"{Path(name).stem} ({counter}){Path(name).suffix}"
        counter += 1
    return candidate
