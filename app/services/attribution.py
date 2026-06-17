from typing import Optional, Dict, Any
from app.services.session import session_service
from app.core.logging import logger

def extract_referral_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extracts ad referral object from Meta's webhook JSON payload if present.
    """
    try:
        entries = payload.get("entry", [])
        if not entries:
            return None
        changes = entries[0].get("changes", [])
        if not changes:
            return None
        val = changes[0].get("value", {})
        messages = val.get("messages", [])
        if not messages:
            return None
        
        # Referral object is nested inside the first message
        msg = messages[0]
        referral = msg.get("referral")
        if referral:
            return {
                "source_id": referral.get("source_id"),
                "headline": referral.get("headline"),
                "ctwa_clid": referral.get("ctwa_clid"),
                "source_type": referral.get("source_type"),
                "source_url": referral.get("source_url")
            }
    except Exception as e:
        logger.error("Failed to extract ad referral from payload", extra={"error": str(e)})
    return None

async def attribute_message_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Checks the webhook payload for CTWA referral. If found, initializes or patches
    the user's session state with ad-attribution parameters.
    """
    referral = extract_referral_from_payload(payload)
    if not referral:
        return None
        
    try:
        phone = payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
        
        # Determine utm_campaign from the headline, fallback to ad_id
        utm_campaign = referral.get("headline") or referral.get("source_id") or "ctwa_ad"
        
        attribution_patch = {
            "source_channel": "whatsapp_ad",
            "utm_campaign": utm_campaign,
            "ctwa_clid": referral.get("ctwa_clid"),
            "referral_source_id": referral.get("source_id")
        }
        
        # Load or create session for the user and save the attribution
        session = await session_service.get_or_create(phone)
        await session_service.patch_collected(phone, attribution_patch)
        
        logger.info(
            "Ad attribution captured successfully",
            extra={
                "phone": phone,
                "source_channel": "whatsapp_ad",
                "utm_campaign": utm_campaign,
                "ctwa_clid": referral.get("ctwa_clid")
            }
        )
        return attribution_patch
    except Exception as e:
        logger.error("Failed to apply ad attribution to session", extra={"error": str(e)})
        
    return None
