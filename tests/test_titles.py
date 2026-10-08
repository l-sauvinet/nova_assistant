from fakes import ScriptedProvider

from nova.core.messages import ProviderResponse
from nova.interfaces.titles import TITLE_PROMPT, clean_title, generate_title
from nova.providers.base import Provider, ProviderError


def test_title_is_asked_without_tools_from_the_first_exchange():
    provider = ScriptedProvider([ProviderResponse(text="Recette des crêpes")])
    assert generate_title(provider, "Comment faire des crêpes ?", "Mélange farine, œufs, lait…") == "Recette des crêpes"
    [messages] = provider.received_histories
    assert provider.received_tools == [[]]
    assert "crêpes" in messages[0].content and "Mélange farine" in messages[0].content
    assert "titre court" in TITLE_PROMPT


def test_model_decorations_are_removed():
    assert clean_title('"Météo à Chambéry."\n') == "Météo à Chambéry"
    assert clean_title("Titre : **Bilan PPS 2026**\nVoilà !") == "Bilan PPS 2026"
    assert clean_title("  \n ") is None


class BrokenProvider(Provider):
    def complete(self, system_prompt, messages, tools):
        raise ProviderError("quota atteint")


def test_a_failing_model_leaves_the_provisional_title():
    assert generate_title(BrokenProvider(), "Salut", "Bonjour !") is None
