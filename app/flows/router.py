from typing import Optional, Dict, Any
from datetime import datetime
from app.db.client import supabase_client
from app.db.repositories.distributors import distributors_repo
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo
from app.services.session import session_service
from app.whatsapp.client import whatsapp_client
from app.whatsapp.models import ParsedMessage
from app.ai.intent import classify_intent
from app.core.logging import logger
from app.core.messages import WELCOME_BODY, WELCOME_BUTTONS, EXISTING_DISTRIBUTOR_GREET, FALLBACK_MESSAGE
from app.flows.farmer import farmer_flow_handler
from app.flows.distributor_new import distributor_new_flow_handler
from app.flows.distributor_existing import existing_distributor_flow_handler

async def handle_recommendation_button(phone: str, payload: str) -> None:
    lead = await leads_repo.get_farmer(phone)
    if not lead:
        await whatsapp_client.send_text(phone, "माफ़ कीजिए, हमें आपकी कोई जानकारी नहीं मिली।")
        return
        
    state = lead.state
    district = lead.district
    
    if payload == "ACT_DEALER":
        from app.services.dealer_locator import dealer_locator
        from app.core.messages_reco import (
            DEALER_CARD_HEADER, DEALER_DEPOT_INFO, DEALER_CONTACT_CARD, DEALER_NOT_FOUND
        )
        
        loc = await dealer_locator.locate(state, district)
        await whatsapp_client.send_text(phone, DEALER_CARD_HEADER)
        
        if loc["depot"] or loc["sales_rep_name"]:
            depot_text = DEALER_DEPOT_INFO.format(
                depot=loc["depot"] or "-",
                rep_name=loc["sales_rep_name"] or "-",
                rep_phone=loc["sales_rep_phone"] or "-"
            )
            await whatsapp_client.send_text(phone, depot_text)
            
        dealers = loc["dealers"]
        if dealers:
            for d in dealers:
                card = DEALER_CONTACT_CARD.format(
                    shop_name=d["shop_name"],
                    contact_name=d["contact_name"],
                    phone=d["whatsapp_phone"]
                )
                await whatsapp_client.send_text(phone, card)
                
            # Conversion Tactics: Dealer-handoff warm intro
            import os
            if os.environ.get("ENABLE_DEALER_WARM_INTRO", "false").lower() == "true":
                try:
                    dealer_phone = dealers[0]["whatsapp_phone"]
                    crop_details = lead.current_crop or "N/A"
                    from app.db.repositories.crops import crops_repo
                    crop_row = await crops_repo.get_by_id(crop_details)
                    crop_name = crop_row.crop_name_hi if crop_row else crop_details
                    
                    prob_cat = lead.problem_category or []
                    primary_prob = prob_cat[0] if prob_cat else "N/A"
                    
                    dealer_alert = (
                        f"📢 *नया किसान लीड अलर्ट (New Farmer Lead)*\n\n"
                        f"किसान का नाम: {lead.name}\n"
                        f"फ़ोन नंबर: {lead.whatsapp_phone}\n"
                        f"फ़सल: {crop_name}\n"
                        f"समस्या: {primary_prob}\n\n"
                        f"कृपया किसान से संपर्क कर सहायता करें।"
                    )
                    await whatsapp_client.send_text(dealer_phone, dealer_alert)
                    logger.info("Dealer warm intro notification sent", extra={"dealer_phone": dealer_phone, "farmer_phone": phone})
                except Exception as dealer_notify_err:
                    logger.error("Failed to notify dealer with warm intro", extra={"error": str(dealer_notify_err)})
                
            lead_dict = lead.model_dump() if hasattr(lead, "model_dump") else lead.dict()
            lead_dict["nearest_dealer_id"] = dealers[0]["distributor_id"]
            lead_dict["updated_at"] = datetime.utcnow().isoformat() + "Z"
            await leads_repo.upsert_farmer(phone, lead_dict)
        else:
            await whatsapp_client.send_text(phone, DEALER_NOT_FOUND)
            
    elif payload == "ACT_CALLBACK":
        from app.core.messages_reco import CALLBACK_ASK
        
        await sessions_repo.upsert(phone, {
            "current_flow": "farmer_qualification",
            "current_step": "WAIT_CALLBACK_TIME"
        })
        await whatsapp_client.send_text(phone, CALLBACK_ASK)
        
    elif payload == "ACT_AGRONOMIST":
        from app.services.dealer_locator import dealer_locator
        from app.core.messages_reco import AGRONOMIST_CONTACT_INFO, AGRONOMIST_NOT_FOUND
        
        loc = await dealer_locator.locate(state, district)
        if loc["agronomist_name"] and loc["agronomist_phone"]:
            text = AGRONOMIST_CONTACT_INFO.format(
                name=loc["agronomist_name"],
                phone=loc["agronomist_phone"]
            )
            await whatsapp_client.send_text(phone, text)
            
            lead_dict = lead.model_dump() if hasattr(lead, "model_dump") else lead.dict()
            lead_dict["next_action"] = "escalate_agronomist"
            lead_dict["updated_at"] = datetime.utcnow().isoformat() + "Z"
            await leads_repo.upsert_farmer(phone, lead_dict)
        else:
            await whatsapp_client.send_text(phone, AGRONOMIST_NOT_FOUND)

