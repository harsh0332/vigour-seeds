import pytest
import time
import uuid
from datetime import datetime
from unittest.mock import patch, AsyncMock
from typing import Optional

from app.whatsapp.models import ParsedMessage
from app.flows.router import conversation_router
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo
from app.db.repositories.tickets import tickets_repo
from conftest import in_memory_db, mock_whatsapp_client, mock_ai_provider

async def send_msg(
    phone: str,
    text: str,
    msg_type: str = "text",
    media_id: Optional[str] = None,
    button_payload: Optional[str] = None,
    list_id: Optional[str] = None
):
    """Utility helper to send ParsedMessage through the router."""
    msg = ParsedMessage(
        wamid=f"wamid.sim_{uuid.uuid4().hex}",
        from_phone=phone,
        profile_name="Simulated User",
        type=msg_type,
        text=text,
        button_payload=button_payload,
        list_id=list_id,
        media_id=media_id,
        timestamp=str(int(time.time()))
    )
    await conversation_router.route_message(msg)

@pytest.mark.asyncio
async def test_journey_a_farmer_pest_photo_reco_dealer():
    """
    (a) Farmer pest -> photo conf 0.8 -> reco -> dealer
    """
    phone = "919000000001"
    
    # 1. Greet (Initial message)
    await send_msg(phone, "कीड़े की समस्या है")
    session = await sessions_repo.get(phone)
    assert session.current_flow == "farmer_qualification"
    assert session.current_step == "F_NAME"
    assert "आपका नाम" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 2. Send Name
    await send_msg(phone, "रमेश")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_LOCATION"
    assert "ज़िले और राज्य" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 3. Send Location
    await send_msg(phone, "Ujjain, मध्य प्रदेश")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_LAND"
    assert "ज़मीन" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 4. Send Land
    await send_msg(phone, "5 एकड़")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_CROP"
    # Q4 crop is a list menu or buttons
    assert "फसल" in mock_whatsapp_client.sent_messages[-1]["body"] or "फसल" in mock_whatsapp_client.sent_messages[-1]["header"]

    # 5. Send Crop
    await send_msg(phone, "सोयाबीन")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_STAGE"
    assert "चरण" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 6. Send Stage
    await send_msg(phone, "बुवाई/छोटा पौधा", msg_type="button_reply", button_payload="sowing")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_HELP_FOR"
    assert "जानकारी" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 7. Send Help Type
    await send_msg(phone, "अभी की फसल", msg_type="button_reply", button_payload="current_crop")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_PROBLEM"
    assert "समस्या" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 8. Send Problem
    await send_msg(phone, "कीड़े/इल्ली", msg_type="list_reply", list_id="pest_attack")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_PHOTO"
    assert "फोटो" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 9. Send Photo (Confidence 0.8)
    await send_msg(phone, "", msg_type="image", media_id="media_pest_0.8")
    
    # Session should be reset
    session = await sessions_repo.get(phone)
    assert session is None or session.current_flow is None
    
    # Lead should be qualified and saved in database
    lead = await leads_repo.get_farmer(phone)
    assert lead is not None
    assert lead.lead_status == "recommendation_sent"
    assert lead.photo_ai_confidence == 0.8
    assert lead.photo_ai_diagnosis == "pest_attack"
    assert lead.escalated_to_human is False
    
    # Check that recommendation was sent (it has product Vigour 335 / PROD_S1)
    reco_sent = False
    for msg in mock_whatsapp_client.sent_messages:
        if "Vigour" in msg.get("body", ""):
            reco_sent = True
    assert reco_sent is True

    # 10. Click Dealer Button (ACT_DEALER)
    await send_msg(phone, "डीलर ढूंढें", msg_type="button_reply", button_payload="ACT_DEALER")
    
    # Verify depot and dealer shop information was dispatched
    dealer_sent = False
    for msg in mock_whatsapp_client.sent_messages:
        if "Sharma Seeds" in msg.get("body", ""):
            dealer_sent = True
    assert dealer_sent is True

