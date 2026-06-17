import os
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from fastapi import APIRouter

from app.db.client import supabase_client
from app.core.logging import logger

class MetricsService:
    def __init__(self):
        self.msgs_in = 0
        self.msgs_out = 0
        self.intents: Dict[str, int] = {}
        self.farmer_qualified = 0
        self.recos_sent = 0
        self.escalations = 0
        self.distributors_scored = {"HOT": 0, "WARM": 0, "COLD": 0}
        self.tickets_open = 0
        self.followups_sent = 0
        self.ai_errors = 0
        self.response_times: List[float] = []

    def increment_msgs_in(self):
        self.msgs_in += 1

    def increment_msgs_out(self):
        self.msgs_out += 1

    def record_intent(self, intent: str):
        if intent:
            self.intents[intent] = self.intents.get(intent, 0) + 1

    def increment_farmer_qualified(self):
        self.farmer_qualified += 1

    def increment_recos_sent(self):
        self.recos_sent += 1

    def increment_escalations(self):
        self.escalations += 1

    def record_distributor_score(self, tier: str):
        if tier in self.distributors_scored:
            self.distributors_scored[tier] += 1

    def increment_tickets_open(self):
        self.tickets_open += 1

    def increment_followups_sent(self):
        self.followups_sent += 1

    def increment_ai_errors(self):
        self.ai_errors += 1

    def record_response_time(self, seconds: float):
        self.response_times.append(seconds)
        # Cap sliding window size at 1000 items
        if len(self.response_times) > 1000:
            self.response_times.pop(0)

    def get_avg_response_time(self) -> float:
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)

    def get_metrics_dict(self) -> Dict[str, Any]:
        return {
            "msgs_in": self.msgs_in,
            "msgs_out": self.msgs_out,
            "intents": self.intents,
            "farmer_qualified": self.farmer_qualified,
            "recos_sent": self.recos_sent,
            "escalations": self.escalations,
            "distributors_scored": self.distributors_scored,
            "tickets_open": self.tickets_open,
            "followups_sent": self.followups_sent,
            "ai_errors": self.ai_errors,
            "avg_response_time_seconds": round(self.get_avg_response_time(), 4)
        }

    async def push_metrics_to_db(self) -> None:
        """Config-driven DB persistence for metrics logs."""
        if os.environ.get("PUSH_METRICS_TO_DB") == "true" and supabase_client:
            try:
                # Store log record in metrics_log (or conversations log as a system action if table not prepared)
                # Since schema doesn't have metrics_log, we can insert into conversations under direction = 'system'
                # or log it as a trace. If we can run a custom DDL we would, but scope lock prevents new migrations.
                # Let's insert into conversations table as handled_by = 'system' to comply with fixed schema rules.
                await asyncio.to_thread(
                    lambda: supabase_client.table("conversations").insert({
                        "message_id": f"metrics_{int(datetime.utcnow().timestamp())}",
                        "lead_id": "SYSTEM",
                        "whatsapp_phone": "SYSTEM",
                        "direction": "system",
                        "message_type": "text",
                        "message_text": f"Metrics Dump: {self.get_metrics_dict()}",
                        "handled_by": "system"
                    }).execute()
                )
                logger.info("Metrics successfully pushed to database")
            except Exception as e:
                logger.error("Failed to push metrics to database", extra={"error": str(e)})

# Global singleton metrics service
metrics_service = MetricsService()

# APIRouter exposing the metrics
router = APIRouter()

@router.get("/metrics")
async def get_metrics():
    await metrics_service.push_metrics_to_db()
    return metrics_service.get_metrics_dict()