async def handle_callback_time_reply(phone: str, message: ParsedMessage) -> None:
    from app.core.messages_reco import CALLBACK_CONFIRM
    
    lead = await leads_repo.get_farmer(phone)
    if lead:
        lead_dict = lead.model_dump() if hasattr(lead, "model_dump") else lead.dict()
        lead_dict["next_action"] = "callback"
        lead_dict["notes_internal"] = (lead_dict.get("notes_internal") or "") + f" | Preferred callback time: {message.text}"
        lead_dict["updated_at"] = datetime.utcnow().isoformat() + "Z"
        await leads_repo.upsert_farmer(phone, lead_dict)
        
    await whatsapp_client.send_text(phone, CALLBACK_CONFIRM)
    await session_service.reset(phone)

async def handle_farmer_flow_stub(message: ParsedMessage, session: Any) -> None:
    # Farmer flow stub
    await whatsapp_client.send_text(
        message.from_phone,
        f"आप फसल समस्या समाधान फ्लो में आ गए हैं। (Farmer Qualification Flow Stub - Step: {session.current_step})"
    )

async def handle_distributor_new_flow_stub(message: ParsedMessage, session: Any) -> None:
    # New distributor inquiry flow stub
    await whatsapp_client.send_text(
        message.from_phone,
        f"आप नई डिस्ट्रीब्यूटरशिप पूछताछ फ्लो में आ गए हैं। (New Distributor Flow Stub - Step: {session.current_step})"
    )

async def handle_distributor_existing_flow_stub(message: ParsedMessage, session: Any) -> None:
    # Existing distributor support stub
    await whatsapp_client.send_text(
        message.from_phone,
        f"आप वर्तमान डिस्ट्रीब्यूटर सेवा फ्लो में आ गए हैं। (Existing Distributor Flow Stub - Step: {session.current_step})"
    )

async def handle_general_flow_stub(message: ParsedMessage, session: Any) -> None:
    # General info flow stub
    await whatsapp_client.send_text(
        message.from_phone,
        f"आप सामान्य जानकारी फ्लो में आ गए हैं। (General Info Flow Stub - Step: {session.current_step})"
    )

