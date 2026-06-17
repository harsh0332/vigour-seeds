import asyncio
from typing import Dict, Any

from app.db.client import supabase_client
from app.core.logging import logger

class DealerLocatorService:
    @staticmethod
    def _locate(state: str, district: str) -> Dict[str, Any]:
        result = {
            "depot": None,
            "sales_rep_name": None,
            "sales_rep_phone": None,
            "agronomist_name": None,
            "agronomist_phone": None,
            "dealers": []
        }
        if not supabase_client:
            return result
            
        try:
            # Query regions for depot, sales rep, and agronomist details
            # Match state name or state code
            res_reg = supabase_client.table("regions").select("*").eq("state", state).execute()
            if not res_reg.data:
                res_reg = supabase_client.table("regions").select("*").eq("state_code", state).execute()
                
            if res_reg.data:
                reg = res_reg.data[0]
                result["depot"] = reg.get("nearest_depot")
                result["sales_rep_name"] = reg.get("sales_rep_name")
                result["sales_rep_phone"] = reg.get("sales_rep_phone")
                result["agronomist_name"] = reg.get("agronomist_name")
                result["agronomist_phone"] = reg.get("agronomist_phone")
        except Exception as e:
            logger.error("Failed to query regions in dealer locator", extra={"state": state, "error": str(e)})

        try:
            # Query up to 2 active dealers in the same district and state
            # Match state name or state code
            query = supabase_client.table("distributors_active") \
                .select("distributor_id, shop_name, contact_name, whatsapp_phone") \
                .eq("district", district) \
                .eq("active_status", "active")
            
            res_dealers = query.eq("state", state).limit(2).execute()
            if not res_dealers.data:
                res_dealers = query.eq("state", state).limit(2).execute() # Retry standard
                
            if res_dealers.data:
                result["dealers"] = res_dealers.data
        except Exception as e:
            logger.error("Failed to query distributors in dealer locator", extra={"state": state, "district": district, "error": str(e)})
            
        return result

    async def locate(self, state: str, district: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._locate, state, district)

dealer_locator = DealerLocatorService()
