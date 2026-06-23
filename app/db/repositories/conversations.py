import asyncio
from datetime import datetime
from app.db.client import supabase_client
from app.models.db_models import ConversationRow
from app.core.logging import logger

class ConversationsRepository:
    @staticmethod
    def _log(message: dict) -> ConversationRow:
        if not supabase_client:
            raise RuntimeError("Database client not initialized")
        
        data = dict(message)
        if "created_at" not in data:
            data["created_at"] = datetime.utcnow().isoformat()
            
        res = supabase_client.table("conversations").insert(data).execute()
        return ConversationRow(**res.data[0])

    async def log(self, message: dict) -> ConversationRow:
        return await asyncio.to_thread(self._log, message)

    @staticmethod
    def _clear(phone: str) -> bool:
        if not supabase_client:
            return False
        res = supabase_client.table("conversations").delete().eq("whatsapp_phone", phone).execute()
        return len(res.data) > 0

    async def clear(self, phone: str) -> bool:
        return await asyncio.to_thread(self._clear, phone)

    async def delete(self, phone: str) -> bool:
        return await self.clear(phone)

conversations_repo = ConversationsRepository()
