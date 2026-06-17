import os
import hmac
import hashlib
import json
import csv
import pytest
from datetime import datetime

# Mock environment variables
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"
os.environ["DASHBOARD_USER"] = "admin"
os.environ["DASHBOARD_PASS"] = "vigour123"

# Mock supabase client in our services before importing app
# Import 'conftest' in the exact same format as tests/test_simulation.py to avoid double import side-effects
from conftest import mock_supabase_client, in_memory_db
import app.api.dashboard
import app.services.retargeting
import app.services.catalog

app.api.dashboard.supabase_client = mock_supabase_client
app.services.retargeting.supabase_client = mock_supabase_client
app.services.catalog.supabase_client = mock_supabase_client

from app.main import app
from app.services.attribution import extract_referral_from_payload, attribute_message_payload
from app.services.retargeting import normalize_and_hash_phone, export_retargeting_audience

from fastapi.testclient import TestClient
client = TestClient(app)

@pytest.fixture
def ctw_ad_payload():
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "12345678",
                                "phone_number_id": "test_phone_id"
                            },
                            "messages": [
                                {
                                    "from": "919000000001",
                                    "id": "wamid.HBgLOT...=",
                                    "timestamp": "1678234851",
                                    "type": "text",
                                    "text": {
                                        "body": "Hi"
                                    },
                                    "referral": {
                                        "source_id": "ad_12345",
                                        "source_type": "ad",
                                        "source_url": "https://fb.me/some-ad",
                                        "headline": "Special Okra Seeds Campaign",
                                        "body": "Check out these seeds",
                                        "media_type": "image",
                                        "image_url": "https://url.to/image",
                                        "video_url": "",
                                        "thumbnail_url": "",
                                        "ctwa_clid": "click_abc123"
                                    }
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

def test_extract_referral_from_payload(ctw_ad_payload):
    referral = extract_referral_from_payload(ctw_ad_payload)
    assert referral is not None
    assert referral["source_id"] == "ad_12345"
    assert referral["headline"] == "Special Okra Seeds Campaign"
    assert referral["ctwa_clid"] == "click_abc123"
    assert referral["source_type"] == "ad"
    assert referral["source_url"] == "https://fb.me/some-ad"

@pytest.mark.asyncio
async def test_attribute_message_payload(ctw_ad_payload):
    # Process attribution
    patch = await attribute_message_payload(ctw_ad_payload)
    assert patch is not None
    assert patch["source_channel"] == "whatsapp_ad"
    assert patch["utm_campaign"] == "Special Okra Seeds Campaign"
    assert patch["ctwa_clid"] == "click_abc123"
    
    # Check session updated in InMemory database
    sessions = in_memory_db.tables["sessions"]
    user_session = next((s for s in sessions if s["whatsapp_phone"] == "919000000001"), None)
    assert user_session is not None
    assert user_session["collected_json"]["source_channel"] == "whatsapp_ad"
    assert user_session["collected_json"]["utm_campaign"] == "Special Okra Seeds Campaign"

def test_normalize_and_hash_phone():
    phone = "+91 88888 88888"
    expected_hash = hashlib.sha256(b"918888888888").hexdigest()
    assert normalize_and_hash_phone(phone) == expected_hash

@pytest.mark.asyncio
async def test_export_retargeting_audience():
    # Clear and seed Leads database
    in_memory_db.clear_all()
    
    # 1. Closed lost farmer lead
    in_memory_db.insert_row("leads_farmer", {
        "lead_id": "f_1",
        "whatsapp_phone": "919000000001",
        "name": "Farmer One",
        "state": "Madhya Pradesh",
        "district": "Guna",
        "lead_status": "closed_lost",
        "help_needed_for": "pest_attack",
        "source_channel": "whatsapp_organic"
    })
    
    # 2. Active (new) farmer lead - should NOT be exported
    in_memory_db.insert_row("leads_farmer", {
        "lead_id": "f_2",
        "whatsapp_phone": "919000000002",
        "name": "Farmer Two",
        "state": "Madhya Pradesh",
        "district": "Guna",
        "lead_status": "qualifying",
        "help_needed_for": "disease",
        "source_channel": "whatsapp_organic"
    })
    
    # 3. Cold distributor lead (score < 45)
    in_memory_db.insert_row("leads_distributor_new", {
        "lead_id": "d_1",
        "whatsapp_phone": "919000000003",
        "contact_name": "Dealer One",
        "shop_name": "Seeds Shop",
        "state": "Madhya Pradesh",
        "district": "Ujjain",
        "monthly_sales_volume_inr": 50000.0,
        "interested_segments": ["field_crops"],
        "lead_score": "35",
        "lead_status": "new",
        "source_channel": "whatsapp_organic"
    })
    
    # 4. Warm distributor lead (score >= 45) - should NOT be exported
    in_memory_db.insert_row("leads_distributor_new", {
        "lead_id": "d_2",
        "whatsapp_phone": "919000000004",
        "contact_name": "Dealer Two",
        "shop_name": "Super Seeds",
        "state": "Madhya Pradesh",
        "district": "Indore",
        "monthly_sales_volume_inr": 600000.0,
        "interested_segments": ["field_crops"],
        "lead_score": "60",
        "lead_status": "new",
        "source_channel": "whatsapp_organic"
    })

    file_path, count = await export_retargeting_audience()
    assert count == 2
    assert file_path is not None
    assert os.path.exists(file_path)

    # Read exported CSV
    hashed_phones = []
    with open(file_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ["phone"]
        for row in reader:
            hashed_phones.append(row[0])

    expected_hashes = {
        normalize_and_hash_phone("919000000001"),
        normalize_and_hash_phone("919000000003")
    }
    assert set(hashed_phones) == expected_hashes
    
    # Cleanup file
    if os.path.exists(file_path):
        os.remove(file_path)

def test_dashboard_auth_and_rendering():
    # Test dashboard page returns 401 without auth
    response = client.get("/dashboard")
    assert response.status_code == 401

    # Test dashboard page returns 401 with invalid auth
    response = client.get("/dashboard", auth=("admin", "wrongpassword"))
    assert response.status_code == 401

    # Seed some dummy data in DB
    in_memory_db.clear_all()
    in_memory_db.insert_row("leads_distributor_new", {
        "lead_id": "dist_id_123",
        "whatsapp_phone": "919000000005",
        "contact_name": "Test Distributor",
        "shop_name": "Test Seeds Store",
        "state": "Madhya Pradesh",
        "district": "Ujjain",
        "monthly_sales_volume_inr": 1200000.0,
        "interested_segments": ["field_crops"],
        "lead_score": "85",
        "lead_status": "new",
        "source_channel": "whatsapp_organic"
    })
    in_memory_db.insert_row("tickets", {
        "ticket_id": "TKT-TEST",
        "lead_id": "dist_id_123",
        "whatsapp_phone": "919000000005",
        "user_type": "distributor",
        "ticket_category": "billing",
        "ticket_priority": "high",
        "ticket_status": "open",
        "subject": "Overdue billing query",
        "description": "Billing is incorrect on invoice",
        "assigned_team": "finance",
        "sla_target_hours": 24.0,
        "created_at": datetime.utcnow().isoformat()
    })

    # Test dashboard page loads successfully with valid auth
    response = client.get("/dashboard", auth=("admin", "vigour123"))
    assert response.status_code == 200
    html = response.text
    
    # Assert dashboard page contains expected styled elements and seeded information
    assert "Vigour Seeds Ops" in html
    assert "Live Monitoring" in html
    assert "Test Distributor" in html
    assert "Test Seeds Store" in html
    assert "HOT" in html
    assert "Overdue billing query" in html
    assert "TKT-TEST" in html
