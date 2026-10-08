import json
import platform
import re
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nova.config import Settings
from nova.providers.base import ProviderError
from nova.providers.claude_code import ClaudeCodeProvider

CHOSEN_ACCOUNT_FILE = "chosen_account.json"

Prompt = Callable[[str], str]
ProviderFactory = Callable[[Path | None], ClaudeCodeProvider]


class AccountSelectionError(Exception):
    pass


@dataclass(frozen=True)
class ClaudeAccount:
    email: str
    config_dir: Path | None
    """NOVA's own login folder for this account; None means the everyday Claude Code login (~/.claude)."""

    @property
    def label(self) -> str:
        return "your everyday Claude Code login" if self.config_dir is None else "NOVA account"


class AccountManager:
    """The user picks a Claude account once; NOVA keeps using it until the user logs out of it."""

    def __init__(self, settings: Settings, make_provider: ProviderFactory | None = None, ask: Prompt = input) -> None:
        self.settings = settings
        self.accounts_dir = settings.claude_code_accounts_dir.expanduser()
        self.make_provider = make_provider or (
            lambda config_dir: ClaudeCodeProvider(cli_path=settings.claude_code_cli, config_dir=config_dir)
        )
        self.ask = ask

    def current(self, interactive: bool) -> ClaudeAccount:
        chosen = self.chosen_account()
        if chosen is not None and self.is_still_logged_in(chosen):
            return chosen
        self.forget()
        if not interactive:
            raise AccountSelectionError("No Claude account connected. Launch `uv run nova` in a terminal to pick one.")
        chosen = self.choose()
        self.remember(chosen)
        return chosen

    def choose(self) -> ClaudeAccount:
        accounts = self.known_accounts()
        print("Which Claude account should NOVA use? (asked once, until you log out)")
        for index, account in enumerate(accounts, start=1):
            print(f"  {index}. {account.email}  ({account.label})")
        print(f"  {len(accounts) + 1}. Sign in with another account")
        while True:
            answer = self.ask("Choice [1]: ").strip() or "1"
            if answer.isdigit() and 1 <= int(answer) <= len(accounts):
                return accounts[int(answer) - 1]
            if answer == str(len(accounts) + 1):
                return self.add_account()
            print(f"Type a number between 1 and {len(accounts) + 1}.")

    def known_accounts(self) -> list[ClaudeAccount]:
        accounts: list[ClaudeAccount] = []
        folders = sorted(path for path in self.accounts_dir.iterdir() if path.is_dir()) if self.accounts_dir.is_dir() else []
        for config_dir in [None, *folders]:
            email = self.make_provider(config_dir).account_email()
            if email is not None and all(account.email.lower() != email.lower() for account in accounts):
                accounts.append(ClaudeAccount(email=email, config_dir=config_dir))
        return accounts

    def add_account(self) -> ClaudeAccount:
        email = self.ask("Email of the Claude account: ").strip()
        if not email:
            raise AccountSelectionError("No email given.")
        config_dir = self.accounts_dir / account_folder_name(email)
        config_dir.mkdir(parents=True, exist_ok=True)
        provider = self.make_provider(config_dir)
        print(f"Opening the Claude sign-in page for {email}...")
        try:
            subprocess.run(provider.login_command(email), env=provider.cli_environment())
        except OSError as error:
            raise AccountSelectionError(f"Could not start the Claude sign-in: {error}") from error
        logged_email = provider.account_email()
        if logged_email is None:
            raise AccountSelectionError(f"Sign-in for {email} did not complete.")
        if logged_email.lower() != email.lower():
            raise AccountSelectionError(f"You signed in as {logged_email}, not {email}. Try again.")
        return ClaudeAccount(email=logged_email, config_dir=config_dir)

    def logout(self) -> ClaudeAccount | None:
        """Signs NOVA out: its own account folders are really logged out; the everyday Claude Code
        login is only forgotten by NOVA, so the user's regular Claude Code stays signed in."""
        chosen = self.chosen_account()
        if chosen is not None and chosen.config_dir is not None:
            provider = self.make_provider(chosen.config_dir)
            subprocess.run(provider.logout_command(), env=provider.cli_environment(), capture_output=True)
        self.forget()
        return chosen

    def remove(self, email: str) -> None:
        """Really signs NOVA's own login for `email` out and deletes its folder. The everyday Claude Code
        login is never touched: removing it would sign the user out of their regular Claude Code."""
        config_dir = self.accounts_dir / account_folder_name(email)
        if not config_dir.is_dir():
            raise AccountSelectionError(f"{email} n'est pas un compte ajouté dans NOVA.")
        provider = self.make_provider(config_dir)
        try:
            subprocess.run(provider.logout_command(), env=provider.cli_environment(), capture_output=True)
        except OSError as error:
            raise AccountSelectionError(f"Impossible de déconnecter {email} : {error}") from error
        shutil.rmtree(config_dir, ignore_errors=True)
        chosen = self.chosen_account()
        if chosen is not None and chosen.config_dir == config_dir:
            self.forget()

    def chosen_account(self) -> ClaudeAccount | None:
        try:
            data = json.loads((self.accounts_dir / CHOSEN_ACCOUNT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("email"):
            return None
        config_dir = data.get("config_dir")
        return ClaudeAccount(email=data["email"], config_dir=Path(config_dir) if config_dir else None)

    def remember(self, account: ClaudeAccount) -> None:
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        data = {"email": account.email, "config_dir": str(account.config_dir) if account.config_dir else None}
        (self.accounts_dir / CHOSEN_ACCOUNT_FILE).write_text(json.dumps(data), encoding="utf-8")

    def forget(self) -> None:
        (self.accounts_dir / CHOSEN_ACCOUNT_FILE).unlink(missing_ok=True)

    def is_still_logged_in(self, account: ClaudeAccount) -> bool:
        email = self.make_provider(account.config_dir).account_email()
        return email is not None and email.lower() == account.email.lower()


EMAIL_PATTERN = re.compile(r"(?!-)[^@\s]+@[^@\s]+\.[^@\s]+")


def account_folder_name(email: str) -> str:
    """Folder of an added account under the accounts directory. The email is validated first: an empty name
    would point at the accounts directory itself (removing it would delete every account), and an email
    starting with "-" would be read as an option by the `claude` CLI."""
    if not EMAIL_PATTERN.fullmatch(email):
        raise AccountSelectionError(f"« {email} » n'est pas une adresse e-mail valide.")
    return re.sub(r"[^a-z0-9]+", "_", email.lower()).strip("_")


def select_account(settings: Settings, interactive: bool, manager: AccountManager | None = None) -> ClaudeAccount:
    manager = manager or AccountManager(settings)
    try:
        return manager.current(interactive)
    except ProviderError as error:
        raise AccountSelectionError(str(error)) from error


LOGIN_URL_PATTERN = re.compile(r"https://[^\s\x07\x1b\]]*oauth/authorize[^\s\x07\x1b]*")


class LoginSession:
    """Non-interactive Claude sign-in for the desktop app.

    The CLI would open the sign-in page itself, in the default browser, which may already be signed in to
    another Claude account. NOVA catches that page's link instead (through BROWSER) so the user can open it
    wherever they want, e.g. a private window; the page completes the sign-in by itself. The link printed by
    the CLI is kept as a fallback: that page shows a code to paste.
    """

    def __init__(self, manager: AccountManager, email: str, popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
        self.manager = manager
        self.email = email
        self.config_dir = manager.accounts_dir / account_folder_name(email)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.provider = manager.make_provider(self.config_dir)
        self.output = ""
        self._url_found = threading.Event()
        self.browser_link_file = self.config_dir / ".nova-sign-in-link"
        self.browser_link_file.unlink(missing_ok=True)
        environment = self.provider.cli_environment()
        if platform.system() != "Windows":
            environment["BROWSER"] = str(self._write_link_catcher())
        self.process = popen(
            self.provider.login_command(email),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        threading.Thread(target=self._read_output, daemon=True).start()

    def _write_link_catcher(self) -> Path:
        script = self.config_dir / ".nova-browser.sh"
        script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$1\" > {shlex.quote(str(self.browser_link_file))}\n", encoding="utf-8")
        script.chmod(0o700)
        return script

    def sign_in_url(self, timeout_seconds: float = 20) -> str:
        """The link to paste a code from (always printed by the CLI)."""
        self._url_found.wait(timeout_seconds)
        match = LOGIN_URL_PATTERN.search(self.output)
        if match is None:
            self.cancel()
            raise AccountSelectionError(f"La connexion Claude n'a pas démarré : {self.output.strip()[-300:]}")
        return match.group(0)

    def browser_link(self, timeout_seconds: float = 5) -> str | None:
        """The link that completes the sign-in by itself, or None if the CLI did not hand it over."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                link = self.browser_link_file.read_text(encoding="utf-8").strip()
            except OSError:
                link = ""
            if link.startswith("https://"):
                return link
            time.sleep(0.1)
        return None

    def finished(self) -> ClaudeAccount | None:
        """The account once `claude auth login` has ended on its own: the page Claude Code opens itself
        completes the sign-in in the browser, without any code to paste. None while it is still waiting."""
        if self.process.poll() is None:
            return None
        return self._signed_in_account()

    def submit_code(self, code: str, timeout_seconds: float = 60) -> ClaudeAccount:
        if self.process.poll() is not None:
            return self._signed_in_account()
        try:
            self.process.stdin.write(code.strip() + "\n")
            self.process.stdin.flush()
            self.process.wait(timeout=timeout_seconds)
        except (OSError, subprocess.TimeoutExpired) as error:
            if self.process.poll() is not None:
                return self._signed_in_account()
            self.cancel()
            raise AccountSelectionError(f"La connexion Claude ne s'est pas terminée : {error}") from error
        return self._signed_in_account()

    def _signed_in_account(self) -> ClaudeAccount:
        logged_email = self.provider.account_email()
        if logged_email is None:
            raise AccountSelectionError("Connexion refusée : le code est faux ou a expiré. Réessaie.")
        if logged_email.lower() != self.email.lower():
            subprocess.run(self.provider.logout_command(), env=self.provider.cli_environment(), capture_output=True)
            raise AccountSelectionError(
                f"La page Claude était connectée à {logged_email}, pas à {self.email}. "
                f"Sur claude.ai, déconnecte-toi ou passe sur {self.email}, puis recommence."
            )
        account = ClaudeAccount(email=logged_email, config_dir=self.config_dir)
        self.manager.remember(account)
        return account

    def cancel(self) -> None:
        if self.process.poll() is None:
            self.process.kill()

    def _read_output(self) -> None:
        while True:
            chunk = self.process.stdout.read(1)
            if not chunk:
                self._url_found.set()
                return
            self.output += chunk
            if LOGIN_URL_PATTERN.search(self.output) and chunk in {"\n", " ", "\x07"}:
                self._url_found.set()
