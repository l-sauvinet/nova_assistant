from pathlib import Path

import pytest
from PIL import Image

from nova.device import filesystem
from nova.device.filesystem import FileExplorerError


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "Photos").mkdir()
    Image.new("RGB", (1200, 800), "green").save(tmp_path / "Photos" / "montagne.jpg")
    (tmp_path / "rapport.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / ".cache").mkdir()
    (tmp_path / "B-notes.txt").write_text("x")
    return tmp_path


def test_folder_listing_puts_folders_first_and_flags_hidden_files(tree: Path):
    listing = filesystem.list_folder(str(tree))
    names = [entry["name"] for entry in listing["entries"]]
    assert names == [".cache", "Photos", "B-notes.txt", "rapport.pdf"]
    by_name = {entry["name"]: entry for entry in listing["entries"]}
    assert by_name[".cache"]["hidden"] and not by_name["Photos"]["hidden"]
    assert by_name["rapport.pdf"]["size"] == 8 and by_name["rapport.pdf"]["extension"] == "pdf"
    assert by_name["Photos"]["size"] is None and listing["parent"] == str(tree.parent)


def test_listing_a_missing_folder_fails_clearly(tree: Path):
    with pytest.raises(FileExplorerError, match="introuvable"):
        filesystem.list_folder(str(tree / "nope"))


def test_locked_folder_is_flagged_and_refused_clearly(tree: Path):
    locked = tree / "Autre compte"
    locked.mkdir()
    locked.chmod(0o111)
    try:
        by_name = {entry["name"]: entry for entry in filesystem.list_folder(str(tree))["entries"]}
        assert not by_name["Autre compte"]["readable"] and by_name["Photos"]["readable"]
        with pytest.raises(FileExplorerError, match="autre compte"):
            filesystem.list_folder(str(locked))
    finally:
        locked.chmod(0o755)


def test_search_is_recursive_and_case_insensitive(tree: Path):
    result = filesystem.search_files(str(tree), "MONTAGNE")
    assert [entry["name"] for entry in result["entries"]] == ["montagne.jpg"]
    with pytest.raises(FileExplorerError):
        filesystem.search_files(str(tree), "  ")


def test_search_skips_heavy_technical_folders(tree: Path):
    (tree / "node_modules" / "lib").mkdir(parents=True)
    (tree / "node_modules" / "lib" / "montagne.js").write_text("x")
    assert len(filesystem.search_files(str(tree), "montagne")["entries"]) == 1


def test_thumbnails_are_small_jpegs(tree: Path):
    from io import BytesIO

    data = filesystem.thumbnail(str(tree / "Photos" / "montagne.jpg"))
    with Image.open(BytesIO(data)) as image:
        assert image.format == "JPEG" and max(image.size) == filesystem.THUMBNAIL_EDGE
    with pytest.raises(FileExplorerError):
        filesystem.thumbnail(str(tree / "rapport.pdf"))


def test_create_rename_and_trash(tree: Path, monkeypatch):
    created = filesystem.create_folder(str(tree), "Factures")
    assert created["is_dir"] and (tree / "Factures").is_dir()
    with pytest.raises(FileExplorerError, match="existe déjà"):
        filesystem.create_folder(str(tree), "Factures")
    with pytest.raises(FileExplorerError, match="invalide"):
        filesystem.create_folder(str(tree), "a/b")

    renamed = filesystem.rename(str(tree / "B-notes.txt"), "notes.txt")
    assert renamed["name"] == "notes.txt" and (tree / "notes.txt").exists()

    trashed = []
    monkeypatch.setattr("send2trash.send2trash", lambda path: trashed.append(path))
    filesystem.move_to_trash(str(tree / "notes.txt"))
    assert trashed == [str(tree / "notes.txt")]
    with pytest.raises(FileExplorerError, match="protégé"):
        filesystem.move_to_trash(str(Path.home()))


def test_unique_destination_never_overwrites(tree: Path):
    assert filesystem.unique_destination(tree, "rapport.pdf").name == "rapport (2).pdf"
    assert filesystem.unique_destination(tree, "neuf.pdf").name == "neuf.pdf"


def test_places_include_nova_folders(tree: Path, monkeypatch):
    monkeypatch.setattr(filesystem, "windows_profile_from_wsl", lambda: tree)
    places = filesystem.list_places([("Créations de NOVA", tree)])
    assert any(place.label == "Créations de NOVA" and place.group == "NOVA" for place in places)
    assert any(place.path == str(Path.home()) for place in places)


def test_windows_user_folders_are_offered_under_wsl(tree: Path, monkeypatch):
    (tree / "Desktop").mkdir()
    (tree / "Downloads").mkdir()
    monkeypatch.setattr(filesystem, "is_wsl", lambda: True)
    monkeypatch.setattr(filesystem, "windows_profile_from_wsl", lambda: tree)
    labels = {place.label: place.path for place in filesystem.list_places()}
    assert labels["Bureau"] == str(tree / "Desktop") and labels["Téléchargements"] == str(tree / "Downloads")
    assert labels["Dossier personnel (Linux)"] == str(Path.home()) and labels["Système Linux"] == "/"


def test_windows_profile_is_read_despite_cmd_warning_in_console_encoding(monkeypatch, tmp_path: Path):
    import subprocess

    warning = "'\\\\wsl.localhost\\Debian\\home\\alice'\r\nCMD.EXE a été démarré avec le chemin d'accès comme répertoire en cours.\r\n"
    answers = {
        "cmd.exe": (warning + "C:\\Users\\alice\r\n").encode("cp850"),
        "wslpath": str(tmp_path).encode(),
    }

    def fake_run(command, **kwargs):
        output = answers[command[0]]
        return subprocess.CompletedProcess(command, 0, output if "text" not in kwargs else output.decode(), b"")

    monkeypatch.setattr(filesystem.subprocess, "run", fake_run)
    filesystem.windows_profile_from_wsl.cache_clear()
    try:
        assert filesystem.windows_profile_from_wsl() == tmp_path
    finally:
        filesystem.windows_profile_from_wsl.cache_clear()


def test_windows_system_files_are_hidden_like_in_the_windows_explorer(tmp_path: Path):
    for name in ["AppData", "Menu Démarrer", "Documents", "ntuser.dat.LOG1", "NTUSER.DAT{abc}.TM.blf", "desktop.ini", "photo.jpg"]:
        (tmp_path / name).mkdir() if "." not in name else (tmp_path / name).write_text("x")
    hidden = {entry["name"]: entry["hidden"] for entry in filesystem.list_folder(str(tmp_path))["entries"]}
    assert hidden == {
        "AppData": True, "Menu Démarrer": True, "Documents": False, "ntuser.dat.LOG1": True,
        "NTUSER.DAT{abc}.TM.blf": True, "desktop.ini": True, "photo.jpg": False,
    }
