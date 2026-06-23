import asyncio
from datetime import datetime
from typing import Optional
from app.db.client import supabase_client
from app.models.db_models import SessionRow
from app.core.logging import logger

class SessionsRepository:
    @staticmethod
    def _get(phone: str) -> Optional[SessionRow]:
        if not supabase_client:
            return None
        res = supabase_client.table("sessions").select("*").eq("whatsapp_phone", phone).execute()
        return SessionRow(**res.data[0]) if res.data else None

    async def get(self, phone: str) -> Optional[SessionRow]:
        return await asyncio.to_thread(self._get, phone)

    @staticmethod
    def _upsert(phone: str, patch: dict) -> SessionRow:
        if not supabase_client:
            raise RuntimeError("Database client not initialized")

        res = supabase_client.table("sessions").select("*").eq("whatsapp_phone", phone).execute()
        now_str = datetime.utcnow().isoformat()

        if res.data:
            existing = res.data[0]
            collected = dict(existing.get("collected_json") or {})
            if "collected_json" in patch and patch["collected_json"] is not None:
                collected.update(patch["collected_json"])

            data = dict(patch)
            if "collected_json" in patch:
                data["collected_json"] = collected
            data["updated_at"] = now_str
            data["last_message_at"] = now_str

            res_upd = supabase_client.table("sessions").update(data).eq("whatsapp_phone", phone).execute()
            return SessionRow(**res_upd.data[0])
        else:
            data = dict(patch)
            data["whatsapp_phone"] = phone
            if "collected_json" not in data or data["collected_json"] is None:
                data["collected_json"] = {}
            if "current_step" not in data or data["current_step"] is None:
                data["current_step"] = "start"
            data["updated_at"] = now_str
            data["last_message_at"] = now_str

            res_ins = supabase_client.table("sessions").insert(data).execute()
            return SessionRow(**res_ins.data[0])

    async def upsert(self, phone: str, patch: dict) -> SessionRow:
        return await asyncio.to_thread(self._upsert, phone, patch)

    @staticmethod
    def _clear(phone: str) -> bool:
        if not supabase_client:
            return False
        res = supabase_client.table("sessions").delete().eq("whatsapp_phone", phone).execute()
        return len(res.data) > 0

    async def clear(self, phone: str) -> bool:
        return await asyncio.to_thread(self._clear, phone)

    async def delete(self, phone: str) -> bool:
        return await self.clear(phone)

sessions_repo = SessionsRepository()
