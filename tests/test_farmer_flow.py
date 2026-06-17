import os
import pytest
from unittest.mock import AsyncMock, patch

# Set mock env variables for config initialization
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

from app.flows.farmer import farmer_flow_handler
from app.whatsapp.models import ParsedMessage
from app.models.db_models import SessionRow

@pytest.mark.asyncio
@patch("app.flows.farmer.whatsapp_client")
@patch("app.services.session.sessions_repo")
async def test_farmer_flow_name_prompt(mock_sess_repo, mock_client):
    session = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_NAME",
        collected_json={},
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    mock_sess_repo.upsert = AsyncMock()
    mock_client.send_text = AsyncMock()
    
    # Send choice trigger
    msg = ParsedMessage(
        wamid="wamid.1",
        from_phone="919999999999",
        type="button_reply",
        button_payload="CHOOSE_FARMER",
        timestamp="1718563800"
    )
    
    await farmer_flow_handler.handle_message(msg, session)
    
    # Should ask name and set name_asked = True in collected
    mock_client.send_text.assert_called_once_with("919999999999", "आपका नाम क्या है? 🙏")
    
    # Now user replies with name
    session.collected_json = {"name_asked": True}
    msg_reply = ParsedMessage(
        wamid="wamid.2",
        from_phone="919999999999",
        type="text",
        text="Ramesh Kumar",
        timestamp="1718563800"
    )
    
    with patch("app.flows.farmer.session_service") as mock_sess_service:
        mock_sess_service.patch_collected = AsyncMock()
        mock_sess_service.set_step = AsyncMock()
        
        await farmer_flow_handler.handle_message(msg_reply, session)
        
        mock_sess_service.patch_collected.assert_called_once_with("919999999999", {"name": "Ramesh Kumar", "name_asked": None})
        mock_sess_service.set_step.assert_called_once_with("919999999999", "F_LOCATION")

@pytest.mark.asyncio
@patch("app.flows.farmer.whatsapp_client")
@patch("app.flows.farmer.get_active_states")
async def test_farmer_flow_location(mock_get_states, mock_client):
    mock_get_states.return_value = [{"state": "Madhya Pradesh", "state_code": "MP"}]
    mock_client.send_text = AsyncMock()
    
    session = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_LOCATION",
        collected_json={"name": "Ramesh Kumar"},
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    # Invalid location test
    msg_invalid = ParsedMessage(
        wamid="wamid.3",
        from_phone="919999999999",
        type="text",
        text="Bihar Guna",
        timestamp="1718563800"
    )
    await farmer_flow_handler.handle_message(msg_invalid, session)
    mock_client.send_text.assert_called_once_with("919999999999", "माफ़ कीजिए, हम इस राज्य में सेवा नहीं दे पा रहे हैं या राज्य का नाम सही नहीं है। कृपया दोबारा अपना ज़िला और राज्य लिखें (जैसे: गुना, मध्य प्रदेश):")
    
    # Valid location test
    mock_client.send_text.reset_mock()
    msg_valid = ParsedMessage(
        wamid="wamid.4",
        from_phone="919999999999",
        type="text",
        text="गुना, मध्य प्रदेश",
        timestamp="1718563800"
    )
    with patch("app.flows.farmer.session_service") as mock_sess_service:
        mock_sess_service.patch_collected = AsyncMock()
        mock_sess_service.set_step = AsyncMock()
        
        await farmer_flow_handler.handle_message(msg_valid, session)
        
        mock_sess_service.patch_collected.assert_called_once_with("919999999999", {"state": "Madhya Pradesh", "district": "Guna", "district_raw": "गुना"})
        mock_sess_service.set_step.assert_called_once_with("919999999999", "F_LAND")

@pytest.mark.asyncio
@patch("app.flows.farmer.whatsapp_client")
async def test_farmer_flow_land(mock_client):
    mock_client.send_text = AsyncMock()
    mock_client.send_list = AsyncMock()
    
    session = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_LAND",
        collected_json={"name": "Ramesh Kumar", "state": "Madhya Pradesh", "district": "Guna"},
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    # Invalid land size
    msg_invalid = ParsedMessage(
        wamid="wamid.5",
        from_phone="919999999999",
        type="text",
        text="bahut saari zameen",
        timestamp="1718563800"
    )
    await farmer_flow_handler.handle_message(msg_invalid, session)
    mock_client.send_text.assert_called_once_with("919999999999", "कृपया ज़मीन का आकार संख्या में लिखें (जैसे: 5 या 2.5):")
    
    # Valid land size
    mock_client.send_text.reset_mock()
    msg_valid = ParsedMessage(
        wamid="wamid.6",
        from_phone="919999999999",
        type="text",
        text="5.5 acre",
        timestamp="1718563800"
    )
    with patch("app.flows.farmer.session_service") as mock_sess_service, \
         patch("app.flows.farmer.get_crop_list") as mock_get_crops:
        mock_sess_service.patch_collected = AsyncMock()
        mock_sess_service.set_step = AsyncMock()
        mock_get_crops.return_value = [{"crop_id": "CR01", "crop_name_hi": "सोयाबीन", "crop_name_en": "Soybean"}]
        
        await farmer_flow_handler.handle_message(msg_valid, session)
        
        mock_sess_service.patch_collected.assert_called_once_with("919999999999", {"total_land": 5.5, "land_unit": "acre"})
        mock_sess_service.set_step.assert_called_once_with("919999999999", "F_CROP")
        mock_client.send_list.assert_called_once()

