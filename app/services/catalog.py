from typing import List
import asyncio
from app.db.client import supabase_client
from app.db.repositories.crops import crops_repo
from app.db.repositories.products import products_repo
from app.whatsapp.client import whatsapp_client
from app.core.logging import logger

class CatalogService:
    async def send_crop_menu(self, phone: str) -> None:
        """
        Sends the initial interactive list of available crops for browsing the catalog.
        """
        try:
            crops = await crops_repo.list_in_catalog()
            if not crops:
                # Fallback if no crops in catalog
                await whatsapp_client.send_text(phone, "माफ़ कीजिए, अभी कोई फसल कैटलॉग में उपलब्ध नहीं है।")
                return

            rows = []
            for crop in crops:
                rows.append({
                    "id": f"CATALOG_CROP_{crop.crop_name_en}",
                    "title": crop.crop_name_hi or crop.crop_name_en,
                    "description": f"Browse {crop.crop_name_en} varieties"
                })

            sections = [{
                "title": "फसलें",
                "rows": rows,
                "button_label": "फसल चुनें"
            }]

            body = "किस फसल की उन्नत किस्मों (Varieties) की जानकारी देखना चाहते हैं? नीचे दिए गए बटन से फसल चुनें:"
            await whatsapp_client.send_list(phone, "उत्पाद कैटलॉग", body, sections)
            logger.info("Sent catalog crop menu", extra={"phone": phone})
        except Exception as e:
            logger.error("Failed to send catalog crop menu", extra={"phone": phone, "error": str(e)})

    async def send_crop_catalog(self, phone: str, crop_name: str) -> None:
        """
        Sends top approved varieties for the specified crop.
        Lists traits, duration, and the 'Confirm with dealer' footer, omitting price and dosage.
        """
        if not supabase_client:
            await whatsapp_client.send_text(phone, "सिस्टम त्रुटि: कैटलॉग लोड नहीं किया जा सका।")
            return

        try:
            # Query approved varieties for the crop
            res = await asyncio.to_thread(
                lambda: supabase_client.table("products")
                .select("*")
                .eq("crop", crop_name)
                .eq("approved_for_recommendation", "Y")
                .limit(5)
                .execute()
            )
            
            products = res.data or []
            if not products:
                await whatsapp_client.send_text(
                    phone, 
                    f"माफ़ कीजिए, {crop_name} के लिए अभी कोई स्वीकृत वैरायटी उपलब्ध नहीं है।"
                )
                return

            body = f"🌱 *Vigour Seeds - {crop_name} वैरायटी सूची*:\n\n"
            for p in products:
                body += f"🔹 *{p.get('variety_name', 'N/A')}*\n"
                if p.get("duration_days"):
                    body += f"  • अवधि: {p.get('duration_days')} दिन\n"
                if p.get("key_traits"):
                    body += f"  • विशेषताएँ: {p.get('key_traits')}\n"
                if p.get("pack_size"):
                    body += f"  • पैक साइज: {p.get('pack_size')}\n"
                body += "\n"

            # Mandatory read-only footer
            body += "⚠️ _डीलर से पुष्टि करें (Confirm with dealer)_"
            
            await whatsapp_client.send_text(phone, body)
            logger.info("Sent crop catalog details", extra={"phone": phone, "crop": crop_name})
        except Exception as e:
            logger.error("Failed to send crop catalog details", extra={"phone": phone, "crop": crop_name, "error": str(e)})

catalog_service = CatalogService()
