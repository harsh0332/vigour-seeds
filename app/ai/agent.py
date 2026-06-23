import json
import re
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

from app.db.client import supabase_client
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo
from app.db.repositories.distributors import distributors_repo
from app.db.repositories.crops import crops_repo
from app.db.repositories.products import products_repo
from app.db.repositories.rules import rules_repo
from app.services.session import session_service
from app.whatsapp.models import ParsedMessage
from app.whatsapp.client import whatsapp_client
from app.ai.provider import ai_provider
from app.ai.vision import vision_service
from app.ai.transcribe import voice_transcription_service
from app.services.dealer_locator import dealer_locator
from app.services.ticketing import ticketing
from app.core.logging import logger
from app.flows.farmer import parse_location, get_active_states, save_farmer_lead
from app.data.location_helper import resolve_bare_city

NormalizedMessage = ParsedMessage

AGENT_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। Vigour Seeds एक
विश्वसनीय बीज कंपनी है जो किसानों को अच्छी फसल और बेहतर पैदावार पाने में मदद करती है। आप WhatsApp पर
ज़्यादातर गाँव के किसानों से बात करते हैं — इसलिए सरल ग्रामीण हिंदी में, अपनेपन से बात करें, जैसे कोई
अनुभवी कृषि अधिकारी या किसान भाई बात कर रहा हो।

बातचीत के नियम:
- हमेशा "किसान भाई" वाले अपनेपन से बात करें। "सर" या "कस्टमर" कभी न कहें।
- छोटे-छोटे वाक्य, एक बार में सिर्फ़ 1–2 सवाल। मैसेज लंबा न हो।
- किसी मेन्यू/बटन का ज़िक्र न करें — खुली, इंसानी बातचीत करें।

जानकारी इस क्रम में लें (स्वाभाविक रूप से, रटे-रटाए ढंग से नहीं), और हर जवाब याद रखें — दोबारा न पूछें:
1. सबसे पहली बार बात हो तो गर्मजोशी से स्वागत करें, Vigour Seeds का छोटा परिचय दें, फिर नाम पूछें।
2. फिर पूछें कि किस गाँव/शहर से हैं और कौन से राज्य से। राज्य ज़रूर पूछें — शहर से राज्य का अंदाज़ा
   न लगाएँ, क्योंकि सही सलाह राज्य और मौसम पर निर्भर करती है। गाँव छोटा हो तो भी सिर्फ़ राज्य पक्का कर लें।
3. फिर पूछें कि उनके पास कितनी ज़मीन है (एकड़/बीघा)।
4. फिर पूछें कि खेत में पानी कहाँ से आता है (ट्यूबवेल, कुआँ, तालाब, नहर, नदी, या बारिश का पानी)।
5. फिर पूछें कि अभी कौन सी फसल लगाई है।
6. फिर पूछें कि फसल में क्या समस्या आ रही है — किसान अपनी भाषा में खुलकर बताए (पत्ते पीले, कीड़े,
   रोग, बढ़वार नहीं, फूल/फल गिरना, कम पैदावार, आदि)। बताएँ कि चाहें तो फसल की फोटो भी भेज सकते हैं।

