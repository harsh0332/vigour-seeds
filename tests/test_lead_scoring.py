import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock env vars
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

from app.services.lead_scoring import lead_scoring
from app.flows.distributor_new import distributor_new_flow_handler
from app.whatsapp.models import ParsedMessage
from app.models.db_models import SessionRow

def test_scoring_high_volume_hot():
    # A high-volume new distributor (₹12L, 10yr, warehouse 1500sqft, 3 brands, 5 staff, 30km)
    lead = {
        "monthly_sales_volume_inr": 1200000.0,
        "years_in_agri_business": 10.0,
        "warehouse_available": True,
        "warehouse_size_sqft": 1500.0,
        "current_brands_sold": ["Syngenta", "Bayer", "Pioneer"],
        "staff_size": 5,
        "area_covered_radius_km": 30.0
    }
    
    result = lead_scoring.score(lead)
    assert result["band"] == "HOT"
    assert result["score"] == 115

def test_scoring_low_volume_cold():
    # A small one (₹1L, 1yr, no warehouse, 0 brands, 0 staff, 5km)
    lead = {
        "monthly_sales_volume_inr": 100000.0,
        "years_in_agri_business": 1.0,
        "warehouse_available": False,
        "current_brands_sold": "",
        "staff_size": 0,
        "area_covered_radius_km": 5.0
    }
    
    result = lead_scoring.score(lead)
    assert result["band"] == "COLD"
    assert result["score"] == 23

def test_boundary_hot_70():
    lead = {
        "monthly_sales_volume_inr": 500000.0,
        "years_in_agri_business": 2.0,
        "warehouse_available": True,
        "warehouse_size_sqft": 500.0,
        "current_brands_sold": [],
        "staff_size": 0,
        "area_covered_radius_km": 25.0
    }
    result = lead_scoring.score(lead)
    assert result["score"] == 70
    assert result["band"] == "HOT"

def test_boundary_warm_69():
    lead = {
        "monthly_sales_volume_inr": 500000.0,
        "years_in_agri_business": 2.0,
        "warehouse_available": True,
        "warehouse_size_sqft": 500.0,
        "current_brands_sold": [],
        "staff_size": 1,
        "area_covered_radius_km": 24.0
    }
    result = lead_scoring.score(lead)
    assert result["score"] == 69
    assert result["band"] == "WARM"

def test_boundary_warm_45():
    lead = {
        "monthly_sales_volume_inr": 200000.0,
        "years_in_agri_business": 1.0,
        "warehouse_available": False,
        "current_brands_sold": ["brand1"],
        "staff_size": 0,
        "area_covered_radius_km": 25.0
    }
    result = lead_scoring.score(lead)
    assert result["score"] == 45
    assert result["band"] == "WARM"

def test_boundary_cold_44():
    lead = {
        "monthly_sales_volume_inr": 200000.0,
        "years_in_agri_business": 1.0,
        "warehouse_available": False,
        "current_brands_sold": ["brand1"],
        "staff_size": 1,
        "area_covered_radius_km": 24.0
    }
    result = lead_scoring.score(lead)
    assert result["score"] == 44
    assert result["band"] == "COLD"

