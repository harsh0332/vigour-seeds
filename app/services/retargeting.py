import os
import csv
import hashlib
import asyncio
from datetime import datetime
from typing import Tuple, List, Optional
from app.db.client import supabase_client
from app.core.logging import logger

def normalize_and_hash_phone(phone: str) -> str:
    """
    Normalizes phone number to digits only (E.164 without +) and returns its SHA-256 hash.
    """
    # Keep only digits
    digits = "".join(char for char in str(phone) if char.isdigit())
    
    # Meta Custom Audience expects SHA-256 hash of the normalized phone number string
    hashed = hashlib.sha256(digits.encode("utf-8")).hexdigest()
    return hashed

async def export_retargeting_audience() -> Tuple[Optional[str], int]:
    """
    Queries cold/closed_lost farmer and distributor leads, hashes their phone numbers,
    and writes them to a CSV file in the conversation artifacts directory.
    Returns: (file_path, count)
    """
    if not supabase_client:
        logger.error("Supabase client not initialized, cannot run retargeting export")
        return None, 0

    hashed_phones = set()

    # 1. Fetch closed_lost farmer leads
    try:
        res_farmer = await asyncio.to_thread(
            lambda: supabase_client.table("leads_farmer").select("whatsapp_phone, lead_status").eq("lead_status", "closed_lost").execute()
        )
        for row in (res_farmer.data or []):
            phone = row.get("whatsapp_phone")
            if phone:
                hashed_phones.add(normalize_and_hash_phone(phone))
    except Exception as e:
        logger.error("Failed to query farmer leads for retargeting", extra={"error": str(e)})

    # 2. Fetch cold / closed_lost distributor leads
    try:
        res_dist = await asyncio.to_thread(
            lambda: supabase_client.table("leads_distributor_new").select("whatsapp_phone, lead_status, lead_score").execute()
        )
        for row in (res_dist.data or []):
            status = row.get("lead_status")
            score_str = row.get("lead_score")
            
            is_cold = False
            if score_str:
                try:
                    if float(score_str) < 45.0:
                        is_cold = True
                except ValueError:
                    pass
                    
            if status == "closed_lost" or is_cold:
                phone = row.get("whatsapp_phone")
                if phone:
                    hashed_phones.add(normalize_and_hash_phone(phone))
    except Exception as e:
        logger.error("Failed to query distributor leads for retargeting", extra={"error": str(e)})

    count = len(hashed_phones)
    if count == 0:
        logger.info("No cold/closed_lost leads found for retargeting export")
        return None, 0

    # Ensure export directory exists
    conv_id = os.environ.get("CONVERSATION_ID", "c9bb5cc3-7a82-4978-a1a6-235ec0fbcbf0")
    # Base path in artifacts
    export_dir = f"/Users/harshchouksey/.gemini/antigravity/brain/{conv_id}"
    os.makedirs(export_dir, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"retargeting_export_{timestamp}.csv"
    file_path = os.path.join(export_dir, file_name)

    try:
        # Write SHA-256 hashed phone numbers to the CSV file
        # Column header is 'phone' as required by Meta Ads Manager
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["phone"])
            for h_phone in sorted(hashed_phones):
                writer.writerow([h_phone])
                
        logger.info("Retargeting export completed successfully", extra={"path": file_path, "leads_count": count})
        return file_path, count
    except Exception as e:
        logger.error("Failed to write retargeting CSV export", extra={"error": str(e)})
        return None, 0
