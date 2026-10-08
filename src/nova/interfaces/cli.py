import sys

from nova.config import Settings
from nova.core.agent import MaxTurnsExceededError
from nova.interfaces.account import AccountManager, AccountSelectionError, select_account
from nova.interfaces.assembly import build_agent, use_claude_account
from nova.providers.base import ProviderSession
from nova.interfaces.setup import run_setup
from nova.providers.base import ProviderError
from nova.tools.confirmation import TerminalConfirmer

EXIT_COMMANDS = {"/quit", "/exit", "/q"}
RESET_COMMAND = "/reset"
LOGOUT_COMMAND = "/logout"


def log_out(settings: Settings) -> None:
    account = AccountManager(settings).logout()
    if account is None:
        print("No Claude account was connected.")
    elif account.config_dir is None:
        print(f"NOVA forgot {account.email} (your everyday Claude Code stays signed in). You will choose again next launch.")
    else:
        print(f"Logged out of {account.email}. You will choose an account again next launch.")


def run_cli() -> int:
    settings = Settings()
    if settings.location() is None and sys.stdin.isatty():
        print("First launch: NOVA needs your location (weather, local questions).")
        run_setup()
        settings = Settings()
    account = None
    try:
        if settings.provider == "claude_code":
            account = select_account(settings, interactive=sys.stdin.isatty())
            settings = use_claude_account(settings, account)
        agent = build_agent(settings, TerminalConfirmer())
        agent.session = ProviderSession()
    except (AccountSelectionError, ValueError, ProviderError, OSError, EOFError, KeyboardInterrupt) as error:
        print(f"Configuration error: {error}")
        return 1

    logout_hint = ", /logout to change account" if account is not None else ""
    print(f"NOVA online (provider: {settings.provider}). /reset to clear the conversation{logout_hint}, /quit to leave.")
    if account is not None:
        print(f"Claude account: {account.email}")
    location = settings.location()
    print(f"Location: {location.describe() if location else 'unknown (run `uv run nova setup`)'}")
    trusted = ", ".join(str(directory) for directory in settings.trusted_dirs) or "none"
    print(f"Trusted folders: {trusted}. Any other folder will need your approval.")
    while True:
        try:
            user_input = input("\nvous> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_input:
            continue
        if user_input in EXIT_COMMANDS:
            return 0
        if user_input == LOGOUT_COMMAND and account is not None:
            log_out(settings)
            return 0
        if user_input == RESET_COMMAND:
            agent.reset()
            print("Conversation cleared.")
            continue
        try:
            print(f"\nNOVA> {agent.ask(user_input)}")
        except (ProviderError, MaxTurnsExceededError) as error:
            print(f"\nNOVA [error]> {error}")
        except KeyboardInterrupt:
            print("\nInterrupted.")
