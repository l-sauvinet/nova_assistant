"""Entry point frozen by PyInstaller into the standalone `nova-engine` binary shipped with the desktop app."""

from nova.__main__ import main

if __name__ == "__main__":
    main()
