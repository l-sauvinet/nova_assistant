from nova.config import Settings
from nova.providers.base import Provider, ProviderError


def create_provider(settings: Settings) -> Provider:
    if settings.provider == "claude_code":
        from nova.providers.claude_code import ClaudeCodeProvider

        return ClaudeCodeProvider(
            cli_path=settings.claude_code_cli,
            model=settings.claude_code_model,
            timeout_seconds=settings.claude_code_timeout_seconds,
            config_dir=settings.claude_code_config_dir,
            sessions_dir=settings.claude_code_sessions_dir,
        )
    if settings.provider == "anthropic":
        from nova.providers.anthropic_api import AnthropicProvider

        if settings.anthropic_api_key is None:
            raise ProviderError("ANTHROPIC_API_KEY is missing from .env (required by NOVA_PROVIDER=anthropic).")
        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
        )
    if settings.provider == "ollama":
        from nova.providers.ollama import OllamaProvider

        return OllamaProvider(
            host=settings.ollama_host,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
    raise ProviderError(f"Unknown provider: {settings.provider}")
