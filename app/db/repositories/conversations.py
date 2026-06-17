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

conversations_repo = ConversationsRepository()
