from enum import Enum
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.chat.schemas import ChatCreateResponse
from app.attachment.schemas import AttachmentSchma
from app.core.schemas import Pagination

class MessageRoleEnum(str, Enum):
    AI = "assistant"
    USER = "user"
    TOOL = "tool"

class MessageConfig(BaseModel):
    temperature: Optional[float] = None
    reasoning: Optional[bool] = None

class MessageContent(BaseModel):
    """
    A message content item should has an index, a type,
    and a content field whose key is the type.
    Ex:
    {
        "type": "text",
        "text": "text content"
    }
    """
    type: str

    model_config = ConfigDict(extra="allow")

class MessageSchema(BaseModel):
    message_id: str
    role: MessageRoleEnum
    content: dict[int, MessageContent]
    message_config: MessageConfig
    created_at: str
    version_count: int
    version_index: int
    attachments: list[AttachmentSchma]

class MessageAttachments(BaseModel):
    attachment_id: str

class InputUserMessage(BaseModel):
    message_config: Optional[MessageConfig] = MessageConfig()
    content: str
    attachments: list[MessageAttachments] = []

class ChatHistoryResp(ChatCreateResponse):
    messages: dict[str, MessageSchema]
    
class MsgHistoryRespPaginated(Pagination[MessageSchema]):
    pass

class MessageVersion(BaseModel):
    version_index: int
    content: list[dict[str, str]]
    created_at: str

class MessageVersionsResp(BaseModel):
    message_id: str
    versions: list[MessageVersion]
    total_versions: int

class MessageVersionUpdate(BaseModel):
    version_index: int

class UserMessageUpdate(BaseModel):
    message_config: Optional[MessageConfig] = MessageConfig()
    content: str

class MessageVersionUpdateOutput(BaseModel):
    active_message: MessageSchema
    branched_history: dict[str, MessageSchema]

class MessageMetadata(BaseModel):
    checkpoint_id: str
    message_id: uuid.UUID
    chat_id: uuid.UUID
    role: MessageRoleEnum
    message_config: MessageConfig
    parent_checkpoint_id: str