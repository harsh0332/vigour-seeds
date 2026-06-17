import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# Set mock env variables
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

from app.flows.router import conversation_router
from app.whatsapp.models import ParsedMessage
from app.models.db_models import DistributorActiveRow, SessionRow

class MockResponse:
    def __init__(self, data):
        self.data = data

@pytest.mark.asyncio
@patch("app.flows.router.distributors_repo")
@patch("app.flows.router.sessions_repo")
@patch("app.services.session.sessions_repo")
@patch("app.flows.router.whatsapp_client")
async def test_router_greet_existing_distributor(mock_client, mock_service_sess_repo, mock_sess_repo, mock_dist_repo):
    # Setup mock active distributor
    mock_dist = DistributorActiveRow(
        distributor_id="DST001",
        whatsapp_phone="918888888888",
        contact_name="Sanjay Sharma",
        shop_name="Sharma Seeds",
        state="MP",
        district="Ujjain",
        territory_code="TERR01",
        onboarded_date="2025-01-01",
        assigned_sales_rep="Rajesh Kumar",
        assigned_sales_rep_phone="917777777777"
    )
    mock_dist_repo.get_active_by_phone = AsyncMock(return_value=mock_dist)
    
    # Setup session: no active flow
    mock_sess_repo.get = AsyncMock(return_value=None)
    mock_service_sess_repo.get = AsyncMock(return_value=None)
    
    session_start = SessionRow(
        whatsapp_phone="918888888888",
        current_step="start",
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    mock_sess_repo.upsert = AsyncMock(return_value=session_start)
    mock_service_sess_repo.upsert = AsyncMock(return_value=session_start)

    mock_client.send_text = AsyncMock()

    msg = ParsedMessage(
        wamid="wamid.1",
        from_phone="918888888888",
        type="text",
        text="Namaste",
        timestamp="1718563800"
    )

    await conversation_router.route_message(msg)

    # Must greet distributor by name Sanjay Sharma
    mock_client.send_text.assert_called_once()
    args, kwargs = mock_client.send_text.call_args
    assert "Sanjay Sharma" in args[1]
    assert "ऑर्डर / स्टॉक" in args[1]

@pytest.mark.asyncio
@patch("app.flows.router.distributors_repo")
@patch("app.flows.router.sessions_repo")
@patch("app.services.session.sessions_repo")
@patch("app.flows.router.whatsapp_client")
@patch("app.flows.farmer.whatsapp_client")
async def test_router_welcome_button_replies(mock_farmer_client, mock_client, mock_service_sess_repo, mock_sess_repo, mock_dist_repo):
    # Not a distributor
    mock_dist_repo.get_active_by_phone = AsyncMock(return_value=None)
    
    session_start = SessionRow(
        whatsapp_phone="919999999999",
        current_step="start",
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    session_farmer = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_NAME",
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    mock_sess_repo.get = AsyncMock(side_effect=[session_start, session_farmer])
    mock_service_sess_repo.get = AsyncMock(side_effect=[session_start, session_farmer])
    mock_sess_repo.upsert = AsyncMock(return_value=session_farmer)
    mock_service_sess_repo.upsert = AsyncMock(return_value=session_farmer)
    mock_client.send_text = AsyncMock()
    mock_farmer_client.send_text = mock_client.send_text

    # Tap farmer button
    msg = ParsedMessage(
        wamid="wamid.2",
        from_phone="919999999999",
        type="button_reply",
        button_payload="CHOOSE_FARMER",
        timestamp="1718563800"
    )

    await conversation_router.route_message(msg)

    # Verify session is updated to farmer flow
    mock_sess_repo.upsert.assert_called_with("919999999999", {
        "user_type": "farmer",
        "current_flow": "farmer_qualification",
        "current_step": "F_NAME"
    })
    mock_client.send_text.assert_called_once_with("919999999999", "आपका नाम क्या है? 🙏")

@pytest.mark.asyncio
@patch("app.flows.router.distributors_repo")
@patch("app.flows.router.sessions_repo")
@patch("app.services.session.sessions_repo")
@patch("app.flows.router.whatsapp_client")
@patch("app.flows.farmer.whatsapp_client")
@patch("app.flows.router.classify_intent")
async def test_router_free_text_routing_success(mock_classify, mock_farmer_client, mock_client, mock_service_sess_repo, mock_sess_repo, mock_dist_repo):
    mock_dist_repo.get_active_by_phone = AsyncMock(return_value=None)
    
    session_start = SessionRow(
        whatsapp_phone="919999999999",
        current_step="start",
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    session_farmer = SessionRow(
        whatsapp_phone="919999999999",
        current_flow="farmer_qualification",
        current_step="F_NAME",
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    mock_sess_repo.get = AsyncMock(side_effect=[session_start, session_farmer])
    mock_service_sess_repo.get = AsyncMock(side_effect=[session_start, session_farmer])
    mock_sess_repo.upsert = AsyncMock(return_value=session_farmer)
    mock_service_sess_repo.upsert = AsyncMock(return_value=session_farmer)
    
    # Mock high confidence intent classification
    mock_classify.return_value = {
        "intent": "farmer_crop_problem",
        "confidence": 0.85,
        "language": "hinglish"
    }

    mock_client.send_text = AsyncMock()
    mock_farmer_client.send_text = mock_client.send_text

    msg = ParsedMessage(
        wamid="wamid.3",
        from_phone="919999999999",
        type="text",
        text="soybean me paani ki dikkat hai",
        timestamp="1718563800"
    )

    await conversation_router.route_message(msg)

    # Verify routed to farmer qualification stub
    mock_sess_repo.upsert.assert_any_call("919999999999", {
        "user_type": "farmer",
        "current_flow": "farmer_qualification",
        "current_step": "F_NAME"
    })
    mock_client.send_text.assert_called_once_with("919999999999", "आपका नाम क्या है? 🙏")

@pytest.mark.asyncio
@patch("app.flows.router.distributors_repo")
@patch("app.flows.router.sessions_repo")
@patch("app.services.session.sessions_repo")
@patch("app.flows.router.whatsapp_client")
@patch("app.flows.router.classify_intent")
async def test_router_free_text_routing_low_confidence(mock_classify, mock_client, mock_service_sess_repo, mock_sess_repo, mock_dist_repo):
    mock_dist_repo.get_active_by_phone = AsyncMock(return_value=None)
    
    session_start = SessionRow(
        whatsapp_phone="919999999999",
        current_step="start",
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    mock_sess_repo.get = AsyncMock(return_value=session_start)
    mock_service_sess_repo.get = AsyncMock(return_value=session_start)
    
    session_reset = SessionRow(
        whatsapp_phone="919999999999",
        current_flow=None,
        current_step="start",
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    mock_sess_repo.upsert = AsyncMock(return_value=session_reset)
    mock_service_sess_repo.upsert = AsyncMock(return_value=session_reset)
    
    # Mock low confidence intent classification
    mock_classify.return_value = {
        "intent": "general_inquiry",
        "confidence": 0.40,
        "language": "hinglish"
    }

    mock_client.send_buttons = AsyncMock()

    msg = ParsedMessage(
        wamid="wamid.4",
        from_phone="919999999999",
        type="text",
        text="kuch bhi random text",
        timestamp="1718563800"
    )

    await conversation_router.route_message(msg)

    # Verify fallback triggers welcome buttons
    mock_client.send_buttons.assert_called_once()
    args, kwargs = mock_client.send_buttons.call_args
    assert "समझ नहीं पाया" in args[1]