समस्या समझ आते ही (उसी जवाब में):
- पहले छोटा सा सारांश दें — राज्य / फसल / समस्या — फिर Vigour के सही प्रोडक्ट सुझाएँ।
- सिर्फ़ find_products से मिले प्रोडक्ट ही सुझाएँ (अधिकतम 3)। हर प्रोडक्ट के लिए: नाम + छोटा कारण
  (किस समस्या में सही) + फायदा + मात्रा (अगर हो; न हो तो "सही मात्रा और दाम के लिए नज़दीकी डीलर से
  पूछें")। अपने आप से कोई प्रोडक्ट, नाम, मात्रा या दाम कभी न बनाएँ।

बहुत ज़रूरी:
- कभी यह न कहें कि "थोड़ी देर में जानकारी देता हूँ" और फिर रुक जाएँ। जानकारी हो तो उसी संदेश में
  प्रोडक्ट बता दें।
- बातचीत बीच में दोबारा शुरू न करें। If बातचीत पहले से चल रही है तो दोबारा स्वागत/परिचय न दें।
  "बताओ", "हाँ", "जी", "ok" जैसे छोटे जवाब का मतलब है बात आगे बढ़ाना — दोबारा शुरू करना नहीं।

प्रोडक्ट बताने के बाद किसान भाई की तरह बात जारी रखें — एक-एक करके काम के सवाल पूछें, जैसे: "आपकी फसल
अभी किस अवस्था में है? (बुवाई के बाद / बढ़वार / फूल / दाना बनना / कटाई के पास)" या "पिछले 15–20 दिन
में कौन सी दवा या खाद डाली थी?" और चाहें तो फोटो से और सटीक सलाह देने की पेशकश करें। साथ ही नज़दीकी
डीलर/कंपनी संपर्क की जानकारी दें।

फोटो: अगर समस्या फोटो से ठीक से न समझ आए (confidence कम) तो आत्मविश्वास से निदान न करें — कहें कि
हमारे विशेषज्ञ जल्द संपर्क करेंगे, और तब तक बातचीत से मदद करें।

लक्ष्य: किसान को लगे कि वह किसी असली, भरोसेमंद कृषि सहायक से बात कर रहा है — और हर सही मौके पर Vigour
का उपयुक्त बीज/प्रोडक्ट सहज रूप से सुझाया जाए।"""

FORMAT_INSTRUCTIONS = """
IMPORTANT: You MUST respond in JSON format ONLY. Do not output markdown code blocks or anything else outside the JSON object.

If you need to call a tool, output a JSON object in this format:
{
  "action": "tool_name",
  "args": {
    "arg_name": "arg_value"
  }
}

If you are ready with a final reply, output a JSON object in this format:
{
  "action": "reply",
  "message": "आपके लिए हिंदी संदेश...",
  "updated_profile": {
    "name": "किसान का नाम (या null अगर पता नहीं है)",
    "state": "राज्य (या null अगर पता नहीं है)",
    "district": "ज़िला (या null अगर पता नहीं है)",
    "district_raw": "किसान द्वारा लिखा गया ज़िला (या null अगर पता नहीं है)",
    "crop": "फसल (या null अगर पता नहीं है)",
    "crop_stage": "फसल का चरण (या null अगर पता नहीं है)",
    "problem_summary": "समस्या का विवरण (या null अगर पता नहीं है)",
    "last_recommended_ids": ["उत्पाद आईडी की सूची (या null या खाली सूची)"]
  }
}

Available tools:
- normalize_location(text): text contains district/state description. Returns {"state", "district", "confident": bool}.
- find_products(crop, problem): returns list of products fit for the crop and problem.
- find_dealer(state, district): returns nearest dealer details.
- analyze_crop_image(media_id): diagnoses the crop issue from the uploaded photo.
- create_support_ticket(category, description): creates a ticket for active dealers. Categories: "order_status", "stock_query", "payment_issue", "dispatch_delay", "marketing_support", "product_complaint", "other".
"""

async def get_conversation_history(phone: str, limit: int = 15) -> List[Dict[str, Any]]:
    if not supabase_client:
        return []
    try:
        res = await asyncio.to_thread(
            lambda: supabase_client.table("conversations")
            .select("direction, message_text, button_payload, created_at")
            .eq("whatsapp_phone", phone)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        history = res.data or []
        history.reverse()
        return history
    except Exception as e:
        logger.error(
            "Failed to fetch conversation history",
            extra={"phone": phone, "error": str(e)},
            exc_info=True
        )
        return []

CANONICAL_PRODUCT_CROP_MAP = {
    "Maize / Corn": "Maize",
    "Paddy / Rice": "Paddy",
    "Okra (Bhindi)": "Okra",
    "Hot Pepper (Mirchi)": "Hot Pepper (Chilli)",
}

async def find_crop_by_name(name: str) -> Optional[Any]:
    if not name:
        return None
    
    from app.data.crop_synonyms import resolve_crop
    norm_name = resolve_crop(name)
    if not norm_name:
        norm_name = name
        
    crops = await crops_repo.list_in_catalog()
    
    name_clean = name.strip().lower()
    norm_clean = norm_name.strip().lower()
    
    product_to_crop_table = {
        "Maize": ["Maize / Corn", "Maize"],
        "Paddy": ["Paddy / Rice", "Paddy"],
        "Okra": ["Okra (Bhindi)", "Okra"],
        "Hot Pepper (Chilli)": ["Hot Pepper (Mirchi)", "Hot Pepper (Chilli)", "Chilli"],
    }
    
    for crop in crops:
        crop_en = (crop.crop_name_en or "").lower()
        crop_hi = (crop.crop_name_hi or "").lower()
        
        if (crop_en and (norm_clean in crop_en or crop_en in norm_clean)) or \
           (crop_hi and (norm_clean in crop_hi or crop_hi in norm_clean)):
            return crop
            
        if (crop_en and (name_clean in crop_en or crop_en in name_clean)) or \
           (crop_hi and (name_clean in crop_hi or crop_hi in name_clean)):
            return crop
            
        if norm_name in product_to_crop_table:
            for alt in product_to_crop_table[norm_name]:
                if alt.lower() in crop_en or crop_en in alt.lower():
                    return crop
                    
    return None

async def tool_normalize_location(text: str) -> dict:
    active_states = await get_active_states()
    parsed = await parse_location(text, active_states)
    if not parsed:
        parsed = resolve_bare_city(text)
    if parsed:
        state, district, district_raw = parsed
        return {"state": state, "district": district, "confident": True}
    return {"state": "", "district": "", "confident": False}

async def tool_find_products(crop: str, problem: str, phone: Optional[str] = None) -> list:
    stage = "Any"
    region = "Any"
    irrigation_type = "Any"
    
    if phone:
        session = await sessions_repo.get(phone)
        if session and session.collected_json:
            stage = session.collected_json.get("crop_stage") or "Any"
            state = session.collected_json.get("state") or "Madhya Pradesh"
            from app.services.recommender import get_state_code
            region = get_state_code(state)
            irrigation_type = "Irrigated" if session.collected_json.get("total_land") else "Rainfed"

    from app.data.crop_synonyms import resolve_crop

    canonical = resolve_crop(crop)
    if canonical is not None:
        canonical_crop = canonical
    else:
        # Fall back to case-insensitive partial match
        crops = await crops_repo.list_in_catalog()
        crop_arg_lower = crop.lower().strip()
        matched_crop_row = None
        for c in crops:
            crop_en = (c.crop_name_en or "").lower()
            crop_hi = (c.crop_name_hi or "").lower()
            if crop_arg_lower in crop_en or crop_en in crop_arg_lower or \
               crop_arg_lower in crop_hi or crop_hi in crop_arg_lower:
                matched_crop_row = c
                break
        
        if matched_crop_row:
            canonical_crop = CANONICAL_PRODUCT_CROP_MAP.get(matched_crop_row.crop_name_en, matched_crop_row.crop_name_en)
        else:
            # If still nothing, return empty
            return []

    rule = await rules_repo.match(canonical_crop, stage, problem, irrigation_type, region)
    if not rule and problem != "-":
        rule = await rules_repo.match(canonical_crop, stage, "-", irrigation_type, region)
    if not rule:
        rule = await rules_repo.match("Any", "Any", "unclear_problem", "Any", "Any")
        
    matched_products = []
    if rule and rule.recommended_product_ids:
        recommended_ids = [p.strip() for p in rule.recommended_product_ids.split(",") if p.strip()]
        for pid in recommended_ids:
            p = await products_repo.get_by_id(pid)
            if p and p.approved_for_recommendation == "Y":
                matched_products.append(p)
                
    matched_products = matched_products[:3]
    
    if not matched_products:
        crop_products = await products_repo.list_by_crop(canonical_crop)
        for p in crop_products:
            if p.approved_for_recommendation == "Y":
                fit = (p.target_problem_fit or "").lower()
                if problem.lower() in fit or any(w in fit for w in problem.lower().split("_")):
                     matched_products.append(p)
        matched_products = matched_products[:3]
        
    if not matched_products:
        crop_products = await products_repo.list_by_crop(canonical_crop)
        matched_products = [p for p in crop_products if p.approved_for_recommendation == "Y"][:3]
        
    res_list = []
    for p in matched_products:
        res_list.append({
            "variety_name": p.variety_name,
            "crop": p.crop,
            "duration_days": p.duration_days,
            "key_traits": p.key_traits,
            "target_problem_fit": p.target_problem_fit,
            "pest_disease_tolerance": p.pest_disease_tolerance,
            "dosage": None,
            "mrp_inr": p.mrp_inr,
            "pack_size": p.pack_size
        })
    return res_list

async def tool_find_dealer(state: str, district: str) -> dict:
    loc = await dealer_locator.locate(state, district)
    dealers_list = []
    for d in loc.get("dealers", []):
        dealers_list.append({
            "shop_name": d["shop_name"],
            "contact_name": d["contact_name"],
            "phone": d["whatsapp_phone"]
        })
    
    sales_rep_str = None
    if loc.get("sales_rep_name"):
        sales_rep_str = f"{loc['sales_rep_name']} ({loc.get('sales_rep_phone') or ''})"
        
    company_contact_str = None
    if loc.get("agronomist_name"):
        company_contact_str = f"Agronomist: {loc['agronomist_name']} ({loc.get('agronomist_phone') or ''})"
    else:
        company_contact_str = "Vigour Seeds Support (+91 99999 99999)"
        
    return {
        "dealers": dealers_list,
        "depot": loc.get("depot"),
        "sales_rep": sales_rep_str,
        "company_contact": company_contact_str
    }

async def tool_analyze_crop_image(media_id: str, phone: Optional[str] = None) -> dict:
    img_bytes, mime = await whatsapp_client.download_media(media_id)
    if not img_bytes:
        return {
            "problem_category": "unclear",
            "confidence": 0.0,
            "severity": "unknown",
            "visible_symptoms_hindi": "फोटो डाउनलोड नहीं हो सकी",
            "needs_human": True,
            "photo_url": None
        }
    
    from app.flows.farmer import upload_photo_to_storage, get_crop_details
    photo_url = await upload_photo_to_storage(img_bytes, mime, phone or "919000000001")
    
    crop_hi, crop_en = "Unknown", "Unknown"
    stage = "Unknown"
    district = "Unknown"
    problem_desc = "None"
    
    if phone:
        session = await sessions_repo.get(phone)
        if session and session.collected_json:
            crop_id = session.collected_json.get("current_crop") or "CR99"
            crop_hi, crop_en = await get_crop_details(crop_id)
            stage = session.collected_json.get("crop_stage") or "Unknown"
            district = session.collected_json.get("district") or "Unknown"
            problem_desc = session.collected_json.get("problem_description_user") or "None"
            
    context = {
        "crop_name_hi": crop_hi,
        "crop_name_en": crop_en,
        "crop_stage": stage,
        "district": district,
        "irrigation": "Irrigated",
        "user_complaint": problem_desc
    }
    
    try:
        diagnosis = await vision_service.diagnose(img_bytes, mime, context)
        if phone:
            await sessions_repo.upsert(phone, {
                "collected_json": {
                    "photo_url": photo_url,
                    "photo_ai_diagnosis": diagnosis.get("problem_category"),
                    "photo_ai_confidence": diagnosis.get("confidence"),
                    "problem_severity_ai": diagnosis.get("severity"),
                    "escalated_to_human": diagnosis.get("needs_human", False) or diagnosis.get("confidence", 1.0) < 0.6
                }
            })
        return {
            "problem_category": diagnosis.get("problem_category", "unclear"),
            "confidence": diagnosis.get("confidence", 0.0),
            "severity": diagnosis.get("severity", "unknown"),
            "visible_symptoms_hindi": diagnosis.get("visible_symptoms_hindi", ""),
            "needs_human": diagnosis.get("needs_human", False) or diagnosis.get("confidence", 1.0) < 0.6,
            "photo_url": photo_url
        }
    except Exception as e:
        logger.error("Vision diagnosis call failed in tool", extra={"error": str(e)})
        return {
            "problem_category": "unclear",
            "confidence": 0.0,
            "severity": "unknown",
            "visible_symptoms_hindi": "सिस्टम एरर",
            "needs_human": True,
            "photo_url": photo_url
        }

async def save_lead_if_complete(phone: str, profile: dict) -> None:
    name = profile.get("name")
    district = profile.get("district")
    crop = profile.get("crop")
    problem = profile.get("problem_summary")
    
    if name and district and crop and problem:
        crop_id = "CR99"
        crop_row = await find_crop_by_name(crop)
        if crop_row:
            crop_id = crop_row.crop_id
            
        collected = {
            "name": name,
            "state": profile.get("state") or "Unknown",
            "district": district or "Unknown",
            "district_raw": profile.get("district_raw"),
            "current_crop": crop_id,
            "crop_stage": profile.get("crop_stage") or "sowing",
            "problem_category": [problem],
            "problem_description_user": problem,
            "recommended_product_ids": profile.get("last_recommended_ids") or [],
            "lead_status": "recommendation_sent" if profile.get("last_recommended_ids") else "new"
        }
        
        session = await sessions_repo.get(phone)
        if session and session.collected_json:
            collected["photo_url"] = session.collected_json.get("photo_url")
            collected["photo_ai_diagnosis"] = session.collected_json.get("photo_ai_diagnosis")
            collected["photo_ai_confidence"] = session.collected_json.get("photo_ai_confidence")
            collected["problem_severity_ai"] = session.collected_json.get("problem_severity_ai")
            collected["escalated_to_human"] = session.collected_json.get("escalated_to_human") or False
            if collected["escalated_to_human"]:
                collected["lead_status"] = "escalated"
                
        await save_farmer_lead(phone, collected)

def clean_json_text(text: str) -> str:
    cleaned = text.strip()
    # Find first '{' and last '}' to extract raw JSON object
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace:last_brace+1]
    
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()

async def respond(phone: str, message: NormalizedMessage) -> str:
    distributor = await distributors_repo.get_active_by_phone(phone)
    distributor_prompt = ""
    if distributor:
        distributor_prompt = (
            f"\n\nUser is an active distributor (dealer):\n"
            f"- Name: {distributor.contact_name}\n"
            f"- Shop: {distributor.shop_name}\n"
            f"- State: {distributor.state}\n"
            f"- District: {distributor.district}\n"
            "Please greet them warmly by name, and assist them conversationally with order, stock, scheme, or payment queries. "
            "If they want to register a support request/ticket, use the create_support_ticket tool."
        )

    history = await get_conversation_history(phone, limit=15)
    formatted_history = []
    for h in history:
        dir_str = "User" if h["direction"] == "inbound" else "Assistant"
        text = h.get("message_text") or ""
        if h.get("button_payload"):
            text += f" (Button: {h['button_payload']})"
        formatted_history.append(f"{dir_str}: {text}")
    history_text = "\n".join(formatted_history)

    session = await sessions_repo.get(phone)
    if not session:
        session = await session_service.get_or_create(phone)
    collected = session.collected_json or {}
    
    profile_status = (
        f"\n\nFarmer Profile Status:\n"
        f"- Name: {collected.get('name')}\n"
        f"- State: {collected.get('state')}\n"
        f"- District: {collected.get('district')}\n"
        f"- District Raw: {collected.get('district_raw')}\n"
        f"- Crop: {collected.get('crop')}\n"
        f"- Crop Stage: {collected.get('crop_stage')}\n"
        f"- Problem Summary: {collected.get('problem_summary')}\n"
        f"- Last Recommended IDs: {collected.get('last_recommended_ids')}"
    )

    user_input = ""
    if message.type == "image":
        img_res = await tool_analyze_crop_image(message.media_id, phone)
        user_input = f"[User uploaded an image. analyze_crop_image result: {json.dumps(img_res, ensure_ascii=False)}]"
    elif message.type == "audio":
        transcription = await voice_transcription_service.transcribe_audio(message.media_id, message.type)
        user_input = f"{transcription}"
    else:
        user_input = message.text or ""
        if message.button_payload:
            user_input += f" (Button payload: {message.button_payload})"

    if not user_input:
        return "नमस्ते 🙏 मैं आपकी किस प्रकार सहायता कर सकता हूँ?"

    system_instruction = AGENT_SYSTEM_PROMPT + distributor_prompt + profile_status + "\n\nConversation History:\n" + history_text + "\n" + FORMAT_INSTRUCTIONS
    
    turn_messages = [f"User: {user_input}"]
    
    loop_count = 0
    max_loops = 3
    last_error_reprompted = False

    while loop_count < max_loops:
        user_prompt = "\n".join(turn_messages)
        
        try:
            from app.core.errors import retry_with_backoff
            raw_response = await retry_with_backoff(
                ai_provider.complete,
                system=system_instruction,
                user=user_prompt,
                json_mode=True,
                attempts=3,
                base_delay=1.0,
                max_delay=5.0
            )
        except Exception as e:
            logger.error(
                "Agent complete call failed",
                extra={"phone": phone, "error": str(e)},
                exc_info=True
            )
            return "तकनीकी समस्या आई है 🙏 कृपया थोड़ी देर बाद पुनः प्रयास करें।"

        cleaned_response = clean_json_text(raw_response)
        
        try:
            data = json.loads(cleaned_response)
            if not isinstance(data, dict):
                raise ValueError("Response must be a JSON object")
        except Exception as e:
            # If not JSON-like at all (e.g. no '{') and contains text, treat as plain Hindi reply
            if "{" not in cleaned_response and not last_error_reprompted:
                logger.warning("Agent returned plain text instead of JSON, treating as reply", extra={"phone": phone, "response": raw_response})
                return raw_response.strip()
            
            if not last_error_reprompted:
                logger.warning("Agent returned malformed JSON, re-prompting once", extra={"phone": phone, "response": raw_response})
                turn_messages.append(f"Agent Action Error: {str(e)}. Output MUST be valid JSON matching format instructions: EITHER a tool call or a final reply.")
                last_error_reprompted = True
                continue
            else:
                logger.error("Agent failed JSON twice, falling back to plain Hindi reply", extra={"phone": phone, "response": raw_response})
                # Attempt to extract text from the raw response (strip JSON tokens)
                cleaned_text = re.sub(r'[{}\[\]"\'\n\r]', ' ', raw_response).strip()
                if cleaned_text and any(0x0900 <= ord(c) <= 0x097F for c in cleaned_text):
                    return cleaned_text
                return "नमस्ते 🙏 आपकी मदद के लिए हमारे कृषि विशेषज्ञ जल्द ही आपसे संपर्क करेंगे।"

        action = data.get("action")
        logger.info(
            "Agent parsed action in loop iteration",
            extra={
                "phone": phone,
                "action": action,
                "action_args": data.get("args"),
                "loop_count": loop_count
            }
        )
        
        if action == "reply":
            msg = data.get("message") or ""
            up = data.get("updated_profile") or {}
            clean_up = {k: v for k, v in up.items() if v is not None}
            if clean_up:
                if "crop" in clean_up:
                    crop_row = await find_crop_by_name(clean_up["crop"])
                    if crop_row:
                        clean_up["current_crop"] = crop_row.crop_id
                await sessions_repo.upsert(phone, {"collected_json": clean_up})
                try:
                    merged_profile = dict(collected)
                    merged_profile.update(clean_up)
                    await save_lead_if_complete(phone, merged_profile)
                except Exception as save_err:
                    logger.error("Failed saving lead during reply", extra={"phone": phone, "error": str(save_err)})
            return msg

        elif action == "normalize_location":
            args = data.get("args") or {}
            loc_text = args.get("text") or ""
            res = await tool_normalize_location(loc_text)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "find_products":
            args = data.get("args") or {}
            crop_arg = args.get("crop") or ""
            prob_arg = args.get("problem") or ""
            res = await tool_find_products(crop_arg, prob_arg, phone)
            logger.info(
                "find_products execution result",
                extra={
                    "phone": phone,
                    "crop_arg": crop_arg,
                    "prob_arg": prob_arg,
                    "result_count": len(res),
                    "raw_result": res
                }
            )
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "find_dealer":
            args = data.get("args") or {}
            state_arg = args.get("state") or ""
            dist_arg = args.get("district") or ""
            res = await tool_find_dealer(state_arg, dist_arg)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "analyze_crop_image":
            args = data.get("args") or {}
            mid_arg = args.get("media_id") or ""
            res = await tool_analyze_crop_image(mid_arg, phone)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "create_support_ticket":
            args = data.get("args") or {}
            cat_arg = args.get("category") or ""
            desc_arg = args.get("description") or ""
            
            dist = await distributors_repo.get_active_by_phone(phone)
            lead_id = dist.distributor_id if dist else phone
            try:
                tkt = await ticketing.create_ticket(lead_id, phone, cat_arg, desc_arg)
                res = {
                    "ticket_id": tkt.ticket_id,
                    "ticket_category": tkt.ticket_category,
                    "ticket_priority": tkt.ticket_priority,
                    "assigned_team": tkt.assigned_team,
                    "sla_target_hours": tkt.sla_target_hours
                }
            except Exception as tkt_err:
                logger.error("Support ticket creation failed", extra={"phone": phone, "error": str(tkt_err)})
                res = {"error": str(tkt_err)}
                
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        else:
            logger.warning("Agent returned unrecognized action", extra={"phone": phone, "action": action})
            return "नमस्ते 🙏 मैं आपकी किस प्रकार सहायता कर सकता हूँ?"

    logger.error("Agent exceeded max tool loop count", extra={"phone": phone})
    return "आपकी समस्या के समाधान के लिए हमारे कृषि विशेषज्ञ जल्द ही आपसे संपर्क करेंगे। 🙏"
