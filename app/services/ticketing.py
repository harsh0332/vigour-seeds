from typing import Optional, Dict, Any
from app.db.repositories.tickets import tickets_repo
from app.db.repositories.distributors import distributors_repo
from app.ai.provider import ai_provider
from app.services.notify import notify
from app.core.logging import logger
from app.models.db_models import TicketRow

CATEGORY_MAP = {
    "ऑर्डर स्टेटस": "order_status",
    "स्टॉक": "stock_query",
    "स्कीम/ऑफर": "scheme_offer",
    "पेमेंट": "payment_issue",
    "शिकायत": "product_complaint",
    "डिस्पैच": "dispatch_delay",
    "और": "other",
    "order_status": "order_status",
    "stock_query": "stock_query",
    "scheme_offer": "scheme_offer",
    "payment_issue": "payment_issue",
    "product_complaint": "product_complaint",
    "dispatch_delay": "dispatch_delay",
    "replacement_claim": "replacement_claim",
    "marketing_support": "marketing_support",
    "other": "other"
}

CATEGORY_RULES = {
    "order_status": {"team": "sales", "priority": "medium", "sla_hours": 24.0},
    "stock_query": {"team": "sales", "priority": "medium", "sla_hours": 24.0},
    "payment_issue": {"team": "accounts", "priority": "high", "sla_hours": 24.0},
    "dispatch_delay": {"team": "logistics", "priority": "high", "sla_hours": 24.0},
    "replacement_claim": {"team": "logistics", "priority": "high", "sla_hours": 24.0},
    "scheme_offer": {"team": "marketing", "priority": "low", "sla_hours": 48.0},
    "marketing_support": {"team": "marketing", "priority": "low", "sla_hours": 48.0},
    "product_complaint": {"team": "agronomy", "priority": "high", "sla_hours": 24.0},
    "other": {"team": "support", "priority": "medium", "sla_hours": 24.0}
}

class TicketingService:
    async def summarize_subject(self, description: str) -> str:
        """Summarize user complaint description using AI into a short English subject."""
        system_prompt = (
            "You are a professional customer support assistant. Summarize the user's issue description "
            "into a short, professional, concise English subject phrase (max 5-7 words). Output ONLY the "
            "plain summarized subject phrase without any extra quotes, labels, or explanatory text."
        )
        try:
            subject = await ai_provider.complete(system_prompt, description)
            subject = subject.strip().strip('"').strip("'")
            if not subject or "mock ai response" in subject.lower():
                subject = description[:40] + "..." if len(description) > 40 else description
            return subject
        except Exception as e:
            logger.error("AI subject summarization failed, falling back to manual truncation", extra={"error": str(e)})
            return description[:40] + "..." if len(description) > 40 else description

    async def create_ticket(
        self,
        lead_id: str,
        phone: str,
        category: str,
        description: str,
        user_type: str = "distributor_existing"
    ) -> TicketRow:
        """
        Create a support ticket, auto-routing by category rules,
        assigning sales reps where relevant, and alerting team.
        """
        # Map raw category input to canonical category
        canonical_category = CATEGORY_MAP.get(category, "other")
        
        # Get priority, team, and SLA
        rules = CATEGORY_RULES.get(canonical_category, CATEGORY_RULES["other"])
        assigned_team = rules["team"]
        priority = rules["priority"]
        sla_hours = rules["sla_hours"]
        
        # Summarize subject using AI
        subject = await self.summarize_subject(description)
        
        # Retrieve assigned sales rep from distributors_active
        assigned_person = None
        try:
            distributor = await distributors_repo.get_active_by_phone(phone)
            if distributor:
                assigned_person = distributor.assigned_sales_rep
        except Exception as e:
            logger.error("Failed to query distributor details during ticket assignment", extra={"phone": phone, "error": str(e)})
            
        ticket_data = {
            "lead_id": lead_id,
            "whatsapp_phone": phone,
            "user_type": user_type,
            "ticket_category": canonical_category,
            "ticket_priority": priority,
            "ticket_status": "open",
            "subject": subject,
            "description": description,
            "assigned_team": assigned_team,
            "assigned_person": assigned_person,
            "sla_target_hours": sla_hours
        }
        
        # Save ticket in repository
        ticket = await tickets_repo.create(ticket_data)
        
        try:
            from app.services.metrics import metrics_service
            metrics_service.increment_tickets_open()
        except Exception:
            pass
        
        # Dispatch team notifications
        try:
            await notify.notify_team(assigned_team, ticket)
        except Exception as e:
            logger.error("Failed to dispatch ticket team notification", extra={"ticket_id": ticket.ticket_id, "error": str(e)})
            
        return ticket

ticketing = TicketingService()
