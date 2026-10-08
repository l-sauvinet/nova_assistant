import json
import subprocess
from pathlib import Path

import pytest

from nova.config import Settings
from nova.interfaces.account import AccountManager, AccountSelectionError, account_folder_name
from nova.providers.claude_code import ClaudeCodeProvider

WORK = "bob@work.example"
PERSONAL = "alice@example.com"


class FakeLogins:
    """Pretends to be `claude auth status` for each login folder (None = everyday Claude Code login)."""

    def __init__(self, emails_by_folder: dict[Path | None, str]) -> None:
        self.emails_by_folder = emails_by_folder

    def provider(self, config_dir: Path | None) -> ClaudeCodeProvider:
        def run(command, **kwargs):
            email = self.emails_by_folder.get(config_dir)
            status = {"loggedIn": email is not None, "email": email}
            return subprocess.CompletedProcess(command, 0, json.dumps(status), "")

        return ClaudeCodeProvider(config_dir=config_dir, run_command=run)


def answers(*replies):
    queue = list(replies)
    return lambda question: queue.pop(0)


def make_manager(tmp_path: Path, logins: FakeLogins, *replies) -> AccountManager:
    settings = Settings(_env_file=None, claude_code_accounts_dir=tmp_path / "accounts")
    return AccountManager(settings, make_provider=logins.provider, ask=answers(*replies))


def personal_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "accounts" / account_folder_name(PERSONAL)
    folder.mkdir(parents=True)
    return folder


def test_lists_everyday_login_and_nova_accounts(tmp_path: Path):
    folder = personal_folder(tmp_path)
    manager = make_manager(tmp_path, FakeLogins({None: WORK, folder: PERSONAL}))
    assert [(account.email, account.config_dir) for account in manager.known_accounts()] == [
        (WORK, None),
        (PERSONAL, folder),
    ]


def test_logged_out_folders_are_not_listed(tmp_path: Path):
    personal_folder(tmp_path)
    assert [account.email for account in make_manager(tmp_path, FakeLogins({None: WORK})).known_accounts()] == [WORK]


def test_first_launch_asks_then_remembers(tmp_path: Path, capsys):
    folder = personal_folder(tmp_path)
    logins = FakeLogins({None: WORK, folder: PERSONAL})
    chosen = make_manager(tmp_path, logins, "2").current(interactive=True)
    assert chosen.email == PERSONAL and chosen.config_dir == folder
    assert "Which Claude account" in capsys.readouterr().out


def test_next_launches_do_not_ask_while_still_logged_in(tmp_path: Path, capsys):
    folder = personal_folder(tmp_path)
    logins = FakeLogins({None: WORK, folder: PERSONAL})
    make_manager(tmp_path, logins, "2").current(interactive=True)
    capsys.readouterr()

    silent_manager = make_manager(tmp_path, logins)
    assert silent_manager.current(interactive=True).email == PERSONAL
    assert silent_manager.current(interactive=False).email == PERSONAL
    assert "Which Claude account" not in capsys.readouterr().out


def test_asks_again_when_the_account_got_logged_out(tmp_path: Path):
    folder = personal_folder(tmp_path)
    logins = FakeLogins({None: WORK, folder: PERSONAL})
    make_manager(tmp_path, logins, "2").current(interactive=True)
    del logins.emails_by_folder[folder]
    assert make_manager(tmp_path, logins, "1").current(interactive=True).email == WORK


def test_logout_of_nova_account_really_logs_out_and_forgets(tmp_path: Path, monkeypatch):
    folder = personal_folder(tmp_path)
    logins = FakeLogins({None: WORK, folder: PERSONAL})
    make_manager(tmp_path, logins, "2").current(interactive=True)
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda command, env, **kwargs: commands.append((command, env["CLAUDE_CONFIG_DIR"])))

    assert make_manager(tmp_path, logins).logout().email == PERSONAL
    assert commands == [(["claude", "auth", "logout"], str(folder))]
    assert make_manager(tmp_path, logins).chosen_account() is None


def test_logout_of_everyday_login_only_forgets_it(tmp_path: Path, monkeypatch):
    logins = FakeLogins({None: WORK})
    make_manager(tmp_path, logins, "1").current(interactive=True)
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: commands.append(args))

    make_manager(tmp_path, logins).logout()
    assert commands == []
    assert make_manager(tmp_path, logins).chosen_account() is None


def test_invalid_choice_asks_again(tmp_path: Path):
    manager = make_manager(tmp_path, FakeLogins({None: WORK}), "9", "abc", "1")
    assert manager.choose().email == WORK


def test_add_account_signs_in_into_its_own_folder(tmp_path: Path, monkeypatch):
    folder = tmp_path / "accounts" / account_folder_name(PERSONAL)
    logins = FakeLogins({None: WORK})
    launched = []

    def fake_login(command, env):
        launched.append((command, env["CLAUDE_CONFIG_DIR"]))
        logins.emails_by_folder[folder] = PERSONAL

    monkeypatch.setattr(subprocess, "run", fake_login)
    chosen = make_manager(tmp_path, logins, "2", PERSONAL).choose()

    assert chosen.email == PERSONAL and chosen.config_dir == folder
    assert launched == [(["claude", "auth", "login", "--claudeai", "--email", PERSONAL], str(folder))]


def test_add_account_rejects_sign_in_with_another_email(tmp_path: Path, monkeypatch):
    folder = tmp_path / "accounts" / account_folder_name(PERSONAL)
    logins = FakeLogins({})
    monkeypatch.setattr(subprocess, "run", lambda command, env: logins.emails_by_folder.update({folder: WORK}))
    with pytest.raises(AccountSelectionError, match="not alice"):
        make_manager(tmp_path, logins, PERSONAL).add_account()


def test_add_account_fails_when_sign_in_is_abandoned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda command, env: None)
    with pytest.raises(AccountSelectionError, match="did not complete"):
        make_manager(tmp_path, FakeLogins({}), PERSONAL).add_account()


def test_non_interactive_launch_without_previous_choice_fails(tmp_path: Path):
    with pytest.raises(AccountSelectionError, match="uv run nova"):
        make_manager(tmp_path, FakeLogins({None: WORK})).current(interactive=False)


def test_cli_uses_chosen_folder_and_never_an_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    environment = ClaudeCodeProvider(config_dir=Path("~/.nova/x")).cli_environment()
    assert environment["CLAUDE_CONFIG_DIR"] == str(Path("~/.nova/x").expanduser())
    assert "ANTHROPIC_API_KEY" not in environment


def test_everyday_login_does_not_force_a_config_dir(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert "CLAUDE_CONFIG_DIR" not in ClaudeCodeProvider().cli_environment()


def test_folder_name_from_email():
    assert account_folder_name("Alice.Martin@Example.com") == "alice_martin_example_com"


@pytest.mark.parametrize("email", ["", "@@", "!!!", "pas-un-email", "--settings=x@evil.example"])
def test_invalid_emails_never_name_a_folder(email: str):
    with pytest.raises(AccountSelectionError, match="adresse e-mail valide"):
        account_folder_name(email)


def test_removing_an_invalid_email_keeps_every_account(tmp_path: Path):
    settings = Settings(_env_file=None, claude_code_accounts_dir=tmp_path / "accounts")
    kept = tmp_path / "accounts" / account_folder_name(PERSONAL)
    kept.mkdir(parents=True)
    with pytest.raises(AccountSelectionError):
        AccountManager(settings).remove("")
    assert kept.is_dir()
