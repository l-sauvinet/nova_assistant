from nova.config import Settings
from nova.core.agent import Agent, AgentObserver
from nova.core.prompt import compose_system_prompt
from nova.device.location import location_context
from nova.device.machine import machine_context
from nova.interfaces.account import ClaudeAccount
from nova.providers.factory import create_provider
from nova.security.exposure import Exposure
from nova.tools.catalog import build_default_tools
from nova.tools.confirmation import Confirmer
from nova.tools.file_access import FileAccessGuard
from nova.tools.registry import ToolRegistry


def build_agent(settings: Settings, confirmer: Confirmer, observer: AgentObserver | None = None) -> Agent:
    exposure = Exposure()
    access = FileAccessGuard([*settings.trusted_dirs, settings.uploads_dir], confirmer, exposure)
    registry = ToolRegistry(build_default_tools(settings, access), confirmer=confirmer, exposure=exposure)
    return Agent(
        provider=create_provider(settings),
        executor=registry,
        system_prompt=build_system_prompt(settings),
        max_turns=settings.max_agent_turns,
        observer=observer,
    )


def build_system_prompt(settings: Settings) -> str:
    location = settings.location()
    return compose_system_prompt(
        f"{settings.load_system_prompt()}\n\n{machine_context()}", [location_context(location)] if location is not None else []
    )


def use_claude_account(settings: Settings, account: ClaudeAccount) -> Settings:
    return settings.model_copy(update={"claude_code_config_dir": account.config_dir})