class ConversationRouter:
    async def route_message(self, message: ParsedMessage) -> None:
        phone = message.from_phone
        
        # Conversational AI Agent (brain architecture)
        from app.ai.agent import respond
        try:
            response_text = await respond(phone, message)
            await whatsapp_client.send_text(phone, response_text)
        except Exception as e:
            logger.error("Failed executing Conversational Agent respond", extra={"phone": phone, "error": str(e)})
            await whatsapp_client.send_text(phone, "तकनीकी समस्या आई है 🙏 कृपया थोड़ी देर बाद पुनः प्रयास करें।")
        return

        # Intercept catalog crop selection list replies
        if message.type == "list_reply" and message.list_id and message.list_id.startswith("CATALOG_CROP_"):
            crop_name = message.list_id.replace("CATALOG_CROP_", "")
            from app.services.catalog import catalog_service
            await catalog_service.send_crop_catalog(phone, crop_name)
            await session_service.reset(phone)
            return

        # Intercept catalog keyword
        text_clean = (message.text or "").strip().lower()
        if text_clean in ["catalog", "catalogue", "list", "variety", "varieties", "सूची", "वैरायटी", "उत्पाद", "कैटलॉग"]:
            from app.services.catalog import catalog_service
            await catalog_service.send_crop_menu(phone)
            await session_service.reset(phone)
            return

        # Conversion Tactics: Vernacular Nudge
        import os
        if os.environ.get("ENABLE_VERNACULAR_NUDGE", "false").lower() == "true":
            text = message.text or ""
            has_regional = any(
                (0x0A00 <= ord(c) <= 0x0A7F) or  # Gurmukhi
                (0x0A80 <= ord(c) <= 0x0AFF) or  # Gujarati
                (0x0980 <= ord(c) <= 0x09FF) or  # Bengali
                (0x0C00 <= ord(c) <= 0x0C7F) or  # Telugu
                (0x0B80 <= ord(c) <= 0x0BFF) or  # Tamil
                (0x0C80 <= ord(c) <= 0x0CFF)     # Kannada
                for c in text
            )
            if has_regional:
                logger.info(
                    "Vernacular script detected - flagged for future language expansion",
                    extra={"phone": phone, "message_text": text}
                )
                await session_service.patch_collected(phone, {"vernacular_nudge_flagged": True})

        # Intercept WAIT_CALLBACK_TIME step
        if session.current_step == "WAIT_CALLBACK_TIME":
            await handle_callback_time_reply(phone, message)
            return

        # Intercept recommendation next-action button replies
        if message.type == "button_reply" and message.button_payload in ["ACT_DEALER", "ACT_CALLBACK", "ACT_AGRONOMIST"]:
            await handle_recommendation_button(phone, message.button_payload)
            return

        # 1. Detect and store preferred language on first message
        if not session.preferred_language:
            detected_lang = await session_service.detect_language(message.text or "")
            await sessions_repo.upsert(phone, {"preferred_language": detected_lang})
            session.preferred_language = detected_lang

        # 2. Auto-identify active distributor FIRST
        if not session.current_flow:
            distributor = await distributors_repo.get_active_by_phone(phone)
            if distributor:
                logger.info("Active distributor auto-identified", extra={"phone": phone, "distributor_name": distributor.contact_name})
                await session_service.set_flow(phone, "distributor_existing")
                await session_service.set_step(phone, "ticket_init")
                await sessions_repo.upsert(phone, {"user_type": "distributor_existing"})
                
                # Fetch fresh session row
                session = await session_service.get_or_create(phone)
                greeting = EXISTING_DISTRIBUTOR_GREET.format(name=distributor.contact_name)
                await whatsapp_client.send_text(phone, greeting)
                return

        # 3. Route if already in an active flow
        if session.current_flow:
            if session.current_flow == "farmer_qualification":
                await farmer_flow_handler.handle_message(message, session)
            elif session.current_flow == "distributor_new":
                await distributor_new_flow_handler.handle_message(message, session)
            elif session.current_flow == "distributor_existing":
                await existing_distributor_flow_handler.handle_message(message, session)
            elif session.current_flow == "general":
                await handle_general_flow_stub(message, session)
            return

        # 4. Handle welcome step (no active flow)
        
        # Check if button reply
        if message.type == "button_reply" and message.button_payload:
            payload = message.button_payload
            if payload == "CHOOSE_FARMER":
                await sessions_repo.upsert(phone, {
                    "user_type": "farmer",
                    "current_flow": "farmer_qualification",
                    "current_step": "F_NAME"
                })
                session = await session_service.get_or_create(phone)
                await farmer_flow_handler.handle_message(message, session)
                return
            elif payload == "CHOOSE_DISTRIBUTOR":
                await sessions_repo.upsert(phone, {
                    "user_type": "distributor_new",
                    "current_flow": "distributor_new",
                    "current_step": "D_NAME"
                })
                session = await session_service.get_or_create(phone)
                await distributor_new_flow_handler.handle_message(message, session)
                return
            elif payload == "CHOOSE_GENERAL":
                await sessions_repo.upsert(phone, {
                    "user_type": "general",
                    "current_flow": "general",
                    "current_step": "G_INFO"
                })
                session = await session_service.get_or_create(phone)
                await handle_general_flow_stub(message, session)
                return

        # Handle free text via Intent Classifier
        if message.text:
            text_clean = (message.text or "").strip().lower()
            if text_clean in ["hi", "hello", "hey", "नमस्ते", "start"]:
                await sessions_repo.upsert(phone, {
                    "current_flow": None,
                    "current_step": "start"
                })
                await whatsapp_client.send_buttons(phone, WELCOME_BODY, WELCOME_BUTTONS)
                return

            intent_res = await classify_intent(message.text)
            intent = intent_res.get("intent")
            confidence = intent_res.get("confidence", 0.0)
            
            # Record intent in metrics
            try:
                from app.services.metrics import metrics_service
                metrics_service.record_intent(intent)
            except Exception:
                pass

            
            # Log intent to conversation log in Supabase
            if supabase_client:
                try:
                    supabase_client.table("conversations").update({
                        "ai_intent_detected": intent,
                        "ai_confidence": confidence
                    }).eq("message_id", message.wamid).execute()
                except Exception as e:
                    logger.error("Failed to update intent in conversation log", extra={"error": str(e)})

            if confidence >= 0.55:
                if intent in ["farmer_crop_problem", "farmer_seed_inquiry"]:
                    await sessions_repo.upsert(phone, {
                        "user_type": "farmer",
                        "current_flow": "farmer_qualification",
                        "current_step": "F_NAME"
                    })
                    session = await session_service.get_or_create(phone)
                    await farmer_flow_handler.handle_message(message, session)
                    return
                elif intent == "distributor_new":
                    await sessions_repo.upsert(phone, {
                        "user_type": "distributor_new",
                        "current_flow": "distributor_new",
                        "current_step": "D_NAME"
                    })
                    session = await session_service.get_or_create(phone)
                    await distributor_new_flow_handler.handle_message(message, session)
                    return
                elif intent == "distributor_existing":
                    await sessions_repo.upsert(phone, {
                        "user_type": "distributor_existing",
                        "current_flow": "distributor_existing",
                        "current_step": "ticket_init"
                    })
                    session = await session_service.get_or_create(phone)
                    await existing_distributor_flow_handler.handle_message(message, session)
                    return
                elif intent == "general_inquiry":
                    await sessions_repo.upsert(phone, {
                        "user_type": "general",
                        "current_flow": "general",
                        "current_step": "G_INFO"
                    })
                    session = await session_service.get_or_create(phone)
                    await handle_general_flow_stub(message, session)
                    return

            # Fallback welcome if confidence < 0.55 or intent is spam
            await sessions_repo.upsert(phone, {
                "current_flow": None,
                "current_step": "start"
            })
            await whatsapp_client.send_buttons(phone, FALLBACK_MESSAGE, WELCOME_BUTTONS)
            return

        # Send welcome message if no matches or no text
        await sessions_repo.upsert(phone, {
            "current_flow": None,
            "current_step": "start"
        })
        await whatsapp_client.send_buttons(phone, WELCOME_BODY, WELCOME_BUTTONS)

conversation_router = ConversationRouter()
