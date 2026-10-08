import subprocess
from pathlib import Path

import anthropic
import pytest

from nova.config import Settings
from nova.core.messages import Message
from nova.providers.anthropic_api import AnthropicProvider
from nova.providers.base import ProviderError
from nova.providers.claude_code import ClaudeCodeProvider
from nova.providers.factory import create_provider
from conftest import RealAICallBlockedError


def test_default_provider_is_claude_code():
    assert isinstance(create_provider(Settings(_env_file=None)), ClaudeCodeProvider)


def test_api_key_alone_does_not_switch_to_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    assert isinstance(create_provider(Settings(_env_file=None)), ClaudeCodeProvider)


def test_anthropic_is_used_only_when_explicitly_chosen(monkeypatch):
    monkeypatch.setenv("NOVA_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    assert isinstance(create_provider(Settings(_env_file=None)), AnthropicProvider)


def test_anthropic_without_key_is_refused(monkeypatch):
    monkeypatch.setenv("NOVA_PROVIDER", "anthropic")
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        create_provider(Settings(_env_file=None))


def test_env_example_defaults_to_claude_code():
    settings = Settings(_env_file=Path(__file__).parent.parent / ".env.example")
    assert settings.provider == "claude_code"


def test_safety_net_blocks_real_claude_cli():
    provider = ClaudeCodeProvider()
    with pytest.raises(RealAICallBlockedError):
        provider.complete("sys", [Message(role="user", content="hi")], [])


def test_safety_net_blocks_real_anthropic_api():
    client = anthropic.Anthropic(api_key="sk-test-not-real", max_retries=0)
    provider = AnthropicProvider(api_key="unused", model="claude-haiku-4-5-20251001", client=client)
    with pytest.raises(ProviderError, match="Connection"):
        provider.complete("sys", [Message(role="user", content="hi")], [])
