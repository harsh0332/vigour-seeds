from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class MessageText(BaseModel):
    body: str

class MessageImage(BaseModel):
    id: str
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None

class MessageDocument(BaseModel):
    id: str
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
    filename: Optional[str] = None
    caption: Optional[str] = None

class ButtonReply(BaseModel):
    id: str
    title: str

class ListReply(BaseModel):
    id: str
    title: str
    description: Optional[str] = None

class MessageInteractive(BaseModel):
    type: str  # button_reply or list_reply
    button_reply: Optional[ButtonReply] = None
    list_reply: Optional[ListReply] = None

class MessageButton(BaseModel):
    payload: str
    text: str

class WebhookMessage(BaseModel):
    from_phone: str = Field(alias="from")
    id: str  # wamid
    timestamp: str
    type: str  # text, image, interactive, button, document, etc.
    text: Optional[MessageText] = None
    image: Optional[MessageImage] = None
    interactive: Optional[MessageInteractive] = None
    button: Optional[MessageButton] = None
    document: Optional[MessageDocument] = None

    class Config:
        populate_by_name = True

class WebhookContact(BaseModel):
    profile: Dict[str, str]  # {"name": "..."}
    wa_id: str

class WebhookValue(BaseModel):
    messaging_product: str
    metadata: Dict[str, str]
    contacts: Optional[List[WebhookContact]] = None
    messages: Optional[List[WebhookMessage]] = None

class WebhookChange(BaseModel):
    value: WebhookValue
    field: str

class WebhookEntry(BaseModel):
    id: str
    changes: List[WebhookChange]

class WebhookRequest(BaseModel):
    object: str
    entry: List[WebhookEntry]
