import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.db.client import supabase_client
from app.db.repositories.conversations import conversations_repo
from app.whatsapp.models import ParsedMessage
from app.core.logging import logger

class WhatsAppParser:
    @staticmethod
    def _is_processed(wamid: str) -> bool:
        if not supabase_client:
            return False
        res = supabase_client.table("conversations").select("message_id").eq("message_id", wamid).execute()
        return len(res.data) > 0

    async def is_processed(self, wamid: str) -> bool:
        return await asyncio.to_thread(self._is_processed, wamid)

    async def parse_message(self, message: Dict[str, Any], contact: Optional[Dict[str, Any]] = None) -> Optional[ParsedMessage]:
        wamid = message.get("id")
        if not wamid:
            return None

        # Idempotency check
        if await self.is_processed(wamid):
            logger.info("Skipping duplicate message", extra={"wamid": wamid})
            return None

        from_phone = message.get("from")
        timestamp = message.get("timestamp", str(int(datetime.utcnow().timestamp())))
        profile_name = contact.get("profile", {}).get("name") if contact else None

        msg_type = message.get("type", "unsupported")
        
        parsed_type = "unsupported"
        text = None
        button_payload = None
        list_id = None
        media_id = None
        location = None

        if msg_type == "text":
            parsed_type = "text"
            text = message.get("text", {}).get("body")
        elif msg_type == "image":
            parsed_type = "image"
            media_id = message.get("image", {}).get("id")
            text = message.get("image", {}).get("caption")
        elif msg_type == "audio":
            parsed_type = "audio"
            media_id = message.get("audio", {}).get("id")
        elif msg_type == "location":
            parsed_type = "location"
            location = message.get("location")
        elif msg_type == "interactive":
            interactive = message.get("interactive", {})
            int_type = interactive.get("type")
            if int_type == "button_reply":
                parsed_type = "button_reply"
                button_reply = interactive.get("button_reply", {})
                button_payload = button_reply.get("id")
                text = button_reply.get("title")
            elif int_type == "list_reply":
                parsed_type = "list_reply"
                list_reply = interactive.get("list_reply", {})
                list_id = list_reply.get("id")
                text = list_reply.get("title")
        elif msg_type == "button":
            parsed_type = "button_reply"
            btn = message.get("button", {})
            button_payload = btn.get("payload")
            text = btn.get("text")

        parsed = ParsedMessage(
            wamid=wamid,
            from_phone=from_phone,
            profile_name=profile_name,
            type=parsed_type,
            text=text,
            button_payload=button_payload,
            list_id=list_id,
            media_id=media_id,
            location=location,
            timestamp=timestamp
        )

        # Log inbound message to conversation log database
        try:
            try:
                dt = datetime.utcfromtimestamp(int(timestamp))
            except Exception:
                dt = datetime.utcnow()
                
            await conversations_repo.log({
                "message_id": wamid,
                "lead_id": from_phone, # phone number as fallback lead_id
                "whatsapp_phone": from_phone,
                "direction": "inbound",
                "message_type": parsed_type,
                "message_text": text or f"Media ID: {media_id}" if media_id else (f"Location: {location}" if location else ""),
                "button_payload": button_payload or list_id,
                "handled_by": "bot",
                "created_at": dt.isoformat() + "Z"
            })
        except Exception as e:
            logger.error("Failed to log inbound message to database", extra={"wamid": wamid, "error": str(e)})

        return parsed

    async def parse_webhook_payload(self, payload: Dict[str, Any]) -> List[ParsedMessage]:
        parsed_messages = []
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                val = change.get("value", {})
                contacts = val.get("contacts", [])
                messages = val.get("messages", [])
                
                # Match contact by index or wa_id
                contact_map = {c.get("wa_id"): c for c in contacts}
                
                for msg in messages:
                    sender = msg.get("from")
                    contact = contact_map.get(sender)
                    parsed = await self.parse_message(msg, contact)
                    if parsed:
                        parsed_messages.append(parsed)
                        
        return parsed_messages

whatsapp_parser = WhatsAppParser()
