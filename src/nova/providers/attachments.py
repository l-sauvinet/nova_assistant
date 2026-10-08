"""How attached files are shown to any model: pictures as images, documents as text, always with their path."""

import base64
from pathlib import Path

from nova.core.messages import Attachment, Message
from nova.security.exposure import OUTSIDE_NOTE, model_note
from nova.security.injection import scan

MAX_IMAGES_PER_REQUEST = 12


def describe_attachment(attachment: Attachment) -> str:
    header = f"[Pièce jointe : {attachment.name} — emplacement : {attachment.path}]"
    if attachment.kind == "image":
        body = "(image jointe, visible par toi)" if attachment.images else attachment.note
    elif attachment.images:
        body = f"(document scanné : ses pages sont jointes en images)\n{attachment.text}".strip()
    else:
        body = attachment.text or attachment.note
    if attachment.text:
        header += "\n" + (model_note(scan(attachment.text)) if attachment.warning else OUTSIDE_NOTE)
        # The scan is redone here (cheap) because the warning stored on the attachment is the user-facing text.
    return f"{header}\n{body}".strip()


def user_text(message: Message) -> str:
    parts = [describe_attachment(attachment) for attachment in message.attachments]
    if message.content:
        parts.append(message.content)
    return "\n\n".join(parts)


def image_paths(messages: list[Message]) -> list[str]:
    """Pictures to send with a request: the most recent ones first kept, oldest dropped past the limit."""
    paths = [path for message in messages if message.role == "user" for attachment in message.attachments for path in attachment.images]
    return paths[-MAX_IMAGES_PER_REQUEST:]


def image_base64(path: str) -> tuple[str, str]:
    data = Path(path).read_bytes()
    media_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return media_type, base64.b64encode(data).decode("ascii")
