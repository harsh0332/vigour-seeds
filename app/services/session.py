import json
from typing import Optional, Dict, Any
from app.db.repositories.sessions import sessions_repo
from app.models.db_models import SessionRow
from app.core.logging import logger
from app.ai.provider import ai_provider

class SessionService:
    async def get_or_create(self, phone: str) -> SessionRow:
        sess = await sessions_repo.get(phone)
        if not sess:
            sess = await sessions_repo.upsert(phone, {
                "current_step": "start",
                "collected_json": {}
            })
        return sess

    async def set_flow(self, phone: str, flow: Optional[str]) -> SessionRow:
        return await sessions_repo.upsert(phone, {"current_flow": flow})

    async def set_step(self, phone: str, step: str) -> SessionRow:
        return await sessions_repo.upsert(phone, {"current_step": step})

    async def patch_collected(self, phone: str, patch_dict: Dict[str, Any]) -> SessionRow:
        return await sessions_repo.upsert(phone, {"collected_json": patch_dict})

    async def get_collected(self, phone: str) -> Dict[str, Any]:
        sess = await self.get_or_create(phone)
        return sess.collected_json or {}

    async def reset(self, phone: str) -> bool:
        return await sessions_repo.clear(phone)

    async def detect_language(self, text: str) -> str:
        if not text:
            return "hinglish"
        
        cleaned = text.lower().strip()
        
        # 1. Unicode Devanagari range check (Hindi)
        if any(ord(char) >= 0x0900 and ord(char) <= 0x097F for char in cleaned):
            return "hindi"

        # 2. Heuristic word matching
        words = set(cleaned.split())
        english_keywords = {"hello", "hi", "help", "order", "stock", "dealer", "distributor", "price", "seed", "problem", "info", "general", "inquiry"}
        hinglish_keywords = {"namaste", "beej", "kheti", "kisan", "keeda", "samasya", "bimar", "pila", "paani", "niche", "chune", "karna", "hai", "tha", "raha", "mirch", "bhindi"}
        
        if words.intersection(english_keywords):
            return "english"
        if words.intersection(hinglish_keywords):
            return "hinglish"

        # 3. AI Fallback
        try:
            prompt = (
                "Identify the language of this message from an Indian farmer/dealer. "
                "Choose exactly one from: hindi, hinglish, english. "
                "Return ONLY the language name lowercase. "
                "Message: '{text}'"
            )
            res = await ai_provider.complete(
                system="You are a language detector. Output ONLY the language.",
                user=prompt
            )
            detected = res.strip().lower()
            if detected in ["hindi", "hinglish", "english"]:
                return detected
        except Exception as e:
            logger.error("AI language detection failed", extra={"error": str(e)})

        return "hinglish"

session_service = SessionService()
