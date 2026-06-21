import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from app.db.client import supabase_client
from app.db.repositories.crops import crops_repo
from app.db.repositories.products import products_repo
from app.db.repositories.rules import rules_repo
from app.db.repositories.leads import leads_repo
from app.services.session import session_service
from app.whatsapp.client import whatsapp_client
from app.core.logging import logger
from app.core.messages_farmer import ESCALATION_MESSAGE, PHOTO_ASK
from app.core.messages_reco import RECO_HEADER, RECO_PRODUCT_CARD, RECO_FOOTER

# Map Hindi state names to English codes
STATE_TO_CODE = {
    "Madhya Pradesh": "MP",
    "Maharashtra": "MH",
    "Rajasthan": "RJ",
    "Gujarat": "GJ",
    "Uttar Pradesh": "UP",
    "Chhattisgarh": "CG",
    "Karnataka": "KA",
    "Andhra Pradesh": "AP",
    "Telangana": "TG",
    "Bihar": "BR",
    "Odisha": "OD",
    "Punjab": "PB",
    "Haryana": "HR",
    "Tamil Nadu": "TN",
    "West Bengal": "WB"
}

def get_state_code(state_name: str) -> str:
    return STATE_TO_CODE.get(state_name, "MP")

def get_canonical_crop_name(crop_id: str, crop_name_en: str) -> str:
    mapping = {
        "CR01": "Soybean",
        "CR02": "Maize",
        "CR03": "Paddy",
        "CR04": "Wheat",
        "CR07": "Chickpea (Chana)",
        "CR15": "Okra",
        "CR16": "Tomato",
        "CR17": "Hot Pepper (Chilli)"
    }
    if crop_id in mapping:
        return mapping[crop_id]
        
    # Fallback cleanup
    name = crop_name_en.split("(")[0].split("/")[0].strip()
    return name

def map_stage_to_hindi(stage: str) -> str:
    mapping = {
        "sowing": "बुवाई",
        "vegetative": "बढ़वार",
        "flowering": "फूल/फल",
        "maturity": "परिपक्वता"
    }
    return mapping.get(stage.lower(), stage)

