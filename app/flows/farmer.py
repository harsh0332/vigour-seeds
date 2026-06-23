import re
import uuid
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from app.data.location_helper import resolve_bare_city
from app.db.client import supabase_client
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo
from app.services.session import session_service
from app.whatsapp.client import whatsapp_client
from app.whatsapp.models import ParsedMessage
from app.ai.vision import vision_service
from app.core.logging import logger
from app.services.recommender import recommender
from app.core.messages_farmer import (
    Q1_NAME, Q2_LOCATION, Q2_INVALID, Q3_LAND, Q3_INVALID,
    Q4_CROP_BODY, Q5_STAGE_BODY, Q6_HELP_BODY, Q7_PROBLEM_BODY,
    PHOTO_ASK, ESCALATION_MESSAGE
)

STATE_HINDI_MAP = {
    "मध्य प्रदेश": "Madhya Pradesh",
    "मध्यप्रदेश": "Madhya Pradesh",
    "महाराष्ट्र": "Maharashtra",
    "राजस्थान": "Rajasthan",
    "गुजरात": "Gujarat",
    "उत्तर प्रदेश": "Uttar Pradesh",
    "उत्तरप्रदेश": "Uttar Pradesh",
    "छत्तीसगढ़": "Chhattisgarh",
    "छत्तीसगढ": "Chhattisgarh",
    "कर्नाटक": "Karnataka",
    "आंध्र प्रदेश": "Andhra Pradesh",
    "आंध्रप्रदेश": "Andhra Pradesh",
    "तेलंगाना": "Telangana",
    "बिहार": "Bihar",
    "ओडिशा": "Odisha",
    "उड़ीसा": "Odisha",
    "पंजाब": "Punjab",
    "हरियाणा": "Haryana",
    "तमिलनाडु": "Tamil Nadu",
    "पश्चिम बंगाल": "West Bengal",
    "पश्चिमबंगाल": "West Bengal"
}

DISTRICT_HINDI_MAP = {
    # MP
    "उज्जैन": "Ujjain",
    "इंदौर": "Indore",
    "भोपाल": "Bhopal",
    "गुना": "Guna",
    "देवास": "Dewas",
    "सीहोर": "Sehore",
    "अशोकनगर": "Ashoknagar",
    "अशोक नगर": "Ashoknagar",
    "विदिशा": "Vidisha",
    # MH
    "नाशिक": "Nashik",
    "नासिक": "Nashik",
    "पुणे": "Pune",
    "औरंगाबाद": "Aurangabad",
    "नागपुर": "Nagpur",
    "अकोला": "Akola",
    "यवतमाल": "Yavatmal",
    # RJ
    "जयपुर": "Jaipur",
    "कोटा": "Kota",
    "उदयपुर": "Udaipur",
    "भीलवाड़ा": "Bhilwara",
    "श्रीगंगानगर": "Sri Ganganagar",
    "श्री गंगानगर": "Sri Ganganagar",
    "हनुमानगढ़": "Hanumangarh",
    # GJ
    "अहमदाबाद": "Ahmedabad",
    "राजकोट": "Rajkot",
    "जूनागढ़": "Junagadh",
    "मेहसाणा": "Mehsana",
    "मेहसाना": "Mehsana",
    "बनासकांठा": "Banaskantha",
    "बनास काँठा": "Banaskantha",
}

