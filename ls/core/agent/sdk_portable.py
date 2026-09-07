"""Worker-only native message validation and portable serialization."""
from __future__ import annotations

import base64
import sys

from .checkpoint_store import MAX_MESSAGES
from .portable_content import project


def convert(finder, history: bytes, *, images: bool) -> bytes:
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('Portable conversion requires the isolated worker importer')
    finder.verify_origins()
    if not isinstance(history,bytes) or len(history)>MAX_MESSAGES or type(images) is not bool:
        raise ValueError('Invalid portable conversion input')
    from pydantic_ai.messages import ModelMessagesTypeAdapter,ModelRequest,UserPromptPart,BinaryContent
    ModelMessagesTypeAdapter.validate_json(history)
    text,attachments=project(history,images=images)
    content=[text,*[BinaryContent(base64.b64decode(item['data'],validate=True),media_type=item['media_type']) for item in attachments]]
    output=ModelMessagesTypeAdapter.dump_json([ModelRequest(parts=[UserPromptPart(content)])])
    if len(output)>MAX_MESSAGES: raise ValueError('Portable history exceeds checkpoint limit')
    finder.verify_origins()
    return output
