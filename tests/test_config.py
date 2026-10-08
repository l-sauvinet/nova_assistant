from pathlib import Path

from nova.config import Settings


def test_allowed_dirs_are_comma_separated(monkeypatch):
    monkeypatch.setenv("NOVA_TRUSTED_DIRS", "/tmp/a, ~/b ,")
    settings = Settings(_env_file=None)
    assert settings.trusted_dirs == [Path("/tmp/a"), Path("~/b").expanduser()]


def test_defaults(monkeypatch):
    monkeypatch.delenv("NOVA_PROVIDER", raising=False)
    monkeypatch.setenv("NOVA_CLAUDE_CODE_MODEL", "")
    settings = Settings(_env_file=None)
    assert settings.provider == "claude_code"
    assert settings.claude_code_model is None
    assert settings.anthropic_model == "claude-haiku-4-5-20251001"
    assert settings.ollama_model == "qwen2.5:7b"
    assert settings.load_system_prompt().startswith("You are NOVA")