@pytest.mark.asyncio
async def test_journey_b_farmer_disease_photo_low_conf_escalate():
    """
    (b) Farmer disease -> photo conf 0.5 -> escalate
    """
    phone = "919000000002"
    
    # Greet and fast-track to F_PHOTO step by patching session state directly (saves test lines)
    await sessions_repo.upsert(phone, {
        "user_type": "farmer",
        "current_flow": "farmer_qualification",
        "current_step": "F_PHOTO",
        "collected_json": {
            "name": "Rohan",
            "state": "Madhya Pradesh",
            "district": "Ujjain",
            "total_land": 10.0,
            "current_crop": "CR01",
            "crop_stage": "sowing",
            "problem_category": ["fungal_disease"]
        }
    })
    
    # Send Image with "disease" inside media_id to trigger confidence 0.5 mock
    await send_msg(phone, "", msg_type="image", media_id="media_disease_0.5")
    
    # Lead status should be escalated
    lead = await leads_repo.get_farmer(phone)
    assert lead is not None
    assert lead.lead_status == "escalated"
    assert lead.photo_ai_confidence == 0.5
    assert lead.escalated_to_human is True
    
    # Outbound messages should include escalation text
    escalation_sent = False
    for msg in mock_whatsapp_client.sent_messages:
        if "कृषि विशेषज्ञ" in msg.get("body", "") or "agronomist" in msg.get("body", "").lower():
            escalation_sent = True
    assert escalation_sent is True

@pytest.mark.asyncio
async def test_journey_c_farmer_skip_photo_reco():
    """
    (c) Farmer skip photo -> reco from text
    """
    phone = "919000000003"
    
    await sessions_repo.upsert(phone, {
        "user_type": "farmer",
        "current_flow": "farmer_qualification",
        "current_step": "F_PHOTO",
        "collected_json": {
            "name": "Suresh",
            "state": "Madhya Pradesh",
            "district": "Ujjain",
            "total_land": 4.0,
            "current_crop": "CR01",
            "crop_stage": "sowing",
            "problem_category": ["pest_attack"]
        }
    })
    
    # Send "skip" text
    await send_msg(phone, "skip")
    
    # Lead should be qualified and recommendation sent
    lead = await leads_repo.get_farmer(phone)
    assert lead is not None
    assert lead.lead_status == "recommendation_sent"
    assert lead.photo_url is None
    
    reco_sent = False
    for msg in mock_whatsapp_client.sent_messages:
        if "Vigour" in msg.get("body", ""):
            reco_sent = True
    assert reco_sent is True

@pytest.mark.asyncio
async def test_journey_d_distributor_new_hot_notify():
    """
    (d) New distributor HOT -> instant notify
    """
    phone = "919000000004"
    
    # Greet / classify intent
    await send_msg(phone, "मैं डीलरशिप लेना चाहता हूँ")
    session = await sessions_repo.get(phone)
    assert session.current_flow == "distributor_new"
    assert session.current_step == "D_NAME"
    assert "दुकान/फर्म" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    # D_NAME: Name & Firm
    await send_msg(phone, "अमित कुमार, अमित बीज भंडार")
    assert (await sessions_repo.get(phone)).current_step == "D_LOCATION"
    
    # D_LOCATION: Location
    await send_msg(phone, "इंदौर, मध्यप्रदेश, 452001")
    assert (await sessions_repo.get(phone)).current_step == "D_BRANDS"
    
    # D_BRANDS: Brands
    await send_msg(phone, "Vigour, Pioneer, Monsanto, Syngenta")
    assert (await sessions_repo.get(phone)).current_step == "D_SALES"
    
    # D_SALES: Sales volume (HOT: 12 Lakhs monthly)
    await send_msg(phone, "12 lakh rupees, 30 km radius")
    assert (await sessions_repo.get(phone)).current_step == "D_WAREHOUSE"
    
    # D_WAREHOUSE: Shop, Warehouse size, Staff
    await send_msg(phone, "1500 sqft shop, yes, 1200 sqft warehouse, 5 staff")
    assert (await sessions_repo.get(phone)).current_step == "D_YEARS"
    
    # D_YEARS: Years in business
    await send_msg(phone, "12 years")
    assert (await sessions_repo.get(phone)).current_step == "D_SEGMENTS"
    
    # D_SEGMENTS: Button reply Field crop
    await send_msg(phone, "फील्ड क्रॉप", msg_type="button_reply", button_payload="FIELD_CROP")
    
    # Session reset
    assert await sessions_repo.get(phone) is None
    
    # Lead must be scored as HOT and saved in DB
    lead = in_memory_db.tables["leads_distributor_new"][-1]
    assert lead["whatsapp_phone"] == phone
    assert int(float(lead["lead_score"])) >= 70
    assert lead["lead_status"] == "qualified"
    
    # Outbound notifications must include both the user response and the Sales rep alert (917777777777)
    rep_notified = False
    for msg in mock_whatsapp_client.sent_messages:
        if msg["to"] == "917777777777" and "HOT Distributor Lead Alert" in msg["body"]:
            rep_notified = True
    assert rep_notified is True

