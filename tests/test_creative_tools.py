from pathlib import Path

import httpx
import pytest

from nova.core.messages import ToolCall
from nova.tools.base import ToolError
from nova.tools.creative import CreativeStudio, PollinationsImageGenerator, build_creative_tools, slugify
from nova.tools.file_access import FileAccessGuard
from nova.tools.registry import ToolRegistry
from fakes import ScriptedConfirmer

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def generator_answering(*responses: httpx.Response, calls: list | None = None) -> PollinationsImageGenerator:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return queue.pop(0)

    return PollinationsImageGenerator(http_client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda seconds: None)


def studio(tmp_path: Path, generator) -> CreativeStudio:
    return CreativeStudio(FileAccessGuard([tmp_path], ScriptedConfirmer()), generator)


def jpeg_response() -> httpx.Response:
    return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})


def test_generated_image_is_saved_and_returned_as_media(tmp_path: Path):
    calls = []
    output = studio(tmp_path, generator_answering(jpeg_response(), calls=calls)).generate_image("a chalet in Savoie")
    media = output.media[0]
    assert media.kind == "image" and media.title == "a chalet in Savoie"
    saved = Path(media.path)
    assert saved.parent == tmp_path.resolve() / "images" and saved.suffix == ".jpg"
    assert saved.read_bytes() == JPEG
    assert "a%20chalet%20in%20Savoie" in str(calls[0].url)
    assert calls[0].url.params["width"] == "1024" and calls[0].url.params["model"] == "flux"


def test_size_is_clamped(tmp_path: Path):
    calls = []
    studio(tmp_path, generator_answering(jpeg_response(), calls=calls)).generate_image("x", width=10, height=99999)
    assert calls[0].url.params["width"] == "256" and calls[0].url.params["height"] == "2048"


def test_busy_service_is_retried(tmp_path: Path):
    generator = generator_answering(httpx.Response(503), httpx.Response(503), jpeg_response())
    assert studio(tmp_path, generator).generate_image("x").media


def test_service_down_gives_a_clear_error(tmp_path: Path):
    generator = generator_answering(*[httpx.Response(503)] * 3)
    with pytest.raises(ToolError, match="unavailable right now"):
        studio(tmp_path, generator).generate_image("x")


def test_client_errors_are_not_retried(tmp_path: Path):
    calls = []
    with pytest.raises(ToolError):
        studio(tmp_path, generator_answering(httpx.Response(400), calls=calls)).generate_image("x")
    assert len(calls) == 1


def test_non_image_answer_is_an_error(tmp_path: Path):
    generator = generator_answering(*[httpx.Response(200, json={"error": "queue full"})] * 3)
    with pytest.raises(ToolError):
        studio(tmp_path, generator).generate_image("x")


def test_svg_artifact(tmp_path: Path):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle r="4"/></svg>'
    output = studio(tmp_path, None).create_artifact("Logo NOVA", "svg", svg)
    saved = Path(output.media[0].path)
    assert saved.parent == tmp_path.resolve() / "artifacts" and saved.name.endswith("-logo-nova.svg")
    assert saved.read_text() == svg and output.media[0].kind == "svg"


def test_html_artifact(tmp_path: Path):
    output = studio(tmp_path, None).create_artifact("Graphique", "html", "<html><body>ok</body></html>")
    assert Path(output.media[0].path).suffix == ".html"


def test_invalid_artifacts_are_refused(tmp_path: Path):
    creative = studio(tmp_path, None)
    with pytest.raises(ToolError):
        creative.create_artifact("x", "pdf", "...")
    with pytest.raises(ToolError, match="<svg>"):
        creative.create_artifact("x", "svg", "<div>not svg</div>")


def test_registry_passes_media_through(tmp_path: Path):
    registry = ToolRegistry(build_creative_tools(studio(tmp_path, generator_answering(jpeg_response()))), ScriptedConfirmer())
    result = registry.execute(ToolCall(id="1", name="generate_image", arguments={"prompt": "x"}))
    assert not result.is_error and result.media[0].kind == "image"
    assert "already displayed" in result.content


def test_slugify():
    assert slugify("Un chalet, en Savoie !") == "un-chalet-en-savoie"
    assert slugify("!!!") == "nova"
