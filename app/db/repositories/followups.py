import asyncio
from datetime import datetime
from typing import List
from app.db.client import supabase_client
from app.models.db_models import FollowupRow
from app.core.logging import logger

class FollowupsRepository:
    @staticmethod
    def _get_sequence(user_type: str, lead_status: str) -> List[FollowupRow]:
        if not supabase_client:
            return []
        res = supabase_client.table("followups").select("*").eq("user_type", user_type).eq("lead_status", lead_status).order("day").execute()
        return [FollowupRow(**row) for row in res.data] if res.data else []

    async def get_sequence(self, user_type: str, lead_status: str) -> List[FollowupRow]:
        return await asyncio.to_thread(self._get_sequence, user_type, lead_status)

    @staticmethod
    def _due_now() -> List[dict]:
        if not supabase_client:
            return []
        
        now_str = datetime.utcnow().isoformat()
        
        # Fetch farmers due for followup
        farmers = supabase_client.table("leads_farmer")\
            .select("lead_id, whatsapp_phone, user_type, lead_status, next_followup_at")\
            .lte("next_followup_at", now_str)\
            .execute()
            
        # Fetch new distributors due for followup
        dists = supabase_client.table("leads_distributor_new")\
            .select("lead_id, whatsapp_phone, user_type, lead_status, next_followup_at")\
            .lte("next_followup_at", now_str)\
            .execute()
            
        due = []
        if farmers.data:
            due.extend(farmers.data)
        if dists.data:
            due.extend(dists.data)
            
        return due

    async def due_now(self) -> List[dict]:
        return await asyncio.to_thread(self._due_now)

followups_repo = FollowupsRepository()