@pytest.mark.asyncio
async def test_journey_e_distributor_new_cold_nurture():
    """
    (e) New distributor COLD -> nurture
    """
    phone = "919000000005"
    
    # Fast track to D_SEGMENTS with cold features
    await sessions_repo.upsert(phone, {
        "user_type": "distributor_new",
        "current_flow": "distributor_new",
        "current_step": "D_SEGMENTS",
        "collected_json": {
            "contact_name": "Vijay",
            "shop_name": "Vijay Seeds",
            "state": "Madhya Pradesh",
            "district": "Ujjain",
            "city_town": "Ujjain",
            "pincode": "456001",
            "current_brands_sold": [],
            "monthly_sales_volume_inr": 50000.0,
            "area_covered_radius_km": 5.0,
            "shop_size_sqft": 100.0,
            "warehouse_available": False,
            "warehouse_size_sqft": 0.0,
            "staff_size": 0,
            "years_in_agri_business": 1.0
        }
    })
    
    await send_msg(phone, "फील्ड क्रॉप", msg_type="button_reply", button_payload="FIELD_CROP")
    
    # DB Lead saved
    lead = in_memory_db.tables["leads_distributor_new"][-1]
    assert lead["whatsapp_phone"] == phone
    assert int(float(lead["lead_score"])) < 45
    
    # Sales rep (917777777777) should NOT be notified
    rep_notified = False
    for msg in mock_whatsapp_client.sent_messages:
        if msg["to"] == "917777777777" and "HOT Distributor Lead Alert" in msg["body"]:
            rep_notified = True
    assert rep_notified is False

@pytest.mark.asyncio
async def test_journey_f_distributor_existing_ticket():
    """
    (f) Existing distributor -> ticket
    """
    phone = "918888888888" # Pre-seeded active distributor (Sanjay Sharma)
    
    # Send message, should auto-identify active distributor, greet and enter flow
    await send_msg(phone, "Namaste")
    
    session = await sessions_repo.get(phone)
    assert session.current_flow == "distributor_existing"
    assert session.current_step == "ticket_init"
    
    # Trigger category menu
    await send_msg(phone, "help")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_DIST_EX_CAT"
    
    # Select category: Payment (payment_issue)
    await send_msg(phone, "पेमेंट", msg_type="list_reply", list_id="payment_issue")
    session = await sessions_repo.get(phone)
    assert session.current_step == "F_DIST_EX_DESC"
    
    # Provide description
    await send_msg(phone, "मेरी पेमेंट अटक गई है, कृपया जांचें।")
    
    # Session reset
    assert await sessions_repo.get(phone) is None
    
    # Ticket created in DB
    tickets = in_memory_db.tables["tickets"]
    assert len(tickets) >= 1
    ticket = tickets[-1]
    assert ticket["whatsapp_phone"] == phone
    assert ticket["ticket_category"] == "payment_issue"
    assert ticket["ticket_priority"] == "high" # payment_issue is high priority
    assert ticket["assigned_team"] == "accounts" # payment_issue maps to accounts team
    assert ticket["assigned_person"] == "Rajesh Kumar" # pre-seeded sales rep for DST001
    
    # Sales Rep / Team notified
    rep_notified = False
    for msg in mock_whatsapp_client.sent_messages:
        # Assigned Sales rep phone is 917777777777
        if msg["to"] == "917777777777" and "New Support Ticket Assigned" in msg["body"]:
            rep_notified = True
    assert rep_notified is True

