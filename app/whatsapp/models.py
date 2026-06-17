from pydantic import BaseModel
from typing import Optional, Dict, Any

class ParsedMessage(BaseModel):
    wamid: str
    from_phone: str
    profile_name: Optional[str] = None
    type: str  # text | image | audio | button_reply | list_reply | location | unsupported
    text: Optional[str] = None
    button_payload: Optional[str] = None
    list_id: Optional[str] = None
    media_id: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    timestamp: str
