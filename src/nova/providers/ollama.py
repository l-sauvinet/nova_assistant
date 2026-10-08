import uuid
from typing import Any

import httpx

from nova.core.messages import Message, ProviderResponse, ToolCall, ToolSpec
from nova.providers.attachments import image_base64, user_text
from nova.providers.base import Provider, ProviderError, ProviderSession


class OllamaProvider(Provider):
    def __init__(self, host: str, model: str, timeout_seconds: int = 300, client: httpx.Client | None = None) -> None:
        self.model = model
        self.client = client or httpx.Client(base_url=host, timeout=timeout_seconds)

    def complete(
        self, system_prompt: str, messages: list[Message], tools: list[ToolSpec], session: ProviderSession | None = None
    ) -> ProviderResponse:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": system_prompt}]
            + [ollama_message for message in messages for ollama_message in to_ollama_messages(message)],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ],
        }
        try:
            response = self.client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ProviderError(f"Ollama error ({self.model}): {error}") from error

        reply = response.json().get("message", {})
        tool_calls = [
            ToolCall(
                id=str(uuid.uuid4()),
                name=call["function"]["name"],
                arguments=dict(call["function"].get("arguments") or {}),
            )
            for call in reply.get("tool_calls") or []
        ]
        return ProviderResponse(text=(reply.get("content") or "").strip(), tool_calls=tool_calls)


def to_ollama_messages(message: Message) -> list[dict[str, Any]]:
    if message.role == "user":
        ollama_message: dict[str, Any] = {"role": "user", "content": user_text(message)}
        images = [image_base64(path)[1] for attachment in message.attachments for path in attachment.images]
        if images:
            ollama_message["images"] = images
        return [ollama_message]
    if message.role == "assistant":
        ollama_message: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            ollama_message["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}} for call in message.tool_calls
            ]
        return [ollama_message]
    return [
        {"role": "tool", "tool_name": result.name, "content": result.content} for result in message.tool_results
    ]
