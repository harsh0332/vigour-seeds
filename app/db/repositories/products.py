import asyncio
from typing import List, Optional
from app.db.client import supabase_client
from app.models.db_models import ProductRow
from app.core.logging import logger

class ProductsRepository:
    @staticmethod
    def _get_by_id(product_id: str) -> Optional[ProductRow]:
        if not supabase_client:
            return None
        res = supabase_client.table("products").select("*").eq("product_id", product_id).execute()
        return ProductRow(**res.data[0]) if res.data else None

    async def get_by_id(self, product_id: str) -> Optional[ProductRow]:
        return await asyncio.to_thread(self._get_by_id, product_id)

    @staticmethod
    def _list_by_crop(crop: str) -> List[ProductRow]:
        if not supabase_client:
            return []
        res = supabase_client.table("products").select("*").ilike("crop", crop).execute()
        return [ProductRow(**row) for row in res.data] if res.data else []

    async def list_by_crop(self, crop: str) -> List[ProductRow]:
        return await asyncio.to_thread(self._list_by_crop, crop)

    @staticmethod
    def _list_approved_for(crop: str, stage: str, problem: str, region: str) -> List[ProductRow]:
        if not supabase_client:
            return []
        # Query crop products that are approved
        res = supabase_client.table("products").select("*").ilike("crop", crop).eq("approved_for_recommendation", "Y").execute()
        if not res.data:
            return []
        
        filtered = []
        for row in res.data:
            # Region matching
            target_region = row.get("target_region") or ""
            if region and target_region:
                regions_list = [r.strip().lower() for r in target_region.split(",")]
                if region.lower() not in regions_list and "any" not in regions_list and "all" not in regions_list:
                    continue
            filtered.append(ProductRow(**row))
        return filtered

    async def list_approved_for(self, crop: str, stage: str, problem: str, region: str) -> List[ProductRow]:
        return await asyncio.to_thread(self._list_approved_for, crop, stage, problem, region)

    @staticmethod
    def _list_approved_crops() -> List[str]:
        if not supabase_client:
            return []
        res = supabase_client.table("products").select("crop").eq("approved_for_recommendation", "Y").execute()
        if not res.data:
            return []
        crops = {row["crop"] for row in res.data if row.get("crop")}
        return sorted(list(crops))

    async def list_approved_crops(self) -> List[str]:
        return await asyncio.to_thread(self._list_approved_crops)

products_repo = ProductsRepository()
