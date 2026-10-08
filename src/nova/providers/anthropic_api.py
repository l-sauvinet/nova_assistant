from typing import Any

import anthropic

from nova.core.messages import Message, ProviderResponse, ToolCall, ToolSpec
from nova.providers.attachments import image_base64, user_text
from nova.providers.base import Provider, ProviderError, ProviderSession


class AnthropicProvider(Provider):
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, client: Any = None) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic(api_key=api_key)

    def complete(
        self, system_prompt: str, messages: list[Message], tools: list[ToolSpec], session: ProviderSession | None = None
    ) -> ProviderResponse:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=[to_anthropic_message(message) for message in messages],
                tools=[
                    {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
                    for tool in tools
                ],
            )
        except anthropic.APIError as error:
            raise ProviderError(f"Anthropic API error: {error}") from error

        text_parts = [block.text for block in response.content if block.type == "text"]
        tool_calls = [
            ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
            for block in response.content
            if block.type == "tool_use"
        ]
        return ProviderResponse(text="\n".join(text_parts).strip(), tool_calls=tool_calls)


def to_anthropic_message(message: Message) -> dict[str, Any]:
    if message.role == "user":
        if not message.attachments:
            return {"role": "user", "content": message.content}
        blocks: list[dict[str, Any]] = []
        for path in (path for attachment in message.attachments for path in attachment.images):
            media_type, data = image_base64(path)
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
        blocks.append({"type": "text", "text": user_text(message)})
        return {"role": "user", "content": blocks}
    if message.role == "assistant":
        blocks: list[dict[str, Any]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        blocks.extend(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            for call in message.tool_calls
        )
        return {"role": "assistant", "content": blocks}
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": result.call_id,
                "content": result.content,
                "is_error": result.is_error,
            }
            for result in message.tool_results
        ],
    }
