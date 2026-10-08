import sys

from nova.config import Settings
from nova.interfaces.account import AccountManager, AccountSelectionError
from nova.interfaces.cli import log_out, run_cli
from nova.interfaces.setup import run_setup


def add_claude_account() -> int:
    manager = AccountManager(Settings())
    try:
        account = manager.add_account()
    except (AccountSelectionError, EOFError, KeyboardInterrupt) as error:
        print(f"Login failed: {error}")
        return 1
    manager.remember(account)
    print(f"NOVA is now connected to {account.email}. It stays connected until `uv run nova logout`.")
    return 0


def main() -> None:
    if sys.argv[1:] == ["login"]:
        sys.exit(add_claude_account())
    if sys.argv[1:] == ["logout"]:
        log_out(Settings())
        sys.exit(0)
    if sys.argv[1:] == ["serve"]:
        from nova.interfaces.server import run_server

        run_server()
        sys.exit(0)
    if sys.argv[1:] == ["setup"]:
        run_setup()
        sys.exit(0)
    sys.exit(run_cli())


if __name__ == "__main__":
    main()
