import re
from typing import Dict, Any, Optional, Tuple
from app.db.repositories.leads import leads_repo
from app.services.session import session_service
from app.services.lead_scoring import lead_scoring
from app.services.notify import notify
from app.whatsapp.client import whatsapp_client
from app.whatsapp.models import ParsedMessage
from app.core.logging import logger
from app.core.messages_distributor import (
    Q1_DIST_NAME, Q2_DIST_LOCATION, Q2_DIST_INVALID,
    Q3_DIST_BRANDS, Q4_DIST_SALES, Q4_DIST_INVALID,
    Q5_DIST_WAREHOUSE, Q5_DIST_INVALID, Q6_DIST_YEARS, Q6_DIST_INVALID,
    Q7_DIST_SEGMENTS, DIST_QUALIFIED_REPLY
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

def parse_name(text: str) -> Tuple[str, str]:
    text = text.strip()
    # Check for split by comma, hyphen, "और", "and"
    for sep in [",", " और ", " and ", " - ", "-"]:
        if sep in text:
            parts = text.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
            
    # Fallback: first word is contact, rest is shop name
    parts = text.split(None, 1)
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return text, text

def parse_location(text: str) -> Optional[Tuple[str, str, str, str]]:
    cleaned = text.strip()
    
    # 1. Extract Pincode (6 digits)
    pincode_match = re.search(r"\b\d{6}\b", cleaned)
    pincode = pincode_match.group(0) if pincode_match else "452001"
    if pincode_match:
        cleaned = cleaned.replace(pincode, "")
        
    # 2. Extract State
    matched_state = "Madhya Pradesh"  # default fallback
    for hi_state, eng_state in STATE_HINDI_MAP.items():
        if hi_state in cleaned:
            matched_state = eng_state
            cleaned = cleaned.replace(hi_state, "")
            break
            
    # Check common English abbreviations
    for code, full_name in [("MP", "Madhya Pradesh"), ("MH", "Maharashtra"), ("RJ", "Rajasthan"), ("UP", "Uttar Pradesh")]:
        if re.search(rf"\b{code}\b", cleaned, re.IGNORECASE):
            matched_state = full_name
            cleaned = re.sub(rf"\b{code}\b", "", cleaned, flags=re.IGNORECASE)
            break
            
    # 3. District & City
    cleaned_parts = [p.strip() for p in re.split(r"[,\s\-]+", cleaned) if p.strip()]
    if len(cleaned_parts) >= 2:
        city = cleaned_parts[0]
        district = cleaned_parts[1]
    elif len(cleaned_parts) == 1:
        city = cleaned_parts[0]
        district = cleaned_parts[0]
    else:
        city = "Indore"
        district = "Indore"
        
    return city.title(), district.title(), matched_state, pincode

def parse_brands(text: str) -> list:
    text_lower = text.strip().lower()
    if text_lower in ["none", "कोई नहीं", "nhi", "no", "nil", ""]:
        return []
    # Split by commas
    parts = [b.strip() for b in text.split(",") if b.strip()]
    return parts

def parse_sales(text: str) -> Optional[Tuple[float, float]]:
    text_lower = text.lower()
    numbers = re.findall(r"(\d+(?:\.\d+)?)", text_lower)
    if not numbers:
        return None
        
    # Check if first number is expressed in Lakhs (laakh, lakh, l, लाख)
    is_lakh = "lakh" in text_lower or "laakh" in text_lower or "लाख" in text_lower or re.search(r"\b\d+l\b", text_lower)
    
    first_val = float(numbers[0])
    if is_lakh:
        first_val *= 100000
        
    sales_volume = first_val
    radius = 10.0
    if len(numbers) >= 2:
        radius = float(numbers[1])
        
    return sales_volume, radius

def parse_warehouse(text: str) -> Optional[Tuple[float, bool, float, int]]:
    text_lower = text.lower()
    numbers = re.findall(r"(\d+(?:\.\d+)?)", text_lower)
    if not numbers:
        return None
        
    # Check warehouse availability
    warehouse_avail = True
    if "no" in text_lower or "नहीं" in text_lower or "nahi" in text_lower or "n" in text_lower:
        # verify "yes" is not also in it
        if "yes" not in text_lower and "हाँ" not in text_lower and "ha" not in text_lower:
            warehouse_avail = False
            
    shop_size = float(numbers[0])
    wh_size = 0.0
    staff = 1
    
    # If warehouse is available
    if warehouse_avail:
        if len(numbers) >= 3:
            wh_size = float(numbers[1])
            staff = int(float(numbers[2]))
        elif len(numbers) == 2:
            second_num = float(numbers[1])
            # heuristics: if second number is >= 100, it's likely warehouse size, staff defaults to 1
            if second_num >= 100:
                wh_size = second_num
                staff = 1
            else:
                wh_size = 0.0
                staff = int(second_num)
    else:
        # Warehouse not available
        wh_size = 0.0
        if len(numbers) >= 2:
            staff = int(float(numbers[1]))
            
    return shop_size, warehouse_avail, wh_size, staff

class NewDistributorFlowHandler:
    async def handle_message(self, message: ParsedMessage, session: Any) -> None:
        phone = message.from_phone
        collected = session.collected_json or {}
        step = session.current_step
        
        if step == "D_NAME":
            if not collected.get("name_asked"):
                collected["name_asked"] = True
                await session_service.patch_collected(phone, {"name_asked": True})
                await whatsapp_client.send_text(phone, Q1_DIST_NAME)
                return
            else:
                text = message.text or ""
                if not text.strip():
                    await whatsapp_client.send_text(phone, Q1_DIST_NAME)
                    return
                c_name, s_name = parse_name(text)
                collected["contact_name"] = c_name
                collected["shop_name"] = s_name
                collected.pop("name_asked", None)
                await session_service.patch_collected(phone, {
                    "contact_name": c_name,
                    "shop_name": s_name,
                    "name_asked": None
                })
                
                await session_service.set_step(phone, "D_LOCATION")
                await whatsapp_client.send_text(phone, Q2_DIST_LOCATION)
                return
                
        elif step == "D_LOCATION":
            text = message.text or ""
            parsed = parse_location(text)
            if not parsed:
                await whatsapp_client.send_text(phone, Q2_DIST_INVALID)
                return
                
            city, district, state, pincode = parsed
            collected["city_town"] = city
            collected["district"] = district
            collected["state"] = state
            collected["pincode"] = pincode
            
            await session_service.patch_collected(phone, {
                "city_town": city,
                "district": district,
                "state": state,
                "pincode": pincode
            })
            
            await session_service.set_step(phone, "D_BRANDS")
            await whatsapp_client.send_text(phone, Q3_DIST_BRANDS)
            return
            
        elif step == "D_BRANDS":
            text = message.text or ""
            brands_list = parse_brands(text)
            collected["current_brands_sold"] = brands_list
            await session_service.patch_collected(phone, {"current_brands_sold": brands_list})
            
            await session_service.set_step(phone, "D_SALES")
            await whatsapp_client.send_text(phone, Q4_DIST_SALES)
            return
            
        elif step == "D_SALES":
            text = message.text or ""
            parsed = parse_sales(text)
            if not parsed:
                await whatsapp_client.send_text(phone, Q4_DIST_INVALID)
                return
                
            sales, radius = parsed
            collected["monthly_sales_volume_inr"] = sales
            collected["area_covered_radius_km"] = radius
            
            await session_service.patch_collected(phone, {
                "monthly_sales_volume_inr": sales,
                "area_covered_radius_km": radius
            })
            
            await session_service.set_step(phone, "D_WAREHOUSE")
            await whatsapp_client.send_text(phone, Q5_DIST_WAREHOUSE)
            return
            
        elif step == "D_WAREHOUSE":
            text = message.text or ""
            parsed = parse_warehouse(text)
            if not parsed:
                await whatsapp_client.send_text(phone, Q5_DIST_INVALID)
                return
                
            shop_size, wh_avail, wh_size, staff = parsed
            collected["shop_size_sqft"] = shop_size
            collected["warehouse_available"] = wh_avail
            collected["warehouse_size_sqft"] = wh_size
            collected["staff_size"] = staff
            
            await session_service.patch_collected(phone, {
                "shop_size_sqft": shop_size,
                "warehouse_available": wh_avail,
                "warehouse_size_sqft": wh_size,
                "staff_size": staff
            })
            
            await session_service.set_step(phone, "D_YEARS")
            await whatsapp_client.send_text(phone, Q6_DIST_YEARS)
            return
            
        elif step == "D_YEARS":
            text = message.text or ""
            nums = re.findall(r"(\d+(?:\.\d+)?)", text)
            if not nums:
                await whatsapp_client.send_text(phone, Q6_DIST_INVALID)
                return
                
            years = float(nums[0])
            collected["years_in_agri_business"] = years
            await session_service.patch_collected(phone, {"years_in_agri_business": years})
            
            await session_service.set_step(phone, "D_SEGMENTS")
            buttons = [
                {"id": "FIELD_CROP", "title": "फील्ड क्रॉप"},
                {"id": "VEGETABLES", "title": "सब्ज़ी"},
                {"id": "BOTH", "title": "दोनों"}
            ]
            await whatsapp_client.send_buttons(phone, Q7_DIST_SEGMENTS, buttons)
            return
            
        elif step == "D_SEGMENTS":
            segment_id = None
            if message.type == "button_reply" and message.button_payload:
                segment_id = message.button_payload
            else:
                # Text fallback
                text = (message.text or "").strip().lower()
                if "सब्जी" in text or "सब्ज़ी" in text or "veg" in text:
                    segment_id = "VEGETABLES"
                elif "फील्ड" in text or "field" in text:
                    segment_id = "FIELD_CROP"
                else:
                    segment_id = "BOTH"
                    
            segment_mapping = {
                "FIELD_CROP": ["Field Crop"],
                "VEGETABLES": ["Vegetables"],
                "BOTH": ["Field Crop", "Vegetables"]
            }
            collected["interested_segments"] = segment_mapping.get(segment_id, ["Field Crop", "Vegetables"])
            await session_service.patch_collected(phone, {"interested_segments": collected["interested_segments"]})
            
            # Run lead scoring and save
            score_res = lead_scoring.score(collected)
            score = score_res["score"]
            band = score_res["band"]
            
            notes = collected.get("notes_internal") or ""
            if collected.get("source_channel") == "whatsapp_ad":
                ref_info = f"[Attribution] Campaign: {collected.get('utm_campaign')} | Ad ID: {collected.get('referral_source_id')} | Click ID: {collected.get('ctwa_clid')}"
                notes = (notes + " | " + ref_info).strip(" | ")

            lead_data = {
                "contact_name": collected["contact_name"],
                "shop_name": collected["shop_name"],
                "state": collected["state"],
                "district": collected["district"],
                "city_town": collected["city_town"],
                "pincode": collected["pincode"],
                "current_brands_sold": collected.get("current_brands_sold", []),
                "monthly_sales_volume_inr": collected["monthly_sales_volume_inr"],
                "area_covered_radius_km": collected["area_covered_radius_km"],
                "shop_size_sqft": collected["shop_size_sqft"],
                "warehouse_available": collected["warehouse_available"],
                "warehouse_size_sqft": collected["warehouse_size_sqft"],
                "staff_size": collected["staff_size"],
                "years_in_agri_business": collected["years_in_agri_business"],
                "interested_segments": collected["interested_segments"],
                "lead_score": str(score),
                "lead_status": "qualified",
                "source_channel": collected.get("source_channel", "whatsapp_organic"),
                "notes_internal": notes if notes else None
            }
            
            # Save distributor lead in DB
            lead = await leads_repo.upsert_distributor_new(phone, lead_data)
            
            # Reset session first
            await session_service.reset(phone)
            
            # Branch on band
            if band == "HOT":
                await notify.sales_now(lead_data)
                await whatsapp_client.send_text(phone, DIST_QUALIFIED_REPLY + "\n📞 हमारी टीम के अधिकारी आपसे बहुत जल्द (1-2 घंटे में) सीधे संपर्क करेंगे।")
            elif band == "WARM":
                await whatsapp_client.send_text(phone, DIST_QUALIFIED_REPLY + "\nहमारी टीम के अधिकारी जल्द ही आपसे संपर्क करेंगे।")
            else:
                # COLD
                await whatsapp_client.send_text(phone, DIST_QUALIFIED_REPLY)
            return

distributor_new_flow_handler = NewDistributorFlowHandler()
