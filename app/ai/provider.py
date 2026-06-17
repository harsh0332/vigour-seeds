import os
import json
import base64
import asyncio
from typing import Optional, List, Dict, Any
from app.core.config import settings
from app.core.logging import logger

class AIProvider:
    def __init__(self):
        self.provider = (settings.AI_PROVIDER or "gemini").lower()
        self._gemini_client = None
        self._openai_client = None
        self._anthropic_client = None

        try:
            if self.provider == "gemini":
                from google import genai
                # google-genai Client picks up GEMINI_API_KEY from env
                api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
                self._gemini_client = genai.Client(api_key=api_key)
                logger.info("Gemini provider client initialized successfully")
            elif self.provider == "openai":
                from openai import OpenAI
                api_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
                self._openai_client = OpenAI(api_key=api_key)
                logger.info("OpenAI provider client initialized successfully")
            elif self.provider == "claude":
                from anthropic import Anthropic
                api_key = settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY")
                self._anthropic_client = Anthropic(api_key=api_key)
                logger.info("Anthropic Claude provider client initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize AI Provider client", extra={"provider": self.provider, "error": str(e)})

    async def complete(
        self,
        system: str,
        user: str,
        images: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = False
    ) -> str:
        from app.core.errors import ai_circuit_breaker, AICircuitBreakerOpenException
        from app.services.metrics import metrics_service
        
        if not ai_circuit_breaker.allow_request():
            metrics_service.increment_ai_errors()
            logger.error("AI Provider blocked by circuit breaker")
            raise AICircuitBreakerOpenException("AI provider circuit breaker is OPEN")
            
        try:
            res = await asyncio.to_thread(self._complete_sync, system, user, images, json_mode)
            ai_circuit_breaker.record_success()
            return res
        except Exception as e:
            ai_circuit_breaker.record_failure()
            metrics_service.increment_ai_errors()
            raise e


    def _complete_sync(
        self,
        system: str,
        user: str,
        images: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = False
    ) -> str:
        if self.provider == "gemini" and self._gemini_client:
            return self._gemini_complete(system, user, images, json_mode)
        elif self.provider == "openai" and self._openai_client:
            return self._openai_complete(system, user, images, json_mode)
        elif self.provider == "claude" and self._anthropic_client:
            return self._claude_complete(system, user, images, json_mode)
        else:
            # Fallback mock for testing/uninitialized settings
            logger.warning("AI Provider client uninitialized. Returning mock response.", extra={"provider": self.provider})
            if json_mode:
                return json.dumps({
                    "intent": "general_inquiry",
                    "confidence": 0.9,
                    "language": "hinglish"
                })
            return "Mock AI response"

    def _gemini_complete(self, system: str, user: str, images: Optional[List[Dict[str, Any]]], json_mode: bool) -> str:
        from google.genai import types
        model = "gemini-2.5-flash"
        contents = []
        
        if images:
            for img in images:
                part = types.Part.from_bytes(data=img["bytes"], mime_type=img["mime_type"])
                contents.append(part)
        
        contents.append(user)
        
        config_args = {"system_instruction": system, "temperature": 0.1}
        if json_mode:
            config_args["response_mime_type"] = "application/json"
            
        config = types.GenerateContentConfig(**config_args)
        
        response = self._gemini_client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )
        return response.text

    def _openai_complete(self, system: str, user: str, images: Optional[List[Dict[str, Any]]], json_mode: bool) -> str:
        messages = [{"role": "system", "content": system}]
        
        user_content = []
        if images:
            for img in images:
                b64_str = base64.b64encode(img["bytes"]).decode("utf-8")
                mime = img["mime_type"]
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64_str}"
                    }
                })
        
        user_content.append({"type": "text", "text": user})
        messages.append({"role": "user", "content": user_content})
        
        args = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 0.1
        }
        if json_mode:
            args["response_format"] = {"type": "json_object"}
            
        response = self._openai_client.chat.completions.create(**args)
        return response.choices[0].message.content

    def _claude_complete(self, system: str, user: str, images: Optional[List[Dict[str, Any]]], json_mode: bool) -> str:
        user_content = []
        if images:
            for img in images:
                b64_str = base64.b64encode(img["bytes"]).decode("utf-8")
                mime = img["mime_type"]
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64_str
                    }
                })
        user_content.append({"type": "text", "text": user})
        
        response = self._anthropic_client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            temperature=0.1
        )
        return response.content[0].text

ai_provider = AIProvider()
