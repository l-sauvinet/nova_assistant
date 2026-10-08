"""Short conversation titles written by the model after the first exchange, like the Claude app sidebar."""

from nova.core.messages import Message
from nova.providers.base import Provider, ProviderError

EXCERPT_LENGTH = 1500
TITLE_PROMPT = (
    "Tu nommes des conversations. Donne un titre court (2 à 6 mots) qui résume le sujet de la conversation, "
    "dans la langue de l'utilisateur. Réponds uniquement par le titre : pas de guillemets, pas d'emoji, "
    "pas de point final."
)


def clean_title(raw: str) -> str | None:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    title = lines[0].removeprefix("Titre :").removeprefix("Titre:").strip()
    title = title.strip("\"'«»“”*# ").rstrip(".").strip()
    return title or None


def generate_title(provider: Provider, first_message: str, answer: str) -> str | None:
    """Returns None when the model fails: the conversation keeps its provisional title."""
    exchange = f"Message de l'utilisateur :\n{first_message[:EXCERPT_LENGTH]}\n\nRéponse de l'assistant :\n{answer[:EXCERPT_LENGTH]}"
    try:
        response = provider.complete(TITLE_PROMPT, [Message(role="user", content=exchange)], [])
    except (ProviderError, OSError, ValueError):
        return None
    return clean_title(response.text)
