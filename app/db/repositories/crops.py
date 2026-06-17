import asyncio
from typing import List, Optional
from app.db.client import supabase_client
from app.models.db_models import CropRow
from app.core.logging import logger

class CropsRepository:
    @staticmethod
    def _get_by_id(crop_id: str) -> Optional[CropRow]:
        if not supabase_client:
            return None
        res = supabase_client.table("crops").select("*").eq("crop_id", crop_id).execute()
        return CropRow(**res.data[0]) if res.data else None

    async def get_by_id(self, crop_id: str) -> Optional[CropRow]:
        return await asyncio.to_thread(self._get_by_id, crop_id)

    @staticmethod
    def _get_by_button_label(label: str) -> Optional[CropRow]:
        if not supabase_client:
            return None
        res = supabase_client.table("crops").select("*").eq("whatsapp_button_label", label).execute()
        return CropRow(**res.data[0]) if res.data else None

    async def get_by_button_label(self, label: str) -> Optional[CropRow]:
        return await asyncio.to_thread(self._get_by_button_label, label)

    @staticmethod
    def _list_in_catalog() -> List[CropRow]:
        if not supabase_client:
            return []
        res = supabase_client.table("crops").select("*").eq("in_catalog", "Y").execute()
        return [CropRow(**row) for row in res.data] if res.data else []

    async def list_in_catalog(self) -> List[CropRow]:
        return await asyncio.to_thread(self._list_in_catalog)

crops_repo = CropsRepository()
