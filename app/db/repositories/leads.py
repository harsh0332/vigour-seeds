import asyncio
import uuid
from datetime import datetime
from typing import Optional
from app.db.client import supabase_client
from app.models.db_models import LeadFarmerRow, LeadDistributorNewRow
from app.core.logging import logger

class LeadsRepository:
    @staticmethod
    def _upsert_farmer(phone: str, fields: dict) -> LeadFarmerRow:
        if not supabase_client:
            raise RuntimeError("Database client not initialized")
        
        # Check if exists
        res = supabase_client.table("leads_farmer").select("*").eq("whatsapp_phone", phone).execute()
        now_str = datetime.utcnow().isoformat()
        
        # Merge values
        data = dict(fields)
        data["whatsapp_phone"] = phone
        data["updated_at"] = now_str
        
        if res.data:
            # Update existing
            existing_id = res.data[0]["lead_id"]
            res_upd = supabase_client.table("leads_farmer").update(data).eq("lead_id", existing_id).execute()
            return LeadFarmerRow(**res_upd.data[0])
        else:
            # Insert new
            if "lead_id" not in data:
                data["lead_id"] = str(uuid.uuid4())
            if "created_at" not in data:
                data["created_at"] = now_str
            res_ins = supabase_client.table("leads_farmer").insert(data).execute()
            return LeadFarmerRow(**res_ins.data[0])

    async def upsert_farmer(self, phone: str, fields: dict) -> LeadFarmerRow:
        return await asyncio.to_thread(self._upsert_farmer, phone, fields)

    @staticmethod
    def _upsert_distributor_new(phone: str, fields: dict) -> LeadDistributorNewRow:
        if not supabase_client:
            raise RuntimeError("Database client not initialized")
        
        # Check if exists
        res = supabase_client.table("leads_distributor_new").select("*").eq("whatsapp_phone", phone).execute()
        now_str = datetime.utcnow().isoformat()
        
        data = dict(fields)
        data["whatsapp_phone"] = phone
        data["updated_at"] = now_str
        
        if res.data:
            # Update existing
            existing_id = res.data[0]["lead_id"]
            res_upd = supabase_client.table("leads_distributor_new").update(data).eq("lead_id", existing_id).execute()
            return LeadDistributorNewRow(**res_upd.data[0])
        else:
            # Insert new
            if "lead_id" not in data:
                data["lead_id"] = str(uuid.uuid4())
            if "created_at" not in data:
                data["created_at"] = now_str
            res_ins = supabase_client.table("leads_distributor_new").insert(data).execute()
            return LeadDistributorNewRow(**res_ins.data[0])

    async def upsert_distributor_new(self, phone: str, fields: dict) -> LeadDistributorNewRow:
        return await asyncio.to_thread(self._upsert_distributor_new, phone, fields)

    @staticmethod
    def _get_farmer(phone: str) -> Optional[LeadFarmerRow]:
        if not supabase_client:
            return None
        res = supabase_client.table("leads_farmer").select("*").eq("whatsapp_phone", phone).execute()
        return LeadFarmerRow(**res.data[0]) if res.data else None

    async def get_farmer(self, phone: str) -> Optional[LeadFarmerRow]:
        return await asyncio.to_thread(self._get_farmer, phone)

    @staticmethod
    def _update_status(lead_id: str, user_type: str, status: str) -> bool:
        if not supabase_client:
            return False
        table = "leads_farmer" if user_type == "farmer" else "leads_distributor_new"
        res = supabase_client.table(table).update({"lead_status": status, "updated_at": datetime.utcnow().isoformat()}).eq("lead_id", lead_id).execute()
        return len(res.data) > 0

    async def update_status(self, lead_id: str, user_type: str, status: str) -> bool:
        return await asyncio.to_thread(self._update_status, lead_id, user_type, status)

    @staticmethod
    def _set_score(lead_id: str, user_type: str, score: str) -> bool:
        if not supabase_client:
            return False
        table = "leads_farmer" if user_type == "farmer" else "leads_distributor_new"
        res = supabase_client.table(table).update({"lead_score": score, "updated_at": datetime.utcnow().isoformat()}).eq("lead_id", lead_id).execute()
        return len(res.data) > 0

    async def set_score(self, lead_id: str, user_type: str, score: str) -> bool:
        return await asyncio.to_thread(self._set_score, lead_id, user_type, score)

leads_repo = LeadsRepository()
