import os
from typing import Dict, Any, Optional
from app.whatsapp.client import whatsapp_client
from app.db.client import supabase_client
from app.core.logging import logger

class NotificationService:
    async def send_to_sales_rep(self, phone: str, summary: str) -> None:
        """Send a WhatsApp notification to a sales representative."""
        logger.info("Sending notification to sales representative", extra={"phone": phone, "summary": summary})
        try:
            await whatsapp_client.send_text(phone, summary)
        except Exception as e:
            logger.error("Failed to send notification to sales representative", extra={"phone": phone, "error": str(e)})

    async def sales_now(self, lead: dict) -> None:
        """Notify the sales rep immediately for a HOT lead."""
        state = lead.get("state")
        district = lead.get("district")
        shop_name = lead.get("shop_name", "Unknown Shop")
        contact_name = lead.get("contact_name", "Unknown Contact")
        phone = lead.get("whatsapp_phone", "Unknown Phone")
        score = lead.get("lead_score")
        volume = lead.get("monthly_sales_volume_inr", 0)

        # Retrieve sales rep phone from regions table
        rep_phone = None
        rep_name = None
        if supabase_client and state:
            try:
                res = supabase_client.table("regions").select("sales_rep_phone, sales_rep_name").eq("state", state).execute()
                if not res.data:
                    # Retry with state code mapping or direct state code if state is code
                    res = supabase_client.table("regions").select("sales_rep_phone, sales_rep_name").eq("state_code", state).execute()
                if res.data:
                    rep_phone = res.data[0].get("sales_rep_phone")
                    rep_name = res.data[0].get("sales_rep_name")
            except Exception as e:
                logger.error("Failed to fetch sales rep from regions in sales_now", extra={"state": state, "error": str(e)})

        # Fallback to env var or default if not found
        if not rep_phone:
            rep_phone = os.environ.get("DEFAULT_NOTIFY_PHONE", "919999999999")
            rep_name = "Default Sales Rep"

        summary = (
            f"🚨 *HOT Distributor Lead Alert!*\n\n"
            f"👤 *Contact:* {contact_name}\n"
            f"🏪 *Shop:* {shop_name}\n"
            f"📞 *Phone:* {phone}\n"
            f"📍 *Location:* {district}, {state}\n"
            f"💰 *Monthly Sales:* ₹{volume:,.2f}\n"
            f"🎯 *Score:* {score} (HOT)\n\n"
            f"Please contact them immediately! 🤝"
        )
        
        await self.send_to_sales_rep(rep_phone, summary)

    async def notify_team(self, team: str, ticket: Any) -> None:
        """Send a WhatsApp notification to the assigned team or sales representative about a ticket."""
        ticket_id = getattr(ticket, "ticket_id", ticket.get("ticket_id") if isinstance(ticket, dict) else "Unknown")
        category = getattr(ticket, "ticket_category", ticket.get("ticket_category") if isinstance(ticket, dict) else "Unknown")
        priority = getattr(ticket, "ticket_priority", ticket.get("ticket_priority") if isinstance(ticket, dict) else "Medium")
        description = getattr(ticket, "description", ticket.get("description") if isinstance(ticket, dict) else "")
        phone = getattr(ticket, "whatsapp_phone", ticket.get("whatsapp_phone") if isinstance(ticket, dict) else "Unknown")

        # Determine rep/support phone number to send to
        rep_phone = None
        if supabase_client and phone:
            try:
                # Find distributor rep
                res_dist = supabase_client.table("distributors_active").select("assigned_sales_rep_phone").eq("whatsapp_phone", phone).execute()
                if res_dist.data:
                    rep_phone = res_dist.data[0].get("assigned_sales_rep_phone")
            except Exception as e:
                logger.error("Failed to fetch distributor's sales rep phone", extra={"phone": phone, "error": str(e)})

        if not rep_phone:
            # Check team specific phone numbers in environment, or default to general support phone
            env_var = f"{team.upper()}_TEAM_PHONE"
            rep_phone = os.environ.get(env_var, os.environ.get("DEFAULT_NOTIFY_PHONE", "919999999999"))

        summary = (
            f"🎫 *New Support Ticket Assigned!*\n\n"
            f"🆔 *Ticket ID:* {ticket_id}\n"
            f"👥 *Team:* {team}\n"
            f"📂 *Category:* {category}\n"
            f"⚠️ *Priority:* {priority}\n"
            f"📞 *Distributor Phone:* {phone}\n"
            f"📝 *Description:* {description}\n\n"
            f"Please review and respond within SLA! 🤝"
        )
        
        await self.send_to_sales_rep(rep_phone, summary)

notify = NotificationService()
