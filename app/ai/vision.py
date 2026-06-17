import json
from typing import Optional, Dict, Any
from app.ai.provider import ai_provider
from app.core.logging import logger

VISION_SYSTEM_PROMPT = """You are an agronomy assistant analyzing a photo of an Indian field/vegetable crop for Vigour Seeds. Identify the MOST LIKELY single problem from this taxonomy:
pest_attack, leaf_eating_caterpillar, sucking_pest, yellow_leaves, nutrient_deficiency, fungal_disease, bacterial_disease, viral_disease (e.g. YMV/leaf curl), low_growth, water_stress, healthy, unclear.
Consider the crop context provided by the user. Output ONLY compact JSON:
{
  "problem_category": "<taxonomy value>",
  "secondary_possibilities": ["..."],
  "severity": "low|medium|high|unknown",
  "confidence": 0.0-1.0,
  "visible_symptoms_hindi": "<1 line, simple Hindi, what you see>",
  "needs_human": true|false
}
Rules: If the image is blurry, not a crop, or you are unsure, set problem_category="unclear", confidence below 0.5, needs_human=true. NEVER prescribe a chemical, dosage, or product — diagnosis only. Do not invent a disease you cannot see."""

class VisionService:
    async def diagnose(self, image_bytes: bytes, mime_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        user_msg = (
            f"Crop: {context.get('crop_name_hi', 'Unknown')} / {context.get('crop_name_en', 'Unknown')}\n"
            f"Stage: {context.get('crop_stage', 'Unknown')}\n"
            f"District: {context.get('district', 'Unknown')}\n"
            f"Irrigation: {context.get('irrigation', 'Unknown')}\n"
            f"User Complaint: {context.get('user_complaint', 'None')}"
        )
        
        try:
            response_text = await ai_provider.complete(
                system=VISION_SYSTEM_PROMPT,
                user=user_msg,
                images=[{"bytes": image_bytes, "mime_type": mime_type}],
                json_mode=True
            )
            return json.loads(response_text)
        except Exception as e:
            logger.error("Vision diagnosis call failed", extra={"error": str(e), "context": context})
            return {
                "problem_category": "unclear",
                "secondary_possibilities": [],
                "severity": "unknown",
                "confidence": 0.0,
                "visible_symptoms_hindi": "फोटो का विश्लेषण नहीं हो पाया",
                "needs_human": True
            }

vision_service = VisionService()
