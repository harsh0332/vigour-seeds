from typing import Any, Dict, List, Optional
from app.db.repositories.distributors import distributors_repo
from app.services.session import session_service
from app.services.ticketing import ticketing
from app.whatsapp.client import whatsapp_client
from app.whatsapp.models import ParsedMessage
from app.core.logging import logger
from app.core.messages_distributor import (
    EXISTING_DIST_MENU_BODY, EXISTING_DIST_DESC_PROMPT, EXISTING_DIST_TICKET_CREATED
)

class ExistingDistributorFlowHandler:
    async def handle_message(self, message: ParsedMessage, session: Any) -> None:
        phone = message.from_phone
        collected = session.collected_json or {}
        step = session.current_step
        
        # Look up distributor
        distributor = await distributors_repo.get_active_by_phone(phone)
        dist_id = distributor.distributor_id if distributor else "DIST_UNKNOWN"
        
        if step == "ticket_init" or not step:
            # Send List menu of categories
            sections = [{
                "title": "सहायता श्रेणियाँ",
                "rows": [
                    {"id": "order_status", "title": "ऑर्डर स्टेटस", "description": "Order status query"},
                    {"id": "stock_query", "title": "स्टॉक", "description": "Stock availability query"},
                    {"id": "scheme_offer", "title": "स्कीम/ऑफर", "description": "Schemes and marketing support"},
                    {"id": "payment_issue", "title": "पेमेंट", "description": "Billing and payment issues"},
                    {"id": "product_complaint", "title": "शिकायत", "description": "Quality or other complaints"},
                    {"id": "dispatch_delay", "title": "डिस्पैच", "description": "Dispatch or logistics delays"},
                    {"id": "other", "title": "और", "description": "Other support queries"}
                ],
                "button_label": "कैटेगरी चुनें"
            }]
            
            await session_service.set_step(phone, "F_DIST_EX_CAT")
            await whatsapp_client.send_list(phone, None, EXISTING_DIST_MENU_BODY, sections)
            return
            
        elif step == "F_DIST_EX_CAT":
            category = None
            if message.type == "list_reply" and message.list_id:
                category = message.list_id
            elif message.type == "button_reply" and message.button_payload:
                category = message.button_payload
            else:
                # Text fallback mapping
                text = (message.text or "").strip().lower()
                from app.services.ticketing import CATEGORY_MAP
                category = CATEGORY_MAP.get(text, "other")
                
            # We want to display the Hindi label or ID
            # Map back to Hindi label for displaying in confirmation if needed,
            # but ticketing.create_ticket maps it correctly.
            # Let's save the selected category in session collected_json
            collected["ticket_category"] = category
            await session_service.patch_collected(phone, {"ticket_category": category})
            
            await session_service.set_step(phone, "F_DIST_EX_DESC")
            await whatsapp_client.send_text(phone, EXISTING_DIST_DESC_PROMPT)
            return
            
        elif step == "F_DIST_EX_DESC":
            description = message.text or ""
            category = collected.get("ticket_category", "other")
            
            if not description.strip():
                await whatsapp_client.send_text(phone, EXISTING_DIST_DESC_PROMPT)
                return
                
            # Create ticket using ticketing service
            ticket = await ticketing.create_ticket(
                lead_id=dist_id,
                phone=phone,
                category=category,
                description=description
            )
            
            # Map canonical category back to Hindi label for display
            category_hi = "अन्य"
            from app.services.ticketing import CATEGORY_MAP
            for hi, eng in CATEGORY_MAP.items():
                if eng == category and hi != eng:
                    category_hi = hi
                    break
                    
            # Reset session
            await session_service.reset(phone)
            
            # Send ticket created confirmation
            confirm_msg = EXISTING_DIST_TICKET_CREATED.format(
                ticket_id=ticket.ticket_id,
                category=category_hi,
                sla_hours=int(ticket.sla_target_hours)
            )
            await whatsapp_client.send_text(phone, confirm_msg)
            return

existing_distributor_flow_handler = ExistingDistributorFlowHandler()
