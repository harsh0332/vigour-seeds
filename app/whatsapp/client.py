import httpx
import uuid
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from app.core.config import settings
from app.core.logging import logger
from app.db.repositories.conversations import conversations_repo
from app.core.errors import (
    MetaApiException,
    MetaRateLimitException,
    MetaServerException,
    MetaAuthException,
    retry_with_backoff
)
from app.services.metrics import metrics_service

class WhatsAppClient:
    def __init__(self):
        self.access_token = settings.META_WHATSAPP_TOKEN
        self.phone_number_id = settings.META_PHONE_NUMBER_ID
        self.base_url = f"https://graph.facebook.com/v21.0/{self.phone_number_id}"
        self.media_base_url = "https://graph.facebook.com/v21.0"
        self.timeout = 15.0  # seconds
        self.max_retries = 3

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    async def _execute_post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        """A single post attempt mapping HTTP error status codes to custom exceptions."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                # Check status codes and raise specific custom exception classes
                if response.status_code == 429:
                    raise MetaRateLimitException(f"Meta API Rate Limit hit (429): {response.text}")
                elif response.status_code in [401, 403]:
                    raise MetaAuthException(f"Meta API Authorization / Token Expired (401/403): {response.text}")
                elif response.status_code >= 500:
                    raise MetaServerException(f"Meta API Server Error ({response.status_code}): {response.text}")
                
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code == 429:
                raise MetaRateLimitException(f"Meta API Rate Limit hit (429): {e.response.text}")
            elif status_code in [401, 403]:
                raise MetaAuthException(f"Meta API Authorization / Token Expired (401/403): {e.response.text}")
            elif status_code >= 500:
                raise MetaServerException(f"Meta API Server Error ({status_code}): {e.response.text}")
            raise MetaApiException(f"Meta API HTTP error: {e}")
        except httpx.RequestError as e:
            raise MetaApiException(f"Meta API connection or network failure: {e}")

    async def _post_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/messages"
        headers = self._get_headers()
        return await retry_with_backoff(self._execute_post, url, payload, headers, attempts=self.max_retries)

    async def send_text(self, to: str, body: str) -> Dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": body}
        }
        logger.info("Sending text message", extra={"to": to, "length": len(body)})
        res = await self._post_request(payload)
        
        # Increment outbound messages metric
        metrics_service.increment_msgs_out()
        
        # Log outbound message
        msg_id = res.get("messages", [{}])[0].get("id") if res else None
        if not msg_id:
            msg_id = f"out_{uuid.uuid4()}"
            
        await conversations_repo.log({
            "message_id": msg_id,
            "lead_id": to,
            "whatsapp_phone": to,
            "direction": "outbound",
            "message_type": "text",
            "message_text": body,
            "handled_by": "bot"
        })
        return res

    async def send_buttons(self, to: str, body: str, buttons: List[Dict[str, str]]) -> Dict[str, Any]:
        # Max 3 buttons
        formatted_buttons = []
        for btn in buttons[:3]:
            formatted_buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["title"]
                }
            })
            
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": formatted_buttons}
            }
        }
        logger.info("Sending interactive buttons", extra={"to": to, "buttons_count": len(formatted_buttons)})
        res = await self._post_request(payload)
        
        # Increment outbound messages metric
        metrics_service.increment_msgs_out()
        
        msg_id = res.get("messages", [{}])[0].get("id") if res else None
        if not msg_id:
            msg_id = f"out_{uuid.uuid4()}"
            
        btn_ids = [btn["id"] for btn in buttons[:3]]
        await conversations_repo.log({
            "message_id": msg_id,
            "lead_id": to,
            "whatsapp_phone": to,
            "direction": "outbound",
            "message_type": "button_reply",
            "message_text": body,
            "button_payload": ", ".join(btn_ids),
            "handled_by": "bot"
        })
        return res

    async def send_list(self, to: str, header: Optional[str], body: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Formats list sections
        formatted_sections = []
        for sec in sections:
            formatted_rows = []
            for row in sec.get("rows", []):
                formatted_rows.append({
                    "id": row["id"],
                    "title": row["title"][:24],
                    "description": row.get("description", "")[:72]
                })
            formatted_sections.append({
                "title": sec.get("title", "")[:24],
                "rows": formatted_rows
            })
            
        button_label = "Select"
        if sections and sections[0].get("button_label"):
            button_label = sections[0]["button_label"]
            
        action = {
            "button": button_label[:20],
            "sections": formatted_sections
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": action
            }
        }
        if header:
            payload["interactive"]["header"] = {
                "type": "text",
                "text": header[:60]
            }
            
        logger.info("Sending interactive list", extra={"to": to, "sections_count": len(formatted_sections)})
        res = await self._post_request(payload)
        
        # Increment outbound messages metric
        metrics_service.increment_msgs_out()
        
        msg_id = res.get("messages", [{}])[0].get("id") if res else None
        if not msg_id:
            msg_id = f"out_{uuid.uuid4()}"
            
        await conversations_repo.log({
            "message_id": msg_id,
            "lead_id": to,
            "whatsapp_phone": to,
            "direction": "outbound",
            "message_type": "list_reply",
            "message_text": body,
            "handled_by": "bot"
        })
        return res

    async def send_template(self, to: str, template_name: str, components: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "hi"},
                "components": components
            }
        }
        logger.info("Sending WhatsApp template", extra={"to": to, "template": template_name})
        res = await self._post_request(payload)
        
        # Increment outbound messages metric
        metrics_service.increment_msgs_out()
        
        msg_id = res.get("messages", [{}])[0].get("id") if res else None
        if not msg_id:
            msg_id = f"out_{uuid.uuid4()}"
            
        await conversations_repo.log({
            "message_id": msg_id,
            "lead_id": to,
            "whatsapp_phone": to,
            "direction": "outbound",
            "message_type": "text",
            "message_text": f"Template: {template_name}",
            "template_id": template_name,
            "handled_by": "bot"
        })
        return res

    async def _execute_media_download(self, url: str, headers: Dict[str, str]) -> Tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.get(url, headers=headers)
            res.raise_for_status()
            data = res.json()
            media_url = data.get("url", "")
            mime_type = data.get("mime_type", "application/octet-stream")
            
            if not media_url:
                logger.error("Media URL missing from Meta response", extra={"url": url})
                return b"", mime_type
            
            res_binary = await client.get(media_url, headers=headers)
            res_binary.raise_for_status()
            return res_binary.content, mime_type

    async def download_media(self, media_id: str) -> Tuple[bytes, str]:
        url = f"{self.media_base_url}/{media_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        try:
            return await retry_with_backoff(self._execute_media_download, url, headers, attempts=self.max_retries)
        except Exception as e:
            logger.error("Failed downloading media from Meta after retries", extra={"media_id": media_id, "error": str(e)})
            return b"", "application/octet-stream"

    async def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        """Marks an inbound message as read (displays the blue checkmarks ✅ to the user)."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id
        }
        logger.info("Marking message as read", extra={"message_id": message_id})
        return await self._post_request(payload)

whatsapp_client = WhatsAppClient()
