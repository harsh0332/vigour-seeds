import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.db.client import supabase_client
from app.whatsapp.client import whatsapp_client
from app.core.logging import logger

def _is_within_window(phone: str) -> bool:
    if not supabase_client:
        return False
        
    try:
        # Fetch the last inbound message from this phone number
        res = supabase_client.table("conversations") \
            .select("created_at") \
            .eq("whatsapp_phone", phone) \
            .eq("direction", "inbound") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
            
        if not res.data:
            return False
            
        # Parse timestamp
        created_at_str = res.data[0]["created_at"]
        # Standardize 'Z' to '+00:00' for fromisoformat in Python 3.10
        if created_at_str.endswith("Z"):
            created_at_str = created_at_str[:-1] + "+00:00"
            
        last_inbound_time = datetime.fromisoformat(created_at_str)
        now = datetime.now(timezone.utc)
        
        diff = now - last_inbound_time
        return diff.total_seconds() <= 86400  # 24 hours
    except Exception as e:
        logger.error("Failed to check 24-hour window from conversations log", extra={"phone": phone, "error": str(e)})
        return False

async def is_within_window(phone: str) -> bool:
    """Check if the last inbound message was received within the last 24 hours."""
    return await asyncio.to_thread(_is_within_window, phone)

async def send_followup(phone: str, template_id: str, fallback_text: str, parameters: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Send a message, complying with Meta's 24-hour window:
    - Inside window: Send free-text fallback_text
    - Outside window: Send template message
    """
    in_window = await is_within_window(phone)
    res = None
    if in_window:
        logger.info("Inside 24-hour window, sending text follow-up", extra={"phone": phone})
        res = await whatsapp_client.send_text(phone, fallback_text)
    else:
        logger.info("Outside 24-hour window, sending template follow-up", extra={"phone": phone, "template": template_id})
        # Format template components
        components = []
        if parameters:
            param_list = []
            for p in parameters:
                param_list.append({
                    "type": "text",
                    "text": str(p)
                })
            components.append({
                "type": "body",
                "parameters": param_list
            })
        res = await whatsapp_client.send_template(phone, template_id, components)
        
    try:
        from app.services.metrics import metrics_service
        metrics_service.increment_followups_sent()
    except Exception:
        pass
        
    return res
