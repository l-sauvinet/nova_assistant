"""Models the user can pick in the chat, per provider, and where the choice is kept."""

from dataclasses import dataclass
from pathlib import Path

from dotenv import set_key

from nova.config import Settings


@dataclass(frozen=True)
class ModelChoice:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class ModelSetting:
    field: str
    variable: str


CHOICES: dict[str, list[ModelChoice]] = {
    "claude_code": [
        ModelChoice("haiku", "Haiku", "Rapide et économe"),
        ModelChoice("sonnet", "Sonnet", "Équilibré, pour la plupart des tâches"),
        ModelChoice("opus", "Opus", "Le plus capable, consomme davantage"),
        ModelChoice("fable", "Fable", "La toute dernière génération"),
    ],
    "anthropic": [
        ModelChoice("claude-haiku-4-5-20251001", "Haiku 4.5", "Rapide et économe"),
        ModelChoice("claude-sonnet-5-5", "Sonnet 5.5", "Équilibré, pour la plupart des tâches"),
        ModelChoice("claude-opus-5-5", "Opus 5.5", "Le plus capable, coûte davantage"),
        ModelChoice("claude-fable-5-1", "Fable 5.1", "La toute dernière génération"),
    ],
}

SETTINGS: dict[str, ModelSetting] = {
    "claude_code": ModelSetting("claude_code_model", "NOVA_CLAUDE_CODE_MODEL"),
    "anthropic": ModelSetting("anthropic_model", "NOVA_ANTHROPIC_MODEL"),
}


class UnknownModelError(ValueError):
    pass


def choices_for(settings: Settings) -> list[ModelChoice]:
    return CHOICES.get(settings.provider, [])


def current_model(settings: Settings) -> str | None:
    setting = SETTINGS.get(settings.provider)
    return getattr(settings, setting.field) if setting else None


def choose_model(settings: Settings, model: str, env_path: Path) -> Settings:
    """Returns the updated settings and keeps the choice in .env for the next launches."""
    setting = SETTINGS.get(settings.provider)
    if setting is None or model not in {choice.id for choice in choices_for(settings)}:
        raise UnknownModelError(f"Modèle inconnu pour ce fournisseur : {model}")
    env_path.touch(exist_ok=True)
    set_key(env_path, setting.variable, model)
    return settings.model_copy(update={setting.field: model})