async def parse_location(text: str, active_states: list) -> Optional[Tuple[str, str, str]]:
    cleaned = text.lower().strip()
    
    # Match Hindi state names first
    matched_state = None
    matched_state_key = None
    for hindi_state, eng_state in STATE_HINDI_MAP.items():
        if hindi_state in cleaned:
            matched_state = eng_state
            matched_state_key = hindi_state
            break
            
    if not matched_state:
        # Match English state names or codes
        for state in active_states:
            state_norm = state["state"].lower().replace(" ", "")
            state_code_norm = state["state_code"].lower().strip()
            text_norm = cleaned.replace(" ", "")
            
            if state_code_norm in text_norm:
                matched_state = state["state"]
                matched_state_key = state["state_code"]
                break
            elif state_norm in text_norm:
                matched_state = state["state"]
                matched_state_key = state["state"]
                break
                
    if not matched_state:
        # Fallback to bare city check
        bare_city_res = resolve_bare_city(text)
        if bare_city_res:
            return bare_city_res
            
        # Fallback split check
        parts = cleaned.split(",")
        if len(parts) >= 2:
            return None # Must validate against regions list
        return None
        
    # Extract district by removing matched state key
    pattern = re.compile(re.escape(matched_state_key), re.IGNORECASE)
    district_part = pattern.sub("", cleaned)
    district_part = re.sub(r"[,\-\s\(\)]+", " ", district_part).strip()
    
    if not district_part:
        district_part = "Unknown"
        
    # Extract raw district from original text
    district_raw_extracted = pattern.sub("", text)
    district_raw_extracted = re.sub(r"[,\-\s\(\)]+", " ", district_raw_extracted).strip()
    if not district_raw_extracted:
        district_raw_extracted = "Unknown"
        
    district_raw = district_raw_extracted
    district_normalized = district_part
    
    # Try mapping
    lookup_key = re.sub(r"\s+", "", district_part).lower()
    
    mapped_english = None
    for k, v in DISTRICT_HINDI_MAP.items():
        if re.sub(r"\s+", "", k).lower() == lookup_key or re.sub(r"\s+", "", v).lower() == lookup_key:
            mapped_english = v
            break
            
    if mapped_english:
        district_normalized = mapped_english
    else:
        # Check Devanagari
        if bool(re.search(r"[\u0900-\u097F]", district_part)):
            try:
                from app.ai.provider import ai_provider
                system_prompt = (
                    "You are a transliteration and location normalization assistant. "
                    "Convert the given Indian district name in Devanagari/Hindi script to standard English spelling "
                    "(e.g., उज्जैन -> Ujjain, भोपाल -> Bhopal, नाशिक -> Nashik). "
                    "Return ONLY the single English district name, with no punctuation or extra words."
                )
                res = await ai_provider.complete(system_prompt, district_part)
                res_clean = res.strip().replace(".", "").replace('"', "").replace("'", "")
                if res_clean and "mock" not in res_clean.lower() and "response" not in res_clean.lower():
                    district_normalized = res_clean.title()
            except Exception as e:
                logger.error("Failed to transliterate district name using AI", extra={"error": str(e)})

    return matched_state, district_normalized.title(), district_raw

