import os
import pandas as pd
import numpy as np
from app.db.client import supabase_client
from app.core.logging import logger

def clean_row(row):
    # Convert numpy types/NaN to Python None
    d = {}
    for k, v in row.items():
        if pd.isna(v) or v is None or (isinstance(v, float) and np.isnan(v)):
            d[k] = None
        else:
            d[k] = v
    return d

def seed_crops():
    path = "seed/crops.csv"
    if not os.path.exists(path):
        logger.error(f"File not found: {path}")
        return 0
    df = pd.read_csv(path)
    records = [clean_row(row) for row in df.to_dict(orient="records")]
    
    if supabase_client:
        res = supabase_client.table("crops").upsert(records).execute()
        count = len(res.data) if res.data else 0
        logger.info(f"Seeded {count} crops")
        return count
    return 0

def seed_products():
    path = "seed/products.csv"
    if not os.path.exists(path):
        logger.error(f"File not found: {path}")
        return 0
    df = pd.read_csv(path)
    records = []
    for row in df.to_dict(orient="records"):
        cleaned = clean_row(row)
        # Convert numeric mrp_inr
        if cleaned.get("mrp_inr") is not None:
            try:
                cleaned["mrp_inr"] = float(cleaned["mrp_inr"])
            except ValueError:
                cleaned["mrp_inr"] = None
        # distributor_availability, mrp_inr and approved_for_recommendation blank as NULL
        # approved_for_recommendation should default to 'Y' unless it is explicitly set
        if cleaned.get("approved_for_recommendation") is None:
            cleaned["approved_for_recommendation"] = "Y"
        records.append(cleaned)
        
    if supabase_client:
        res = supabase_client.table("products").upsert(records).execute()
        count = len(res.data) if res.data else 0
        logger.info(f"Seeded {count} products")
        return count
    return 0

def seed_recommendation_rules():
    path = "seed/recommendation_rules.csv"
    if not os.path.exists(path):
        logger.error(f"File not found: {path}")
        return 0
    df = pd.read_csv(path)
    records = []
    for row in df.to_dict(orient="records"):
        cleaned = clean_row(row)
        # Convert human_review_required from 'Y'/'N' to boolean
        hrr = cleaned.get("human_review_required")
        if hrr == "Y":
            cleaned["human_review_required"] = True
        else:
            cleaned["human_review_required"] = False
        records.append(cleaned)
        
    if supabase_client:
        res = supabase_client.table("recommendation_rules").upsert(records).execute()
        count = len(res.data) if res.data else 0
        logger.info(f"Seeded {count} recommendation rules")
        return count
    return 0

def seed_regions():
    path = "seed/regions.csv"
    if not os.path.exists(path):
        logger.error(f"File not found: {path}")
        return 0
    df = pd.read_csv(path)
    records = [clean_row(row) for row in df.to_dict(orient="records")]
    
    if supabase_client:
        res = supabase_client.table("regions").upsert(records).execute()
        count = len(res.data) if res.data else 0
        logger.info(f"Seeded {count} regions")
        return count
    return 0

