import asyncio
from typing import Optional
from app.db.client import supabase_client
from app.models.db_models import RegionRow
from app.core.logging import logger

class RegionsRepository:
    @staticmethod
    def _get_by_state(state: str) -> Optional[RegionRow]:
        if not supabase_client:
            return None
        # Support searching by either full state name or state code (case-insensitive)
        val = state.strip()
        res = supabase_client.table("regions").select("*")\
            .or_(f"state.ilike.{val},state_code.ilike.{val}")\
            .execute()
        return RegionRow(**res.data[0]) if res.data else None

    async def get_by_state(self, state: str) -> Optional[RegionRow]:
        return await asyncio.to_thread(self._get_by_state, state)

regions_repo = RegionsRepository()
