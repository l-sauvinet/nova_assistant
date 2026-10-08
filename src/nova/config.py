from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from nova.device.location import Location

DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"

ProviderName = Literal["claude_code", "anthropic", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="NOVA_", extra="ignore", populate_by_name=True
    )

    provider: ProviderName = "claude_code"
    system_prompt_path: Path = DEFAULT_SYSTEM_PROMPT_PATH
    max_agent_turns: int = 10

    trusted_dirs: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    max_read_bytes: int = 200_000
    disk_scan_timeout_seconds: int = 60

    shell_enabled: bool = True
    shell_timeout_seconds: int = 120

    web_region: str = "fr-fr"

    image_model: str = "flux"

    server_port: int = 8765

    location_city: str = ""
    location_region: str = ""
    location_country: str = ""
    location_latitude: float | None = None
    location_longitude: float | None = None
    location_source: str = ""

    claude_code_cli: str = "claude"
    claude_code_model: str | None = None
    claude_code_timeout_seconds: int = 300
    claude_code_accounts_dir: Path = Path("~/.nova/claude-accounts")
    claude_code_sessions_dir: Path = Path("~/.nova/claude-sessions")
    conversations_dir: Path = Path("~/.nova/conversations")
    uploads_dir: Path = Path("~/.nova/uploads")
    claude_code_config_dir: Path | None = None

    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_max_tokens: int = 4096

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: int = 300

    @field_validator("trusted_dirs", mode="before")
    @classmethod
    def split_comma_separated_dirs(cls, value: object) -> object:
        if isinstance(value, str):
            return [Path(part.strip()).expanduser() for part in value.split(",") if part.strip()]
        return value

    @field_validator("claude_code_model", "claude_code_config_dir", mode="before")
    @classmethod
    def empty_means_unset(cls, value: object) -> object:
        return value or None

    @field_validator("location_latitude", "location_longitude", mode="before")
    @classmethod
    def empty_coordinate_means_unset(cls, value: object) -> object:
        return value if value != "" else None

    def location(self) -> Location | None:
        if self.location_latitude is None or self.location_longitude is None:
            return None
        return Location(
            city=self.location_city,
            region=self.location_region,
            country=self.location_country,
            latitude=self.location_latitude,
            longitude=self.location_longitude,
            source=self.location_source,
        )

    def load_system_prompt(self) -> str:
        return self.system_prompt_path.read_text(encoding="utf-8").strip()