def seed_followups():
    # Hardcoded followups from sheet
    followup_data = [
        {
            "id": 1,
            "user_type": "farmer",
            "lead_status": "qualifying",
            "day": 1,
            "send_after_hours": 24,
            "message_template_id": "fu_farmer_q_d1",
            "message_text_hindi": "नमस्ते 🙏 क्या आप अभी भी अपनी फसल की समस्या के बारे में बात करना चाहते हैं? हम मदद के लिए तैयार हैं।",
            "next_action_if_no_reply": "Wait 24h"
        },
        {
            "id": 2,
            "user_type": "farmer",
            "lead_status": "qualifying",
            "day": 2,
            "send_after_hours": 48,
            "message_template_id": "fu_farmer_q_d2",
            "message_text_hindi": "हम आपकी फसल की समस्या का मुफ्त समाधान बता सकते हैं। बस एक छोटा सा सवाल — आपकी फसल कौन सी है?",
            "next_action_if_no_reply": "Wait 24h"
        },
        {
            "id": 3,
            "user_type": "farmer",
            "lead_status": "qualifying",
            "day": 3,
            "send_after_hours": 72,
            "message_template_id": "fu_farmer_q_d3",
            "message_text_hindi": "अंतिम मौका 🌾 — आज ही सही बीज और सलाह से अपनी पैदावार बढ़ाएं। बस \"हाँ\" लिखकर भेजें।",
            "next_action_if_no_reply": "Mark closed_lost"
        },
        {
            "id": 4,
            "user_type": "farmer",
            "lead_status": "recommendation_sent",
            "day": 1,
            "send_after_hours": 48,
            "message_template_id": "fu_farmer_rec_d1",
            "message_text_hindi": "क्या आपको हमारी सलाह उपयोगी लगी? कोई और सवाल हो तो बताएं।",
            "next_action_if_no_reply": "Wait 5 days"
        },
        {
            "id": 5,
            "user_type": "farmer",
            "lead_status": "recommendation_sent",
            "day": 7,
            "send_after_hours": 168,
            "message_template_id": "fu_farmer_rec_d7",
            "message_text_hindi": "आपकी फसल कैसी चल रही है? कोई अपडेट हो तो बताएं — हम आगे की सलाह दे सकते हैं।",
            "next_action_if_no_reply": "Mark closed_won if no issue"
        },
        {
            "id": 6,
            "user_type": "farmer",
            "lead_status": "escalated",
            "day": 1,
            "send_after_hours": 4,
            "message_template_id": "fu_farmer_esc_d1",
            "message_text_hindi": "हमारे एग्रोनॉमिस्ट जल्द ही आपसे संपर्क करेंगे। अगर अभी कोई urgent मदद चाहिए तो call करें: [number]",
            "next_action_if_no_reply": "No auto-action — human owns"
        },
        {
            "id": 7,
            "user_type": "distributor_new",
            "lead_status": "qualifying",
            "day": 1,
            "send_after_hours": 24,
            "message_template_id": "fu_dist_q_d1",
            "message_text_hindi": "नमस्ते जी 🤝 Vigour Seeds के साथ डिस्ट्रीब्यूटरशिप के लिए आपकी रुचि के लिए धन्यवाद। क्या हम आगे बात कर सकते हैं?",
            "next_action_if_no_reply": "Wait 24h"
        },
        {
            "id": 8,
            "user_type": "distributor_new",
            "lead_status": "qualifying",
            "day": 2,
            "send_after_hours": 48,
            "message_template_id": "fu_dist_q_d2",
            "message_text_hindi": "हमारी टीम आपके area में distributor opportunity discuss करना चाहती है। बस अपना shop name बता दें।",
            "next_action_if_no_reply": "Wait 24h"
        },
        {
            "id": 9,
            "user_type": "distributor_new",
            "lead_status": "qualifying",
            "day": 3,
            "send_after_hours": 72,
            "message_template_id": "fu_dist_q_d3",
            "message_text_hindi": "कोई बात नहीं अगर अभी time नहीं है। जब भी interest हो, message कर दें।",
            "next_action_if_no_reply": "Mark closed_lost"
        },
        {
            "id": 10,
            "user_type": "distributor_new",
            "lead_status": "qualified",
            "day": 1,
            "send_after_hours": 4,
            "message_template_id": "fu_dist_qf_d1",
            "message_text_hindi": "हमारी sales team [name] अगले [time] में आपको call करेगी। तब तक कोई सवाल हो तो पूछें।",
            "next_action_if_no_reply": "No auto-action — sales owns"
        },
        {
            "id": 11,
            "user_type": "distributor_existing",
            "lead_status": "ticket_open",
            "day": 1,
            "send_after_hours": 4,
            "message_template_id": "fu_exdist_tkt_d1",
            "message_text_hindi": "आपकी ticket [TKT-ID] हमारी टीम के पास है। हम जल्द ही update देंगे।",
            "next_action_if_no_reply": "Escalate to manager if SLA breach"
        },
        {
            "id": 12,
            "user_type": "distributor_existing",
            "lead_status": "ticket_resolved",
            "day": 1,
            "send_after_hours": 24,
            "message_template_id": "fu_exdist_resolved_d1",
            "message_text_hindi": "क्या आपकी समस्या solve हो गई? कृपया 1-5 rating दें।",
            "next_action_if_no_reply": "Auto-close after 7 days"
        }
    ]
    
    if supabase_client:
        # Clear table first to prevent serial/upsert conflicts and duplication
        supabase_client.table("followups").delete().neq("id", 0).execute()
        res = supabase_client.table("followups").insert(followup_data).execute()
        count = len(res.data) if res.data else 0
        logger.info(f"Seeded {count} followups")
        return count
    return 0

def main():
    logger.info("Starting database seeding...")
    c_count = seed_crops()
    p_count = seed_products()
    r_count = seed_recommendation_rules()
    reg_count = seed_regions()
    f_count = seed_followups()
    
    logger.info("Database seeding complete!")
    print(f"✅ Seeding summary:")
    print(f"   - Crops: {c_count}")
    print(f"   - Products: {p_count}")
    print(f"   - Rules: {r_count}")
    print(f"   - Regions: {reg_count}")
    print(f"   - Followups: {f_count}")

if __name__ == "__main__":
    main()