def parse_land(text: str) -> Optional[float]:
    match = re.search(r"(\d+(\.\d+)?)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

async def get_active_states() -> list:
    if not supabase_client:
        return []
    try:
        res = await asyncio.to_thread(
            lambda: supabase_client.table("regions").select("state, state_code").eq("is_active", "Y").execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("Failed to fetch active states from DB", extra={"error": str(e)})
        return []

async def get_crop_list() -> list:
    if not supabase_client:
        return []
    try:
        res = await asyncio.to_thread(
            lambda: supabase_client.table("crops").select("crop_id, crop_name_hi, crop_name_en").eq("in_catalog", "Y").limit(9).execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("Failed to fetch crops from DB", extra={"error": str(e)})
        return []

async def get_crop_details(crop_id: str) -> Tuple[str, str]:
    if crop_id == "CR99":
        return "अन्य फसल", "Other crop"
    if not supabase_client:
        return "Unknown", "Unknown"
    try:
        res = await asyncio.to_thread(
            lambda: supabase_client.table("crops").select("crop_name_hi, crop_name_en").eq("crop_id", crop_id).execute()
        )
        if res.data:
            return res.data[0].get("crop_name_hi", "Unknown"), res.data[0].get("crop_name_en", "Unknown")
    except Exception as e:
        logger.error("Failed to fetch crop details", extra={"crop_id": crop_id, "error": str(e)})
    return "Unknown", "Unknown"

async def send_crop_list(phone: str) -> None:
    crops = await get_crop_list()
    rows = []
    for crop in crops:
        rows.append({
            "id": crop["crop_id"],
            "title": crop["crop_name_hi"],
            "description": crop["crop_name_en"]
        })
    rows.append({
        "id": "CR99",
        "title": "अन्य फसल",
        "description": "Other crop"
    })
    
    sections = [{
        "title": "फसलें",
        "rows": rows,
        "button_label": "फसल चुनें"
    }]
    await whatsapp_client.send_list(phone, None, Q4_CROP_BODY, sections)

async def upload_photo_to_storage(img_bytes: bytes, mime_type: str, phone: str) -> Optional[str]:
    if not supabase_client:
        return None
    try:
        ext = "jpg"
        if "png" in mime_type:
            ext = "png"
        elif "gif" in mime_type:
            ext = "gif"
        elif "webp" in mime_type:
            ext = "webp"
            
        filename = f"{phone}_{uuid.uuid4().hex}.{ext}"
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: supabase_client.storage.from_("crop-photos").upload(
                path=filename,
                file=img_bytes,
                file_options={"content-type": mime_type}
            )
        )
        
        url = supabase_client.storage.from_("crop-photos").get_public_url(filename)
        return url
    except Exception as e:
        logger.error("Failed uploading photo to Supabase storage", extra={"error": str(e)})
        return None

async def save_farmer_lead(phone: str, collected: dict) -> None:
    fields = {
        "name": collected.get("name", "Unknown"),
        "state": collected.get("state", "Unknown"),
        "district": collected.get("district", "Unknown"),
        "total_land": collected.get("total_land"),
        "land_unit": collected.get("land_unit", "acre"),
        "current_crop": collected.get("current_crop"),
        "crop_stage": collected.get("crop_stage"),
        "help_needed_for": collected.get("help_needed_for", "both"),
        "problem_category": collected.get("problem_category", []),
        "problem_description_user": collected.get("problem_description_user"),
        "photo_url": collected.get("photo_url"),
        "photo_ai_diagnosis": collected.get("photo_ai_diagnosis"),
        "photo_ai_confidence": collected.get("photo_ai_confidence"),
        "problem_severity_ai": collected.get("problem_severity_ai"),
        "lead_status": collected.get("lead_status", "new"),
        "escalated_to_human": collected.get("escalated_to_human", False),
        "next_action": collected.get("next_action"),
        "source_channel": collected.get("source_channel", "whatsapp_organic"),
        "utm_campaign": collected.get("utm_campaign"),
        "notes_internal": collected.get("notes_internal") or (f"District Raw: {collected.get('district_raw')}" if collected.get("district_raw") else None),
        "last_message_at": datetime.utcnow().isoformat()
    }
    
    try:
        await leads_repo.upsert_farmer(phone, fields)
        logger.info("Farmer lead successfully saved/updated in database", extra={"phone": phone, "status": fields["lead_status"]})
    except Exception as e:
        logger.error("Failed to upsert farmer lead to database", extra={"phone": phone, "error": str(e)})

async def get_recommendation_stub(phone: str) -> str:
    return "reco pending"

async def proceed_to_recommender(phone: str, collected: dict) -> None:
    await recommender.resolve(phone, collected)

async def complete_qualification(phone: str, collected: dict) -> None:
    collected["lead_status"] = "qualified"
    try:
        from app.services.metrics import metrics_service
        metrics_service.increment_farmer_qualified()
    except Exception:
        pass
    await save_farmer_lead(phone, collected)
    await proceed_to_recommender(phone, collected)

async def handle_photo_upload_and_diagnosis(phone: str, media_id: str, collected: dict) -> None:
    # Check if bucket exists
    if supabase_client:
        try:
            buckets = await asyncio.to_thread(supabase_client.storage.list_buckets)
            bucket_names = [b.name for b in buckets]
            if "crop-photos" not in bucket_names:
                logger.error("Supabase Storage bucket 'crop-photos' does not exist! Please create it.")
                await whatsapp_client.send_text(phone, "सिस्टम त्रुटि: फोटो अपलोड बकेट नहीं मिला। कृपया एडमिन से संपर्क करें।")
                return
        except Exception as bucket_err:
            logger.warning("Failed to list buckets during verification", extra={"error": str(bucket_err)})
            
    img_bytes, mime = await whatsapp_client.download_media(media_id)
    if not img_bytes:
        await whatsapp_client.send_text(phone, "फोटो डाउनलोड नहीं की जा सकी। कृपया दोबारा प्रयास करें या 'स्किप' लिखें:")
        return
        
    photo_url = await upload_photo_to_storage(img_bytes, mime, phone)
    if not photo_url:
        await whatsapp_client.send_text(phone, "फोटो अपलोड नहीं की जा सकी। कृपया दोबारा प्रयास करें या 'स्किप' लिखें:")
        return
        
    crop_hi, crop_en = await get_crop_details(collected.get("current_crop", "CR99"))
    
    context = {
        "crop_name_hi": crop_hi,
        "crop_name_en": crop_en,
        "crop_stage": collected.get("crop_stage", "Unknown"),
        "district": collected.get("district", "Unknown"),
        "irrigation": "Irrigated",
        "user_complaint": collected.get("problem_description_user", "None")
    }
    
    try:
        diagnosis = await vision_service.diagnose(img_bytes, mime, context)
    except Exception as e:
        logger.error("Vision diagnosis raised exception, degrading gracefully", extra={"error": str(e)})
        diagnosis = {
            "problem_category": "unclear",
            "confidence": 0.0,
            "severity": "unknown"
        }
    
    photo_ai_diagnosis = diagnosis.get("problem_category", "unclear")
    photo_ai_confidence = float(diagnosis.get("confidence", 0.0))
    problem_severity_ai = diagnosis.get("severity", "unknown")
    
    collected["photo_url"] = photo_url
    collected["photo_ai_diagnosis"] = photo_ai_diagnosis
    collected["photo_ai_confidence"] = photo_ai_confidence
    collected["problem_severity_ai"] = problem_severity_ai
    
    prob_cat = list(set(collected.get("problem_category", []) + [photo_ai_diagnosis]))
    collected["problem_category"] = prob_cat
    
    if photo_ai_confidence < 0.6:
        collected["escalated_to_human"] = True
        collected["next_action"] = "escalate_agronomist"
        collected["lead_status"] = "escalated"
        
        try:
            from app.services.metrics import metrics_service
            metrics_service.increment_escalations()
        except Exception:
            pass
            
        await save_farmer_lead(phone, collected)
        await whatsapp_client.send_text(phone, ESCALATION_MESSAGE)
    else:
        collected["lead_status"] = "qualified"
        
        try:
            from app.services.metrics import metrics_service
            metrics_service.increment_farmer_qualified()
        except Exception:
            pass
            
        await save_farmer_lead(phone, collected)
        await proceed_to_recommender(phone, collected)


class FarmerFlowHandler:
    async def handle_message(self, message: ParsedMessage, session: Any) -> None:
        phone = message.from_phone
        collected = session.collected_json or {}
        step = session.current_step
        
        if step == "F_NAME":
            if not collected.get("name_asked"):
                collected["name_asked"] = True
                await session_service.patch_collected(phone, {"name_asked": True})
                await whatsapp_client.send_text(phone, Q1_NAME)
                return
            else:
                name = message.text or ""
                if not name.strip():
                    await whatsapp_client.send_text(phone, Q1_NAME)
                    return
                collected["name"] = name.strip()
                collected.pop("name_asked", None)
                await session_service.patch_collected(phone, {"name": name.strip(), "name_asked": None})
                
                await session_service.set_step(phone, "F_LOCATION")
                await whatsapp_client.send_text(phone, Q2_LOCATION)
                return
                
        elif step == "F_LOCATION":
            active_states = await get_active_states()
            parsed = await parse_location(message.text or "", active_states)
            if not parsed:
                await whatsapp_client.send_text(phone, Q2_INVALID)
                return
                
            state, district, district_raw = parsed
            collected["state"] = state
            collected["district"] = district
            collected["district_raw"] = district_raw
            await session_service.patch_collected(phone, {
                "state": state,
                "district": district,
                "district_raw": district_raw
            })
            
            await session_service.set_step(phone, "F_LAND")
            await whatsapp_client.send_text(phone, Q3_LAND)
            return
            
        elif step == "F_LAND":
            val = parse_land(message.text or "")
            if val is None:
                await whatsapp_client.send_text(phone, Q3_INVALID)
                return
                
            collected["total_land"] = val
            collected["land_unit"] = "acre"
            await session_service.patch_collected(phone, {"total_land": val, "land_unit": "acre"})
            
            await session_service.set_step(phone, "F_CROP")
            await send_crop_list(phone)
            return
            
        elif step == "F_CROP":
            crop_id = None
            if message.type == "list_reply" and message.list_id:
                crop_id = message.list_id
            elif message.type == "button_reply" and message.button_payload:
                crop_id = message.button_payload
            else:
                text = (message.text or "").strip().lower()
                crops = await get_crop_list()
                for crop in crops:
                    if text in crop["crop_name_hi"].lower() or text in crop["crop_name_en"].lower():
                        crop_id = crop["crop_id"]
                        break
                if not crop_id:
                    crop_id = "CR99"
                    
            collected["current_crop"] = crop_id
            await session_service.patch_collected(phone, {"current_crop": crop_id})
            
            await session_service.set_step(phone, "F_STAGE")
            buttons = [
                {"id": "sowing", "title": "बुवाई/छोटा पौधा"},
                {"id": "vegetative", "title": "बढ़वार"},
                {"id": "flowering", "title": "फूल/फल"}
            ]
            await whatsapp_client.send_buttons(phone, Q5_STAGE_BODY, buttons)
            return
            
        elif step == "F_STAGE":
            stage = None
            if message.type == "button_reply" and message.button_payload:
                stage = message.button_payload
            else:
                text = (message.text or "").lower()
                if "बुवाई" in text or "छोटा" in text or "sowing" in text:
                    stage = "sowing"
                elif "फूल" in text or "फल" in text or "flowering" in text:
                    stage = "flowering"
                else:
                    stage = "vegetative"
                    
            collected["crop_stage"] = stage
            await session_service.patch_collected(phone, {"crop_stage": stage})
            
            await session_service.set_step(phone, "F_HELP_FOR")
            buttons = [
                {"id": "current_crop", "title": "अभी की फसल"},
                {"id": "next_sowing", "title": "अगली बुवाई"},
                {"id": "both", "title": "दोनों"}
            ]
            await whatsapp_client.send_buttons(phone, Q6_HELP_BODY, buttons)
            return
            
        elif step == "F_HELP_FOR":
            help_for = None
            if message.type == "button_reply" and message.button_payload:
                help_for = message.button_payload
            else:
                text = (message.text or "").lower()
                if "अगली" in text or "sowing" in text or "next" in text:
                    help_for = "next_sowing"
                elif "अभी" in text or "current" in text:
                    help_for = "current_crop"
                else:
                    help_for = "both"
                    
            collected["help_needed_for"] = help_for
            await session_service.patch_collected(phone, {"help_needed_for": help_for})
            
            if help_for == "next_sowing":
                await complete_qualification(phone, collected)
                await session_service.reset(phone)
                return
            else:
                await session_service.set_step(phone, "F_PROBLEM")
                sections = [{
                    "title": "समस्याएं",
                    "rows": [
                        {"id": "pest_attack", "title": "कीड़े/इल्ली", "description": "Pest attack / caterpillars"},
                        {"id": "yellow_leaves", "title": "पत्ते पीले", "description": "Yellowing leaves"},
                        {"id": "low_growth", "title": "कम बढ़वार", "description": "Slow growth or stunting"},
                        {"id": "fungal_disease", "title": "बीमारी/फफूंद", "description": "Fungal/bacterial disease symptoms"},
                        {"id": "unclear", "title": "और कुछ", "description": "Other issues"}
                    ],
                    "button_label": "समस्या चुनें"
                }]
                await whatsapp_client.send_list(phone, None, Q7_PROBLEM_BODY, sections)
                return
                
        elif step == "F_PROBLEM":
            prob_cat = None
            desc = None
            
            if message.type == "list_reply" and message.list_id:
                prob_cat = [message.list_id]
            elif message.type == "button_reply" and message.button_payload:
                prob_cat = [message.button_payload]
            else:
                prob_cat = ["unclear"]
                desc = message.text
                
            collected["problem_category"] = prob_cat
            if desc:
                collected["problem_description_user"] = desc
                await session_service.patch_collected(phone, {"problem_category": prob_cat, "problem_description_user": desc})
            else:
                await session_service.patch_collected(phone, {"problem_category": prob_cat})
                
            await session_service.set_step(phone, "F_PHOTO")
            await whatsapp_client.send_text(phone, PHOTO_ASK)
            return
            
        elif step == "F_PHOTO":
            if message.type == "image" and message.media_id:
                await handle_photo_upload_and_diagnosis(phone, message.media_id, collected)
                await session_service.reset(phone)
                return
            else:
                text = (message.text or "").strip().lower()
                if text in ["skip", "स्किप", "no", "नहीं", "nhi"]:
                    await complete_qualification(phone, collected)
                else:
                    collected["problem_description_user"] = (collected.get("problem_description_user") or "") + f" | Extra info: {message.text}"
                    await complete_qualification(phone, collected)
                await session_service.reset(phone)
                return

farmer_flow_handler = FarmerFlowHandler()
