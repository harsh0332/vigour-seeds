import asyncio
from typing import Optional
from app.db.client import supabase_client
from app.models.db_models import DistributorActiveRow
from app.core.logging import logger

class DistributorsRepository:
    @staticmethod
    def _get_active_by_phone(phone: str) -> Optional[DistributorActiveRow]:
        if not supabase_client:
            return None
        res = supabase_client.table("distributors_active").select("*").eq("whatsapp_phone", phone).eq("active_status", "active").execute()
        return DistributorActiveRow(**res.data[0]) if res.data else None

    async def get_active_by_phone(self, phone: str) -> Optional[DistributorActiveRow]:
        return await asyncio.to_thread(self._get_active_by_phone, phone)

distributors_repo = DistributorsRepository()
