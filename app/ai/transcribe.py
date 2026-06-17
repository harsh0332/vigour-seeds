import asyncio
import io
from app.ai.provider import ai_provider
from app.whatsapp.client import whatsapp_client
from app.core.config import settings
from app.core.logging import logger

class VoiceTranscriptionService:
    async def transcribe_audio(self, media_id: str, mime_type: str) -> str:
        """Download audio media from WhatsApp and transcribe it using the configured AI provider."""
        logger.info("Transcribing audio media", extra={"media_id": media_id, "mime_type": mime_type})
        
        # 1. Download media bytes
        audio_bytes, actual_mime = await whatsapp_client.download_media(media_id)
        if not audio_bytes:
            logger.error("Failed to download audio bytes for transcription", extra={"media_id": media_id})
            return ""
            
        # Standardize mime type
        target_mime = mime_type.split(";")[0].strip() if ";" in mime_type else mime_type
        
        # 2. Transcribe using AI provider
        provider_name = (settings.AI_PROVIDER or "gemini").lower()
        
        if provider_name == "gemini" and ai_provider._gemini_client:
            return await asyncio.to_thread(self._transcribe_gemini, audio_bytes, target_mime)
        elif provider_name == "openai" and ai_provider._openai_client:
            return await asyncio.to_thread(self._transcribe_whisper, audio_bytes, target_mime)
        else:
            logger.warning("No supported transcription client initialized. Returning mock transcription.", extra={"provider": provider_name})
            return "Mock transcription of crop problem"

    def _transcribe_gemini(self, audio_bytes: bytes, mime_type: str) -> str:
        from google.genai import types
        try:
            model = "gemini-2.5-flash"
            contents = [
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                "Please transcribe this audio. Output ONLY the transcription in the original language spoken (Hindi/English/Hinglish). Do not translate or add extra text."
            ]
            response = ai_provider._gemini_client.models.generate_content(
                model=model,
                contents=contents
            )
            return response.text.strip()
        except Exception as e:
            logger.error("Gemini audio transcription failed", extra={"error": str(e)})
            return ""

    def _transcribe_whisper(self, audio_bytes: bytes, mime_type: str) -> str:
        try:
            # Prepare file-like object for transcription
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "audio.ogg" if "ogg" in mime_type else ("audio.mp3" if "mp3" in mime_type else "audio.wav")
            
            transcription = ai_provider._openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
            return transcription.text.strip()
        except Exception as e:
            logger.error("Whisper audio transcription failed", extra={"error": str(e)})
            return ""

voice_transcription_service = VoiceTranscriptionService()