class RecommenderService:
    async def resolve(self, phone: str, collected: dict) -> None:
        crop_id = collected.get("current_crop")
        
        # 1. Fetch Crop details
        crop_name_en = "Any"
        crop_name_hi = "फसल"
        if crop_id:
            crop_row = await crops_repo.get_by_id(crop_id)
            if crop_row:
                crop_name_en = crop_row.crop_name_en
                crop_name_hi = crop_row.crop_name_hi
                
        canonical_crop = get_canonical_crop_name(crop_id or "", crop_name_en)
        stage = collected.get("crop_stage", "Any")
        
        # Primary problem category
        prob_cat_list = collected.get("problem_category") or []
        primary_prob = prob_cat_list[0] if prob_cat_list else "-"
        if primary_prob == "unclear":
            primary_prob = "unclear_problem"
            
        irrigation = "Irrigated" if collected.get("total_land") else "Rainfed" # inferred default
        state_code = get_state_code(collected.get("state", "Madhya Pradesh"))
        logger.debug(f"DEBUG RESOLVE: crop={canonical_crop}, stage={stage}, problem={primary_prob}, irrigation={irrigation}, region={state_code}")
        logger.info(
            "Resolving recommendation rule",
            extra={
                "phone": phone,
                "crop": canonical_crop,
                "stage": stage,
                "problem": primary_prob,
                "irrigation": irrigation,
                "region": state_code
            }
        )
        
        # 2. Match recommendation rule from DB
        rule = await rules_repo.match(canonical_crop, stage, primary_prob, irrigation, state_code)
        
        # Fallback 1: Match with problem '-'
        if not rule and primary_prob != "-":
            logger.info("Specific rule not found, falling back to problem '-'", extra={"phone": phone})
            rule = await rules_repo.match(canonical_crop, stage, "-", irrigation, state_code)
            
        # Fallback 2: Catch-all unclear problem R900
        if not rule:
            logger.info("Fallback to catch-all unclear problem R900", extra={"phone": phone})
            rule = await rules_repo.match("Any", "Any", "unclear_problem", "Any", "Any")
            
        if not rule:
            logger.error("No recommendation rule matched, even fallback R900", extra={"phone": phone})
            await self._escalate(phone, collected, "System Error: Rule unmatched")
            return
            
        logger.info("Rule matched successfully", extra={"phone": phone, "rule_id": rule.rule_id, "next_action": rule.next_action})
        
        # Check human review flag
        human_review = getattr(rule, "human_review_required", False)
        if isinstance(human_review, str):
            human_review = human_review.strip().upper() in ["Y", "YES", "TRUE"]
            
        if human_review or rule.next_action == "escalate_agronomist":
            await self._escalate(phone, collected, f"Rule {rule.rule_id} triggered agronomist escalation")
            return
            
        if rule.next_action == "ask_for_photo":
            if collected.get("photo_url"):
                # Photo already exists, but still unclear -> escalate
                await self._escalate(phone, collected, f"Unclear problem even with photo under rule {rule.rule_id}")
            else:
                # Ask for photo
                await session_service.set_step(phone, "F_PHOTO")
                await whatsapp_client.send_text(phone, PHOTO_ASK)
            return
            
        if rule.next_action == "send_recommendation":
            await self._recommend(phone, collected, rule, crop_name_hi, stage, primary_prob, state_code)
            return
            
        # Fallback for unrecognized action
        await self._escalate(phone, collected, f"Unrecognized next_action: {rule.next_action}")

    async def _recommend(self, phone: str, collected: dict, rule: Any, crop_hi: str, stage: str, problem: str, state_code: str) -> None:
        # Load recommended product IDs from the rule
        recommended_ids = []
        if getattr(rule, "recommended_product_ids", None):
            recommended_ids = [p.strip() for p in rule.recommended_product_ids.split(",") if p.strip()]
            
        matched_products = []
        
        # Fetch products from DB
        for pid in recommended_ids:
            p = await products_repo.get_by_id(pid)
            if p and p.approved_for_recommendation == "Y":
                matched_products.append(p)
                
        # Filter and cap at 3
        matched_products = matched_products[:3]
        
        # If no products matched or list is empty, query products by crop and match target_problem_fit
        if not matched_products and collected.get("current_crop"):
            logger.info("Product list empty from rule, querying crop catalog", extra={"phone": phone})
            crop_name_en = "Any"
            crop_row = await crops_repo.get_by_id(collected["current_crop"])
            if crop_row:
                crop_name_en = crop_row.crop_name_en
            canonical_crop = get_canonical_crop_name(collected["current_crop"], crop_name_en)
            
            crop_products = await products_repo.list_by_crop(canonical_crop)
            for p in crop_products:
                if p.approved_for_recommendation == "Y":
                    fit = (p.target_problem_fit or "").lower()
                    if problem.lower() in fit or any(w in fit for w in problem.lower().split("_")):
                         matched_products.append(p)
                         
            if not matched_products:
                # Fallback to first 3 approved crop products
                matched_products = [p for p in crop_products if p.approved_for_recommendation == "Y"][:3]
                
        if not matched_products:
            # Still no products found -> escalate
            logger.warning("No catalog products found for recommendation", extra={"phone": phone})
            await self._escalate(phone, collected, "No catalog products found")
            return
            
        # Format and send cards
        header_text = RECO_HEADER.format(crop=crop_hi, stage=map_stage_to_hindi(stage))
        await whatsapp_client.send_text(phone, header_text)
        
        for p in matched_products:
            # Format price line
            if p.mrp_inr is not None:
                price_line = f"{p.mrp_inr} रुपये"
            else:
                price_line = "दर व कीमत के लिए नज़दीकी डीलर से पूछें।"
                
            # Format pack size line
            pack_size_line = ""
            if p.pack_size:
                pack_size_line = f"• पैक साइज: {p.pack_size}\n"
                
            # Shorten खासियत key traits to 1 line
            traits = p.key_traits or p.target_problem_fit or ""
            traits_line = traits.split("\n")[0].split(".")[0].strip()[:80]
            if not traits_line:
                traits_line = "-"
                
            card_text = RECO_PRODUCT_CARD.format(
                variety_name=p.variety_name,
                crop=p.crop,
                duration_days=p.duration_days or "TBD",
                key_traits=traits_line,
                pest_disease_tolerance=p.pest_disease_tolerance or "-",
                pack_size_line=pack_size_line,
                price_line=price_line
            )
            await whatsapp_client.send_text(phone, card_text)
            
        # Send footer
        await whatsapp_client.send_text(phone, RECO_FOOTER)
        
        # Send interactive next-action buttons
        buttons = [
            {"id": "ACT_DEALER", "title": "📍 नज़दीकी डीलर"},
            {"id": "ACT_CALLBACK", "title": "📞 कॉलबैक चाहिए"},
            {"id": "ACT_AGRONOMIST", "title": "👨🌾 विशेषज्ञ से बात"}
        ]
        await whatsapp_client.send_buttons(phone, "आपको किसमें सहायता चाहिए? 👇", buttons)
        
        # Save recommended fields in leads_farmer
        rec_ids = [p.product_id for p in matched_products]
        now_str = datetime.utcnow().isoformat() + "Z"
        
        fields = {
            "recommended_product_ids": rec_ids,
            "recommendation_sent_at": now_str,
            "lead_status": "recommendation_sent",
            "next_action": "send_recommendation"
        }
        # Merge fields with collected
        collected.update(fields)
        
        # Upsert in database
        try:
            await leads_repo.upsert_farmer(phone, collected)
            logger.info("Farmer recommendation successfully saved in DB", extra={"phone": phone})
            # Increment recommendations sent metric
            try:
                from app.services.metrics import metrics_service
                metrics_service.increment_recos_sent()
            except Exception:
                pass
        except Exception as e:
            logger.error("Failed to save farmer recommendation in DB", extra={"phone": phone, "error": str(e)})

    async def _escalate(self, phone: str, collected: dict, reason: str) -> None:
        logger.info("Escalating lead to human agronomist", extra={"phone": phone, "reason": reason})
        
        fields = {
            "escalated_to_human": True,
            "next_action": "escalate_agronomist",
            "lead_status": "escalated"
        }
        collected.update(fields)
        
        try:
            await leads_repo.upsert_farmer(phone, collected)
            # Increment escalations metric
            try:
                from app.services.metrics import metrics_service
                metrics_service.increment_escalations()
            except Exception:
                pass
        except Exception as e:
            logger.error("Failed to save escalated lead in DB", extra={"phone": phone, "error": str(e)})
            
        await whatsapp_client.send_text(phone, ESCALATION_MESSAGE)

recommender = RecommenderService()
