import os
import sys
import asyncio
import uuid
import time
from datetime import datetime

# Setup environment variables
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

# Import conftest to bootstrap all mocks (Supabase, WhatsApp, AI)
import tests.conftest
from tests.conftest import in_memory_db, mock_whatsapp_client

from app.flows.router import conversation_router
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo
from app.whatsapp.models import ParsedMessage
from app.services.session import session_service

PHONE = "919000000001"

async def print_bot_responses():
    """Prints all captured outbound messages from the mock WhatsApp client and clears them."""
    if not mock_whatsapp_client.sent_messages:
        return
        
    for msg in mock_whatsapp_client.sent_messages:
        msg_type = msg.get("type", "text")
        to = msg.get("to")
        
        # Format the message output beautifully
        print("BOT >", end=" ")
        if msg_type == "text":
            body = msg.get("body", "")
            print(body.replace("\n", "\n      "))
        elif msg_type == "buttons":
            body = msg.get("body", "")
            print(body.replace("\n", "\n      "))
            for btn in msg.get("buttons", []):
                btn_id = btn.get("id") or btn.get("reply", {}).get("id", "")
                btn_title = btn.get("title") or btn.get("reply", {}).get("title", "")
                print(f"      [{btn_id}] {btn_title}")
        elif msg_type == "list":
            header = msg.get("header", "Menu")
            body = msg.get("body", "")
            print(f"[{header}] {body}".replace("\n", "\n      "))
            for section in msg.get("sections", []):
                print(f"      --- {section.get('title', '')} ---")
                for row in section.get("rows", []):
                    print(f"      [{row['id']}] {row['title']} - {row.get('description', '')}")
        else:
            print(f"[{msg_type.upper()}] {msg}")
            
    mock_whatsapp_client.clear()

async def handle_user_message(text: str):
    """Simulates sending a text message from the user."""
    # Classify button/list clicks or standard text
    msg_type = "text"
    button_payload = None
    list_id = None
    
    if text.startswith("CHOOSE_") or text.startswith("ACT_") or text in ["sowing", "vegetative", "flowering", "current_crop", "next_crop", "both"]:
        msg_type = "button_reply"
        button_payload = text
    elif text.startswith("CATALOG_") or text.startswith("F_") or text in ["pest_attack", "disease", "other_problems"]:
        msg_type = "list_reply"
        list_id = text
        
    msg = ParsedMessage(
        wamid=f"wamid.sim_{uuid.uuid4().hex}",
        from_phone=PHONE,
        profile_name="Ramesh",
        type=msg_type,
        text=text,
        button_payload=button_payload,
        list_id=list_id,
        media_id=None,
        timestamp=str(int(time.time()))
    )
    await conversation_router.route_message(msg)

async def handle_user_photo(media_id: str = "media_pest_0.8"):
    """Simulates sending a photo from the user."""
    msg = ParsedMessage(
        wamid=f"wamid.sim_{uuid.uuid4().hex}",
        from_phone=PHONE,
        profile_name="Ramesh",
        type="image",
        text="",
        button_payload=None,
        list_id=None,
        media_id=media_id,
        timestamp=str(int(time.time()))
    )
    await conversation_router.route_message(msg)

async def main():
    # Initialize mock DB with seed data
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    mock_whatsapp_client.clear()
    
    print("=" * 60)
    print("Vigour Seeds WhatsApp Chat Simulator (Phase 9)")
    print("Type your message below. Special commands:")
    print("  /photo       - Sends a crop photo (triggers diagnosis & recommendation)")
    print("  /state       - Prints database and session status")
    print("  /reset       - Resets the current chat session")
    print("  /exit or /q  - Exits the simulator")
    print("=" * 60)
    print()
    
    # Prompt user for initial message
    while True:
        try:
            user_input = input("YOU > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting simulator.")
            break
            
        if not user_input:
            continue
            
        if user_input.lower() in ["/exit", "/q"]:
            print("Exiting simulator.")
            break
            
        if user_input.lower() == "/reset":
            await session_service.reset(PHONE)
            # Also clear the leads table for this phone to start clean
            in_memory_db.tables["leads_farmer"] = [r for r in in_memory_db.tables["leads_farmer"] if r.get("whatsapp_phone") != PHONE]
            print("[Session and leads reset for this number. Start typing to begin new chat!]")
            continue
            
        if user_input.lower() == "/state":
            print("\n--- [CURRENT STATE] ---")
            # Query session
            session = await sessions_repo.get(PHONE)
            if session:
                print(f"Session Step : {session.current_step}")
                print(f"Session Flow : {session.current_flow}")
                print(f"Collected    : {session.collected_json}")
            else:
                print("Session      : None (or expired/reset)")
                
            # Query lead
            lead = await leads_repo.get_farmer(PHONE)
            if lead:
                print(f"Lead Name    : {lead.name}")
                print(f"Lead Status  : {lead.lead_status}")
                print(f"District     : {lead.district}")
                print(f"District Raw : {lead.collected_json.get('district_raw') if hasattr(lead, 'collected_json') and lead.collected_json else lead.notes_internal if 'district_raw' not in lead.__dict__ else getattr(lead, 'district_raw', None)}")
                print(f"State        : {lead.state}")
                print(f"Crop/Stage   : {lead.current_crop} / {lead.crop_stage}")
                print(f"Diagnosis    : {lead.photo_ai_diagnosis} (conf: {lead.photo_ai_confidence})")
            else:
                print("Lead in DB   : None")
            print("-----------------------\n")
            continue
            
        if user_input.lower() == "/photo":
            print("[Simulating sending image media_id='media_pest_0.8'...]")
            await handle_user_photo("media_pest_0.8")
            await print_bot_responses()
            continue
            
        # Send message
        await handle_user_message(user_input)
        await print_bot_responses()

if __name__ == "__main__":
    # Run the interactive simulator
    asyncio.run(main())
