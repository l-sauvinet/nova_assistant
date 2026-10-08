import re
import time
import unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from nova.core.messages import Media
from nova.tools.base import Tool, ToolError, ToolOutput, object_schema
from nova.tools.file_access import FileAccessGuard

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"
IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_ARTIFACT_CHARS = 500_000


class ImageGenerator(Protocol):
    def generate(self, prompt: str, width: int, height: int) -> tuple[bytes, str]:
        """Returns the image bytes and their media type."""
        ...


class PollinationsImageGenerator:
    """Free image generation service, no API key. Busy at times: retries, then reports it clearly."""

    def __init__(
        self,
        model: str = "flux",
        http_client: httpx.Client | None = None,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.http_client = http_client or httpx.Client(timeout=120, follow_redirects=True)
        self.attempts = attempts
        self.sleep = sleep

    def generate(self, prompt: str, width: int, height: int) -> tuple[bytes, str]:
        params = {"width": width, "height": height, "model": self.model, "nologo": "true"}
        last_problem = ""
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.http_client.get(POLLINATIONS_URL + quote(prompt, safe=""), params=params)
            except httpx.HTTPError as error:
                last_problem = str(error)
            else:
                media_type = response.headers.get("content-type", "").split(";")[0]
                if response.status_code == 200 and media_type in IMAGE_EXTENSIONS:
                    return response.content, media_type
                last_problem = f"HTTP {response.status_code}"
                if response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < self.attempts:
                self.sleep(2 * attempt)
        raise ToolError(
            f"The free image service is unavailable right now ({last_problem}). "
            "Tell the user to try again in a moment."
        )


def slugify(text: str, max_length: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "nova"


class CreativeStudio:
    def __init__(self, access: FileAccessGuard, image_generator: ImageGenerator) -> None:
        self.access = access
        self.image_generator = image_generator

    def generate_image(self, prompt: str, width: int = 1024, height: int = 1024) -> ToolOutput:
        width, height = (max(256, min(int(size), 2048)) for size in (width, height))
        content, media_type = self.image_generator.generate(prompt, width, height)
        path = self._output_path("images", prompt, IMAGE_EXTENSIONS[media_type])
        path.write_bytes(content)
        return ToolOutput(
            text=f"Image generated and saved to {path}. It is already displayed to the user.",
            media=[Media(path=str(path), kind="image", title=prompt)],
        )

    def create_artifact(self, title: str, kind: str, content: str) -> ToolOutput:
        if kind not in {"svg", "html"}:
            raise ToolError("kind must be 'svg' or 'html'.")
        if len(content) > MAX_ARTIFACT_CHARS:
            raise ToolError(f"Artifact too large ({len(content)} characters).")
        if kind == "svg" and "<svg" not in content[:2000].lower():
            raise ToolError("An SVG artifact must contain an <svg> element.")
        path = self._output_path("artifacts", title, f".{kind}")
        path.write_text(content, encoding="utf-8")
        return ToolOutput(
            text=f"Artifact saved to {path}. It is already displayed to the user.",
            media=[Media(path=str(path), kind=kind, title=title)],
        )

    def _output_path(self, folder: str, label: str, extension: str) -> Path:
        directory = self.access.resolve_for_write(folder)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{datetime.now():%Y%m%d-%H%M%S}-{slugify(label)}{extension}"


def build_creative_tools(studio: CreativeStudio) -> list[Tool]:
    return [
        Tool(
            name="generate_image",
            description=(
                "Generate a picture (photo, illustration, painting, wallpaper...) with an image model and show it "
                "to the user. Write the prompt in English, detailed (subject, style, lighting, framing). "
                "The prompt is sent to an external image service."
            ),
            parameters=object_schema(
                {
                    "prompt": {"type": "string"},
                    "width": {"type": "integer", "description": "256 to 2048. Default 1024."},
                    "height": {"type": "integer", "description": "256 to 2048. Default 1024."},
                },
                required=["prompt"],
            ),
            run=studio.generate_image,
            effect="sends",
            action="générer une image (sa description part vers un service en ligne)",
        ),
        Tool(
            name="create_artifact",
            description=(
                "Create and show a visual artifact like the Claude app: 'svg' for logos, icons, diagrams, "
                "drawings; 'html' for a self-contained page (interactive demo, chart, mini-app, formatted document; "
                "inline CSS/JS, CDN scripts allowed). Saved in NOVA's workspace. Do not repeat the content in your answer."
            ),
            parameters=object_schema(
                {
                    "title": {"type": "string", "description": "Short title, also used for the file name."},
                    "kind": {"type": "string", "enum": ["svg", "html"]},
                    "content": {"type": "string", "description": "Full SVG or HTML document."},
                },
                required=["title", "kind", "content"],
            ),
            run=studio.create_artifact,
            effect="sends",
            action="créer une page interactive (elle peut contacter des sites)",
        ),
    ]