@pytest.mark.asyncio
@patch("app.flows.distributor_new.whatsapp_client")
@patch("app.flows.distributor_new.session_service")
@patch("app.flows.distributor_new.leads_repo")
@patch("app.flows.distributor_new.notify")
async def test_new_distributor_flow_hot_path(mock_notify, mock_leads_repo, mock_sess_service, mock_wa_client):
    # Setup mock methods
    mock_wa_client.send_text = AsyncMock()
    mock_wa_client.send_buttons = AsyncMock()
    mock_sess_service.patch_collected = AsyncMock()
    mock_sess_service.set_step = AsyncMock()
    mock_sess_service.reset = AsyncMock()
    mock_leads_repo.upsert_distributor_new = AsyncMock(return_value={"contact_name": "Ramesh Gupta"})
    mock_notify.sales_now = AsyncMock()
    
    session = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="distributor_new",
        current_step="D_NAME",
        collected_json={},
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    # 1. Ask Name step (initiator prompt)
    msg1 = ParsedMessage(wamid="w1", from_phone="919999999999", type="text", text="Hi", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg1, session)
    mock_wa_client.send_text.assert_called_with("919999999999", "नमस्ते! Vigour Seeds के नए डिस्ट्रीब्यूटर नेटवर्क में रुचि लेने के लिए धन्यवाद। व्यापार संबंधी चर्चा शुरू करने से पहले, कृपया अपना नाम और अपनी दुकान/फर्म का नाम बताइए। 🙏")
    
    # 2. Reply Name -> Move to D_LOCATION
    session.collected_json = {"name_asked": True}
    msg2 = ParsedMessage(wamid="w2", from_phone="919999999999", type="text", text="Ramesh Gupta, Ramesh Seeds", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg2, session)
    mock_sess_service.patch_collected.assert_called_with("919999999999", {
        "contact_name": "Ramesh Gupta",
        "shop_name": "Ramesh Seeds",
        "name_asked": None
    })
    mock_sess_service.set_step.assert_called_with("919999999999", "D_LOCATION")
    
    # 3. Reply Location -> Move to D_BRANDS
    session.current_step = "D_LOCATION"
    session.collected_json = {"contact_name": "Ramesh Gupta", "shop_name": "Ramesh Seeds"}
    msg3 = ParsedMessage(wamid="w3", from_phone="919999999999", type="text", text="Indore, Indore, MP, 452001", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg3, session)
    mock_sess_service.patch_collected.assert_called_with("919999999999", {
        "city_town": "Indore",
        "district": "Indore",
        "district_raw": "Indore",
        "state": "Madhya Pradesh",
        "pincode": "452001"
    })
    mock_sess_service.set_step.assert_called_with("919999999999", "D_BRANDS")
    
    # 4. Reply Brands -> Move to D_SALES
    session.current_step = "D_BRANDS"
    session.collected_json.update({"city_town": "Indore", "district": "Indore", "state": "Madhya Pradesh", "pincode": "452001"})
    msg4 = ParsedMessage(wamid="w4", from_phone="919999999999", type="text", text="Bayer, Syngenta, Pioneer", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg4, session)
    mock_sess_service.patch_collected.assert_called_with("919999999999", {
        "current_brands_sold": ["Bayer", "Syngenta", "Pioneer"]
    })
    mock_sess_service.set_step.assert_called_with("919999999999", "D_SALES")
    
    # 5. Reply Sales -> Move to D_WAREHOUSE
    session.current_step = "D_SALES"
    session.collected_json.update({"current_brands_sold": ["Bayer", "Syngenta", "Pioneer"]})
    msg5 = ParsedMessage(wamid="w5", from_phone="919999999999", type="text", text="12 Lakh, 30 km", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg5, session)
    mock_sess_service.patch_collected.assert_called_with("919999999999", {
        "monthly_sales_volume_inr": 1200000.0,
        "area_covered_radius_km": 30.0
    })
    mock_sess_service.set_step.assert_called_with("919999999999", "D_WAREHOUSE")
    
    # 6. Reply Warehouse -> Move to D_YEARS
    session.current_step = "D_WAREHOUSE"
    session.collected_json.update({"monthly_sales_volume_inr": 1200000.0, "area_covered_radius_km": 30.0})
    msg6 = ParsedMessage(wamid="w6", from_phone="919999999999", type="text", text="1000 sqft, yes, 1500 sqft, 5 staff", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg6, session)
    mock_sess_service.patch_collected.assert_called_with("919999999999", {
        "shop_size_sqft": 1000.0,
        "warehouse_available": True,
        "warehouse_size_sqft": 1500.0,
        "staff_size": 5
    })
    mock_sess_service.set_step.assert_called_with("919999999999", "D_YEARS")
    
    # 7. Reply Years -> Move to D_SEGMENTS
    session.current_step = "D_YEARS"
    session.collected_json.update({"shop_size_sqft": 1000.0, "warehouse_available": True, "warehouse_size_sqft": 1500.0, "staff_size": 5})
    msg7 = ParsedMessage(wamid="w7", from_phone="919999999999", type="text", text="10 years", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg7, session)
    mock_sess_service.patch_collected.assert_called_with("919999999999", {
        "years_in_agri_business": 10.0
    })
    mock_sess_service.set_step.assert_called_with("919999999999", "D_SEGMENTS")
    
    # 8. Reply Segment button -> Complete and Score
    session.current_step = "D_SEGMENTS"
    session.collected_json.update({"years_in_agri_business": 10.0})
    msg8 = ParsedMessage(wamid="w8", from_phone="919999999999", type="button_reply", button_payload="BOTH", timestamp="1718563800")
    await distributor_new_flow_handler.handle_message(msg8, session)
    
    # Scoring verification
    mock_sess_service.reset.assert_called_with("919999999999")
    mock_leads_repo.upsert_distributor_new.assert_called_once()
    mock_notify.sales_now.assert_called_once()
    
    # Verify exact qualified text sent
    confirm_call_args = mock_wa_client.send_text.call_args_list[-1][0][1]
    assert "जुड़ने में रुचि के लिए" in confirm_call_args
    assert "1-2 घंटे में" in confirm_call_args