@pytest.mark.asyncio
@patch("app.flows.farmer.whatsapp_client")
@patch("app.flows.farmer.upload_photo_to_storage")
@patch("app.flows.farmer.get_crop_details")
@patch("app.flows.farmer.vision_service")
@patch("app.flows.farmer.leads_repo")
@patch("app.flows.farmer.recommender")
async def test_farmer_flow_photo_confidence_gate(mock_recommender, mock_leads_repo, mock_vision, mock_get_details, mock_upload, mock_client):
    mock_client.download_media = AsyncMock(return_value=(b"fake_bytes", "image/jpeg"))
    mock_client.send_text = AsyncMock()
    mock_upload.return_value = "https://mock.supabase.co/storage/v1/object/public/crop-photos/mock.jpg"
    mock_get_details.return_value = ("सोयाबीन", "Soybean")
    mock_leads_repo.upsert_farmer = AsyncMock()
    mock_recommender.resolve = AsyncMock(side_effect=lambda phone, collected: mock_client.send_text(phone, "reco pending"))
    
    session = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_PHOTO",
        collected_json={
            "name": "Ramesh Kumar", "state": "Madhya Pradesh", "district": "Guna",
            "total_land": 5.0, "land_unit": "acre", "current_crop": "CR01",
            "crop_stage": "vegetative", "help_needed_for": "current_crop",
            "problem_category": ["yellow_leaves"]
        },
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    # Case 1: Low Confidence (0.59) -> Escalation path
    mock_vision.diagnose = AsyncMock(return_value={
        "problem_category": "pest_attack",
        "confidence": 0.59,
        "severity": "high",
        "visible_symptoms_hindi": "कीड़े दिख रहे हैं"
    })
    
    msg_image = ParsedMessage(
        wamid="wamid.7",
        from_phone="919999999999",
        type="image",
        media_id="media.123",
        timestamp="1718563800"
    )
    
    with patch("app.flows.farmer.session_service") as mock_sess_service:
        mock_sess_service.reset = AsyncMock()
        await farmer_flow_handler.handle_message(msg_image, session)
        
        # Verify escalated
        mock_leads_repo.upsert_farmer.assert_called_once()
        args, kwargs = mock_leads_repo.upsert_farmer.call_args
        fields = args[1]
        assert fields["lead_status"] == "escalated"
        assert fields["escalated_to_human"] is True
        assert fields["next_action"] == "escalate_agronomist"
        assert "pest_attack" in fields["problem_category"]
        
        # Verify escalation message sent
        mock_client.send_text.assert_any_call("919999999999", "आपकी फसल की समस्या थोड़ी जटिल लग रही है 🌾 हमारे कृषि विशेषज्ञ (एग्रोनॉमिस्ट) जल्द ही आपसे संपर्क करेंगे। तब तक चिंता न करें।")
        for call in mock_client.send_text.call_args_list:
            assert "reco pending" not in call[0][1]
            
    # Case 2: High Confidence (0.61) -> Qualified path
    mock_leads_repo.upsert_farmer.reset_mock()
    mock_client.send_text.reset_mock()
    
    mock_vision.diagnose = AsyncMock(return_value={
        "problem_category": "pest_attack",
        "confidence": 0.61,
        "severity": "medium",
        "visible_symptoms_hindi": "कीड़े दिख रहे हैं"
    })
    
    session_new = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_PHOTO",
        collected_json={
            "name": "Ramesh Kumar", "state": "Madhya Pradesh", "district": "Guna",
            "total_land": 5.0, "land_unit": "acre", "current_crop": "CR01",
            "crop_stage": "vegetative", "help_needed_for": "current_crop",
            "problem_category": ["yellow_leaves"]
        },
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    with patch("app.flows.farmer.session_service") as mock_sess_service:
        mock_sess_service.reset = AsyncMock()
        await farmer_flow_handler.handle_message(msg_image, session_new)
        
        mock_leads_repo.upsert_farmer.assert_called_once()
        args, kwargs = mock_leads_repo.upsert_farmer.call_args
        fields = args[1]
        assert fields["lead_status"] == "qualified"
        assert fields["escalated_to_human"] is False
        
        mock_client.send_text.assert_any_call("919999999999", "reco pending")

@pytest.mark.asyncio
@patch("app.flows.farmer.whatsapp_client")
@patch("app.flows.farmer.leads_repo")
@patch("app.flows.farmer.recommender")
async def test_farmer_flow_photo_skip(mock_recommender, mock_leads_repo, mock_client):
    mock_client.send_text = AsyncMock()
    mock_leads_repo.upsert_farmer = AsyncMock()
    mock_recommender.resolve = AsyncMock(side_effect=lambda phone, collected: mock_client.send_text(phone, "reco pending"))
    
    session = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_PHOTO",
        collected_json={
            "name": "Ramesh Kumar", "state": "Madhya Pradesh", "district": "Guna",
            "total_land": 5.0, "land_unit": "acre", "current_crop": "CR01",
            "crop_stage": "vegetative", "help_needed_for": "current_crop",
            "problem_category": ["yellow_leaves"]
        },
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    msg_skip = ParsedMessage(
        wamid="wamid.8",
        from_phone="919999999999",
        type="text",
        text="skip",
        timestamp="1718563800"
    )
    
    with patch("app.flows.farmer.session_service") as mock_sess_service:
        mock_sess_service.reset = AsyncMock()
        await farmer_flow_handler.handle_message(msg_skip, session)
        
        # Verify qualified
        mock_leads_repo.upsert_farmer.assert_called_once()
        args, kwargs = mock_leads_repo.upsert_farmer.call_args
        fields = args[1]
        assert fields["lead_status"] == "qualified"
        assert fields["escalated_to_human"] is False
        
        # Verify recommender stub called
        mock_client.send_text.assert_called_once_with("919999999999", "reco pending")
