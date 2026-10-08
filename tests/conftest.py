import socket
import subprocess
import sys

import pytest


class RealAICallBlockedError(RuntimeError):
    pass


def _block(*args, **kwargs):
    raise RealAICallBlockedError(
        "Tests must never reach a real AI: use tests/fakes.py (ScriptedProvider) or inject a fake runner/client."
    )


_real_connect = socket.socket.connect


def _block_connect(self, *args, **kwargs):
    # On Windows, asyncio opens a loopback self-pipe via socket.socketpair(), whose
    # pure-Python fallback (Lib/socket.py) goes through socket.connect(). Let that
    # internal plumbing through; still block every other connect (Anthropic, Ollama...).
    caller = sys._getframe(1)
    if caller.f_globals.get("__name__") == "socket" and caller.f_code.co_name == "_fallback_socketpair":
        return _real_connect(self, *args, **kwargs)
    return _block(self, *args, **kwargs)


@pytest.fixture(autouse=True)
def forbid_real_ai_calls(monkeypatch):
    """Blocks network access (Anthropic API, Ollama) and subprocesses (`claude -p`) in every test."""
    monkeypatch.setattr(socket.socket, "connect", _block_connect)
    monkeypatch.setattr(socket, "create_connection", _block)
    monkeypatch.setattr(subprocess.Popen, "__init__", _block)


@pytest.fixture(autouse=True)
def isolate_from_user_environment(monkeypatch, tmp_path_factory):
    """Tests ignore the developer's .env choices and never see a real API key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    nova_home = tmp_path_factory.mktemp("nova-home")
    monkeypatch.setenv("NOVA_CONVERSATIONS_DIR", str(nova_home / "conversations"))
    monkeypatch.setenv("NOVA_CLAUDE_CODE_ACCOUNTS_DIR", str(nova_home / "claude-accounts"))
    monkeypatch.setenv("NOVA_UPLOADS_DIR", str(nova_home / "uploads"))
    monkeypatch.setenv("NOVA_CLAUDE_CODE_SESSIONS_DIR", str(nova_home / "claude-sessions"))
    for variable in ("NOVA_PROVIDER", "NOVA_CLAUDE_CODE_MODEL", "NOVA_TRUSTED_DIRS", "NOVA_LOCATION_LATITUDE", "NOVA_LOCATION_LONGITUDE"):
        monkeypatch.delenv(variable, raising=False)
