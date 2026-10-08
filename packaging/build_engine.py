"""Builds the standalone NOVA engine (Python + all deps) that the desktop installer bundles.

Run from the repository root: `uv run python packaging/build_engine.py`.
Output: `dist/nova-engine/nova-engine(.exe)` plus its support files (PyInstaller one-folder mode,
which starts much faster than one-file mode since nothing is unpacked at each launch).
"""

import os
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent

# Packages imported lazily or loading data files/native libraries at runtime: PyInstaller's static
# analysis misses them unless they are collected explicitly.
COLLECT_ALL = ["uvicorn", "ddgs", "pypdfium2", "pypdfium2_raw", "xhtml2pdf", "reportlab", "docx", "pptx", "openpyxl", "send2trash"]


def main() -> None:
    arguments = [
        str(ROOT / "packaging" / "engine_entry.py"),
        "--name=nova-engine",
        "--onedir",
        "--console",
        "--noconfirm",
        "--clean",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build' / 'pyinstaller'}",
        f"--specpath={ROOT / 'build'}",
        f"--paths={ROOT / 'src'}",
        f"--add-data={ROOT / 'src' / 'nova' / 'prompts'}{os.pathsep}nova/prompts",
        "--collect-submodules=nova",
    ]
    arguments += [f"--collect-all={package}" for package in COLLECT_ALL]
    PyInstaller.__main__.run(arguments)


if __name__ == "__main__":
    main()
