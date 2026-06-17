import asyncio
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from app.db.client import supabase_client
from app.db.repositories.followups import followups_repo
from app.db.repositories.leads import leads_repo
from app.db.repositories.tickets import tickets_repo
from app.whatsapp.window import send_followup
from app.services.notify import notify
from app.core.logging import logger

class FollowupService:
    async def process_due_followups(self) -> int:
        """Find and process all due followups for farmers, new distributors, and existing distributors."""
        logger.info("Starting follow-up processing run")
        count = 0
        
        # 1. Process due farmers and new distributors
        try:
            due_leads = await followups_repo.due_now()
            logger.info("Found due leads from repository", extra={"count": len(due_leads)})
            for lead in due_leads:
                try:
                    processed = await self._process_lead_followup(lead)
                    if processed:
                        count += 1
                except Exception as e:
                    logger.error("Error processing follow-up for lead", extra={"lead_id": lead.get("lead_id"), "error": str(e)})
        except Exception as e:
            logger.error("Error fetching due leads", extra={"error": str(e)})
                
        # 2. Process existing distributor tickets
        try:
            processed_tickets = await self._process_ticket_followups()
            count += processed_tickets
        except Exception as e:
            logger.error("Error processing ticket follow-ups", extra={"error": str(e)})
            
        logger.info("Follow-up processing run finished", extra={"sent_count": count})
        return count

    async def _process_lead_followup(self, lead: dict) -> bool:
        lead_id = lead.get("lead_id")
        phone = lead.get("whatsapp_phone")
        user_type = lead.get("user_type")
        lead_status = lead.get("lead_status")
        
        if not lead_id or not phone or not user_type or not lead_status:
            logger.warning("Lead missing critical fields", extra={"lead": lead})
            return False
            
        # Fetch the follow-up sequence
        sequence = await followups_repo.get_sequence(user_type, lead_status)
        if not sequence:
            logger.info("No follow-up sequence found", extra={"user_type": user_type, "lead_status": lead_status})
            return False
            
        # Get the current followup_count and last_message_at
        followup_count = 0
        last_message_at = None
        
        if user_type == "farmer":
            full_lead = await leads_repo.get_farmer(phone)
            if not full_lead:
                return False
            followup_count = full_lead.followup_count
            last_message_at = full_lead.last_message_at
        elif user_type == "distributor_new":
            if supabase_client:
                res = await asyncio.to_thread(
                    lambda: supabase_client.table("leads_distributor_new").select("*").eq("lead_id", lead_id).execute()
                )
                if res.data:
                    full_lead = res.data[0]
                    followup_count = full_lead.get("followup_count", 0) or 0
                    last_message_at_str = full_lead.get("last_message_at") or full_lead.get("updated_at")
                    if last_message_at_str:
                        if last_message_at_str.endswith("Z"):
                            last_message_at_str = last_message_at_str[:-1] + "+00:00"
                        last_message_at = datetime.fromisoformat(last_message_at_str)
            else:
                return False
        
        if not last_message_at:
            logger.warning("Lead missing last_message_at timestamp, skipping", extra={"lead_id": lead_id})
            return False
            
        # Standardize last_message_at to UTC timezone
        if last_message_at.tzinfo is None:
            last_message_at = last_message_at.replace(tzinfo=timezone.utc)
        else:
            last_message_at = last_message_at.astimezone(timezone.utc)
            
        # If we have already exhausted the sequence, apply next_action_if_no_reply
        if followup_count >= len(sequence):
            last_step = sequence[-1]
            await self._apply_next_action(lead_id, phone, user_type, lead_status, last_step.next_action_if_no_reply)
            return False
            
        # Select the current step to send
        step = sequence[followup_count]
        
        # Check idempotency: make sure this specific template or message text hasn't already been sent
        is_sent = await self._check_idempotency(phone, step.message_template_id, step.message_text_hindi)
        if is_sent:
            logger.info("Follow-up already sent, skipping to avoid duplicate", extra={"phone": phone, "template_id": step.message_template_id})
            # Progress sequence to next step
            await self._increment_followup(phone, user_type, lead_id, followup_count + 1, sequence, last_message_at)
            return False
            
        # Determine template parameters
        parameters = []
        fallback_text = step.message_text_hindi
        
        if step.message_template_id == "fu_farmer_esc_d1":
            agronomist_phone = "919999999999"  # Default fallback
            if user_type == "farmer":
                full_lead = await leads_repo.get_farmer(phone)
                if full_lead and full_lead.state:
                    if supabase_client:
                        res_reg = await asyncio.to_thread(
                            lambda: supabase_client.table("regions").select("agronomist_phone").eq("state", full_lead.state).execute()
                        )
                        if res_reg.data and res_reg.data[0].get("agronomist_phone"):
                            agronomist_phone = res_reg.data[0]["agronomist_phone"]
            parameters = [agronomist_phone]
            fallback_text = fallback_text.replace("{{1}}", agronomist_phone).replace("[number]", agronomist_phone)
            
        elif step.message_template_id == "fu_dist_qf_d1":
            rep_name = "हमारे सेल्स प्रतिनिधि"
            eta = "24 घंटे"
            if supabase_client:
                res_dist = await asyncio.to_thread(
                    lambda: supabase_client.table("leads_distributor_new").select("assigned_sales_rep").eq("lead_id", lead_id).execute()
                )
                if res_dist.data and res_dist.data[0].get("assigned_sales_rep"):
                    rep_name = res_dist.data[0]["assigned_sales_rep"]
            parameters = [rep_name, eta]
            fallback_text = fallback_text.replace("{{1}}", rep_name).replace("[name]", rep_name).replace("{{2}}", eta).replace("[time]", eta)
            
        # Send followup complying with 24h window
        await send_followup(
            phone=phone,
            template_id=step.message_template_id,
            fallback_text=fallback_text,
            parameters=parameters
        )
        
        # Update followup count and next scheduling
        new_count = followup_count + 1
        await self._increment_followup(phone, user_type, lead_id, new_count, sequence, last_message_at)
        
        # If this was the last step, apply next_action_if_no_reply
        if new_count >= len(sequence):
            await self._apply_next_action(lead_id, phone, user_type, lead_status, step.next_action_if_no_reply)
            
        return True

    async def _check_idempotency(self, phone: str, template_id: str, fallback_text: str) -> bool:
        """Verify if a template message or matching text was already sent to this phone number."""
        if not supabase_client:
            return False
        try:
            # Check by template_id
            res_template = await asyncio.to_thread(
                lambda: supabase_client.table("conversations")
                .select("message_id")
                .eq("whatsapp_phone", phone)
                .eq("direction", "outbound")
                .eq("template_id", template_id)
                .execute()
            )
            if res_template.data:
                return True
                
            # Check by message text content matching the fallback template
            res_text = await asyncio.to_thread(
                lambda: supabase_client.table("conversations")
                .select("message_id")
                .eq("whatsapp_phone", phone)
                .eq("direction", "outbound")
                .eq("message_text", fallback_text)
                .execute()
            )
            return len(res_text.data) > 0
        except Exception as e:
            logger.error("Idempotency check failed", extra={"phone": phone, "template_id": template_id, "error": str(e)})
            return False

    async def _increment_followup(self, phone: str, user_type: str, lead_id: str, new_count: int, sequence: List[Any], last_message_at: datetime) -> None:
        """Increment followup_count and set the next_followup_at time."""
        next_followup_at = None
        if new_count < len(sequence):
            next_step = sequence[new_count]
            next_followup_at = last_message_at + timedelta(hours=next_step.send_after_hours)
            
        now_str = datetime.utcnow().isoformat()
        
        if user_type == "farmer":
            fields = {
                "followup_count": new_count,
                "next_followup_at": next_followup_at.isoformat() if next_followup_at else None,
                "updated_at": now_str
            }
            await leads_repo.upsert_farmer(phone, fields)
        elif user_type == "distributor_new":
            fields = {
                "followup_count": new_count,
                "next_followup_at": next_followup_at.isoformat() if next_followup_at else None,
                "updated_at": now_str
            }
            await leads_repo.upsert_distributor_new(phone, fields)

    async def _apply_next_action(self, lead_id: str, phone: str, user_type: str, lead_status: str, action: str) -> None:
        """Apply final action after followup sequence is completed without reply."""
        logger.info("Applying final followup action", extra={"lead_id": lead_id, "action": action})
        
        now_str = datetime.utcnow().isoformat()
        
        if action == "Mark closed_lost":
            if user_type == "farmer":
                await leads_repo.upsert_farmer(phone, {
                    "lead_status": "closed_lost",
                    "next_followup_at": None,
                    "updated_at": now_str
                })
            elif user_type == "distributor_new":
                await leads_repo.upsert_distributor_new(phone, {
                    "lead_status": "closed_lost",
                    "next_followup_at": None,
                    "updated_at": now_str
                })
        elif action == "Mark closed_won if no issue":
            if user_type == "farmer":
                await leads_repo.upsert_farmer(phone, {
                    "lead_status": "closed_won",
                    "next_followup_at": None,
                    "updated_at": now_str
                })
            elif user_type == "distributor_new":
                await leads_repo.upsert_distributor_new(phone, {
                    "lead_status": "closed_won",
                    "next_followup_at": None,
                    "updated_at": now_str
                })
        else:
            # For actions like "No auto-action — human owns", just cancel next followups
            if user_type == "farmer":
                await leads_repo.upsert_farmer(phone, {
                    "next_followup_at": None,
                    "updated_at": now_str
                })
            elif user_type == "distributor_new":
                await leads_repo.upsert_distributor_new(phone, {
                    "next_followup_at": None,
                    "updated_at": now_str
                })

    async def _process_ticket_followups(self) -> int:
        """Handle followups for existing distributor support tickets."""
        if not supabase_client:
            return 0
            
        now = datetime.now(timezone.utc)
        count = 0
        
        # 1. Ticket status = 'open' followups (4 hours delay, template fu_exdist_tkt_d1)
        res_open = await asyncio.to_thread(
            lambda: supabase_client.table("tickets").select("*").eq("ticket_status", "open").execute()
        )
        for ticket in res_open.data or []:
            try:
                ticket_id = ticket["ticket_id"]
                phone = ticket["whatsapp_phone"]
                created_at_str = ticket["created_at"]
                
                if created_at_str.endswith("Z"):
                    created_at_str = created_at_str[:-1] + "+00:00"
                created_at = datetime.fromisoformat(created_at_str).astimezone(timezone.utc)
                
                # Check if ticket open for >= 4 hours
                if now - created_at >= timedelta(hours=4):
                    # Check idempotency
                    template_id = "fu_exdist_tkt_d1"
                    fallback_text = f"आपकी ticket {ticket_id} हमारी टीम के पास है। हम जल्द ही update देंगे।"
                    
                    is_sent = await self._check_idempotency(phone, template_id, fallback_text)
                    if not is_sent:
                        # Send followup
                        await send_followup(
                            phone=phone,
                            template_id=template_id,
                            fallback_text=fallback_text,
                            parameters=[ticket_id]
                        )
                        count += 1
                        
                    # Check if SLA breached
                    sla_target = ticket.get("sla_target_hours", 24.0)
                    if now - created_at >= timedelta(hours=sla_target):
                        # Escalate to manager
                        manager_phone = os.environ.get("MANAGER_PHONE", os.environ.get("DEFAULT_NOTIFY_PHONE", "919999999999"))
                        escalation_text = (
                            f"🚨 *SLA Breach Escalation!*\n\n"
                            f"🎫 *Ticket ID:* {ticket_id}\n"
                            f"📂 *Category:* {ticket.get('ticket_category')}\n"
                            f"⚠️ *Priority:* {ticket.get('ticket_priority')}\n"
                            f"⏱️ *SLA Target:* {sla_target} hours\n"
                            f"👤 *Assigned Rep:* {ticket.get('assigned_person') or 'Unassigned'}\n"
                            f"📞 *Distributor Phone:* {phone}\n"
                            f"📝 *Description:* {ticket.get('description')}\n\n"
                            f"Please handle immediately!"
                        )
                        await notify.send_to_sales_rep(manager_phone, escalation_text)
            except Exception as e:
                logger.error("Error processing open ticket followup", extra={"ticket_id": ticket.get("ticket_id"), "error": str(e)})

        # 2. Ticket status = 'resolved' followups (24 hours delay, template fu_exdist_resolved_d1)
        res_resolved = await asyncio.to_thread(
            lambda: supabase_client.table("tickets").select("*").eq("ticket_status", "resolved").execute()
        )
        for ticket in res_resolved.data or []:
            try:
                ticket_id = ticket["ticket_id"]
                phone = ticket["whatsapp_phone"]
                # Use resolved_at or updated_at
                resolved_at_str = ticket.get("resolved_at") or ticket.get("updated_at")
                
                if resolved_at_str:
                    if resolved_at_str.endswith("Z"):
                        resolved_at_str = resolved_at_str[:-1] + "+00:00"
                    resolved_at = datetime.fromisoformat(resolved_at_str).astimezone(timezone.utc)
                    
                    # Check if resolved for >= 24 hours
                    if now - resolved_at >= timedelta(hours=24):
                        # Check idempotency
                        template_id = "fu_exdist_resolved_d1"
                        fallback_text = "क्या आपकी समस्या solve हो गई? कृपया 1-5 rating दें।"
                        
                        is_sent = await self._check_idempotency(phone, template_id, fallback_text)
                        if not is_sent:
                            # Send followup
                            await send_followup(
                                phone=phone,
                                template_id=template_id,
                                fallback_text=fallback_text,
                                parameters=[]
                            )
                            count += 1
                            
                    # Check if resolved for >= 7 days -> Auto-close
                    if now - resolved_at >= timedelta(days=7):
                        await tickets_repo.update_status(ticket_id, "closed")
                        logger.info("Auto-closed ticket after 7 days of resolved status", extra={"ticket_id": ticket_id})
            except Exception as e:
                logger.error("Error processing resolved ticket followup", extra={"ticket_id": ticket.get("ticket_id"), "error": str(e)})
                
        return count

followup_service = FollowupService()