@pytest.mark.asyncio
async def test_simulation_ai_failure_graceful_degrade():
    """
    AI Provider crashes -> Farmer flow gracefully degrades to human escalation instead of 500
    """
    phone = "919000000009"
    mock_ai_provider.should_fail = True
    
    await sessions_repo.upsert(phone, {
        "user_type": "farmer",
        "current_flow": "farmer_qualification",
        "current_step": "F_PHOTO",
        "collected_json": {
            "name": "Test Graceful",
            "state": "Madhya Pradesh",
            "district": "Ujjain",
            "total_land": 5.0,
            "current_crop": "CR01",
            "crop_stage": "sowing",
            "problem_category": ["pest_attack"]
        }
    })
    
    # Vision diagnosis fails because AI provider fails, should degrade gracefully to confidence 0.0 & escalate
    await send_msg(phone, "", msg_type="image", media_id="media_crash")
    
    lead = await leads_repo.get_farmer(phone)
    assert lead is not None
    assert lead.lead_status == "escalated"
    assert lead.photo_ai_confidence == 0.0
    assert lead.escalated_to_human is True
    
    # Confirms session was reset
    assert await sessions_repo.get(phone) is None

@pytest.mark.asyncio
async def test_simulation_meta_429_retry_handling():
    """
    Simulated Meta 429 outbound client send -> retried then logged, webhook returns 200
    """
    from fastapi.testclient import TestClient
    from app.main import app
    import json
    import hmac
    import hashlib
    
    client = TestClient(app)
    
    # Mock execute_post to fail with MetaRateLimitException
    from app.core.errors import MetaRateLimitException
    
    async def mock_fail_post(*args, **kwargs):
        raise MetaRateLimitException("Simulated Meta 429 Rate Limit")
        
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15555555555", "phone_number_id": "test_phone_id"},
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": "919000000100"}],
                            "messages": [{
                                "from": "919000000100",
                                "id": "wamid.meta429test",
                                "timestamp": str(int(time.time())),
                                "text": {"body": "कीड़े की समस्या है"},
                                "type": "text"
                            }]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }
    
    payload_bytes = json.dumps(payload).encode("utf-8")
    app_secret_bytes = "test_app_secret".encode("utf-8")
    signature = hmac.new(app_secret_bytes, payload_bytes, hashlib.sha256).hexdigest()
    
    headers = {
        "X-Hub-Signature-256": f"sha256={signature}",
        "Content-Type": "application/json"
    }
    
    from app.whatsapp.client import WhatsAppClient
    real_client = WhatsAppClient()
    
    # Patch execute_post to simulate Meta 429, which retry_with_backoff will try 3 times
    # and then log as critical, but webhook still returns 200 OK.
    # We patch inside WhatsAppClient
    with patch("app.flows.farmer.whatsapp_client", real_client), \
         patch("app.flows.router.whatsapp_client", real_client), \
         patch("asyncio.sleep", new=AsyncMock()) as mock_sleep, \
         patch("app.whatsapp.client.WhatsAppClient._execute_post", new=AsyncMock(side_effect=mock_fail_post)) as mock_post:
         
        response = client.post("/webhook", content=payload_bytes, headers=headers)
        assert response.status_code == 200
        assert response.text == "EVENT_RECEIVED"
        
        # Verify the background task was executed (give background tasks a small sleep to run since they are async)
        # Fastapi background tasks run immediately, but let's yield control to make sure it processed.
        # Calling process_webhook_payload directly makes it easy. Let's call it synchronously to ensure the mock was called.
        from app.api.webhook import process_webhook_payload
        try:
            await process_webhook_payload(payload)
        except Exception:
            pass
            
        # The mock post should have been retried 3 times (due to retry_with_backoff max attempts)
        assert mock_post.call_count == 3
