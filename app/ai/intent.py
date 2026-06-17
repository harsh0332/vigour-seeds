import json
from typing import Dict, Any
from app.ai.provider import ai_provider
from app.core.logging import logger

INTENT_SYSTEM_PROMPT = """You are an intent classifier for Vigour Seeds' WhatsApp bot. The user is an Indian farmer or
agri-dealer writing in Hindi, Hinglish, or English. Classify their message into ONE intent.
Allowed intents:
  farmer_crop_problem   - crop issue: pest, disease, yellow leaves, low growth, low yield
  farmer_seed_inquiry   - wants seeds/variety info for current or next sowing
  distributor_new       - wants to become a Vigour distributor/dealer
  distributor_existing  - already a Vigour dealer asking about orders/stock/scheme/payment
  general_inquiry       - greeting, company info, contact, price, anything else
  spam                  - irrelevant/abuse
Also detect language: hindi | hinglish | english.
Return ONLY compact JSON: {"intent":"...","confidence":0.0-1.0,"language":"..."}.
No explanation. If unsure between farmer_crop_problem and farmer_seed_inquiry, pick
farmer_crop_problem."""

async def classify_intent(text: str) -> Dict[str, Any]:
    try:
        response_text = await ai_provider.complete(
            system=INTENT_SYSTEM_PROMPT,
            user=text,
            json_mode=True
        )
        return json.loads(response_text)
    except Exception as e:
        logger.error("Intent classification call failed", extra={"text": text, "error": str(e)})
        # Default safe fallback
        return {
            "intent": "general_inquiry",
            "confidence": 0.5,
            "language": "hinglish"
        }
