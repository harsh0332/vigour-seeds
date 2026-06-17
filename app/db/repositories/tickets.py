import asyncio
import uuid
from datetime import datetime
from app.db.client import supabase_client
from app.models.db_models import TicketRow
from app.core.logging import logger

class TicketsRepository:
    @staticmethod
    def _create(ticket: dict) -> TicketRow:
        if not supabase_client:
            raise RuntimeError("Database client not initialized")
        
        data = dict(ticket)
        now_str = datetime.utcnow().isoformat()
        if "ticket_id" not in data:
            # Let's generate a human friendly ID or simple uuid
            data["ticket_id"] = "TKT-" + str(uuid.uuid4())[:8].upper()
        if "created_at" not in data:
            data["created_at"] = now_str
        if "updated_at" not in data:
            data["updated_at"] = now_str
            
        res = supabase_client.table("tickets").insert(data).execute()
        return TicketRow(**res.data[0])

    async def create(self, ticket: dict) -> TicketRow:
        return await asyncio.to_thread(self._create, ticket)

    @staticmethod
    def _update_status(ticket_id: str, status: str) -> bool:
        if not supabase_client:
            return False
        res = supabase_client.table("tickets").update({
            "ticket_status": status,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("ticket_id", ticket_id).execute()
        return len(res.data) > 0

    async def update_status(self, ticket_id: str, status: str) -> bool:
        return await asyncio.to_thread(self._update_status, ticket_id, status)

tickets_repo = TicketsRepository()
