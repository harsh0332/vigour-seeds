import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, ANY

# Set mock env variables for config initialization before any imports
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

from app.whatsapp.window import is_within_window, send_followup
from app.ai.transcribe import voice_transcription_service
from app.services.followup import followup_service
from app.models.db_models import FollowupRow, LeadFarmerRow, TicketRow
from app.core.config import settings

class MockResponse:
    def __init__(self, data):
        self.data = data

# --- 1. WHATSAPP WINDOW COMPLIANCE TESTS ---

@pytest.mark.asyncio
@patch("app.whatsapp.window.supabase_client")
async def test_is_within_window_true(mock_supabase):
    # Setup: last inbound message was 5 hours ago
    last_inbound = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute = MagicMock(
        return_value=MockResponse([{"created_at": last_inbound}])
    )
    
    res = await is_within_window("919999999999")
    assert res is True

@pytest.mark.asyncio
@patch("app.whatsapp.window.supabase_client")
async def test_is_within_window_false(mock_supabase):
    # Setup: last inbound message was 30 hours ago
    last_inbound = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute = MagicMock(
        return_value=MockResponse([{"created_at": last_inbound}])
    )
    
    res = await is_within_window("919999999999")
    assert res is False

@pytest.mark.asyncio
@patch("app.whatsapp.window.supabase_client")
async def test_is_within_window_no_history(mock_supabase):
    # Setup: no conversations history
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute = MagicMock(
        return_value=MockResponse([])
    )
    
    res = await is_within_window("919999999999")
    assert res is False

@pytest.mark.asyncio
@patch("app.whatsapp.window.whatsapp_client")
@patch("app.whatsapp.window.is_within_window")
async def test_send_followup_inside_window(mock_window_check, mock_whatsapp):
    mock_window_check.return_value = True
    mock_whatsapp.send_text = AsyncMock(return_value={"status": "sent"})
    
    await send_followup("919999999999", "template_id", "fallback_text")
    
    mock_whatsapp.send_text.assert_called_once_with("919999999999", "fallback_text")
    mock_whatsapp.send_template.assert_not_called()

@pytest.mark.asyncio
@patch("app.whatsapp.window.whatsapp_client")
@patch("app.whatsapp.window.is_within_window")
async def test_send_followup_outside_window(mock_window_check, mock_whatsapp):
    mock_window_check.return_value = False
    mock_whatsapp.send_template = AsyncMock(return_value={"status": "sent"})
    
    await send_followup("919999999999", "template_id", "fallback_text", ["param1", "param2"])
    
    expected_components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "param1"},
                {"type": "text", "text": "param2"}
            ]
        }
    ]
    mock_whatsapp.send_template.assert_called_once_with("919999999999", "template_id", expected_components)
    mock_whatsapp.send_text.assert_not_called()


# --- 2. VOICE TRANSCRIPTION TESTS ---

@pytest.mark.asyncio
@patch("app.ai.transcribe.whatsapp_client")
@patch("app.ai.transcribe.ai_provider")
async def test_transcribe_gemini_success(mock_provider, mock_whatsapp):
    # Mock settings to use Gemini
    settings.AI_PROVIDER = "gemini"
    
    # Mock downloading audio file
    mock_whatsapp.download_media = AsyncMock(return_value=(b"audio_bytes", "audio/ogg"))
    
    # Mock Gemini client
    mock_gemini_client = MagicMock()
    mock_provider._gemini_client = mock_gemini_client
    
    mock_response = MagicMock()
    mock_response.text = "  गेहूं की फसल में पीलापन है  "
    mock_gemini_client.models.generate_content.return_value = mock_response
    
    transcription = await voice_transcription_service.transcribe_audio("media123", "audio/ogg")
    
    assert transcription == "गेहूं की फसल में पीलापन है"
    mock_whatsapp.download_media.assert_called_once_with("media123")
    mock_gemini_client.models.generate_content.assert_called_once()

@pytest.mark.asyncio
@patch("app.ai.transcribe.whatsapp_client")
@patch("app.ai.transcribe.ai_provider")
async def test_transcribe_whisper_success(mock_provider, mock_whatsapp):
    # Mock settings to use OpenAI
    settings.AI_PROVIDER = "openai"
    
    # Mock downloading audio file
    mock_whatsapp.download_media = AsyncMock(return_value=(b"audio_bytes", "audio/ogg"))
    
    # Mock OpenAI client
    mock_openai_client = MagicMock()
    mock_provider._openai_client = mock_openai_client
    
    mock_transcription = MagicMock()
    mock_transcription.text = "   crop problem with low yield  "
    mock_openai_client.audio.transcriptions.create.return_value = mock_transcription
    
    transcription = await voice_transcription_service.transcribe_audio("media123", "audio/ogg")
    
    assert transcription == "crop problem with low yield"
    mock_whatsapp.download_media.assert_called_once_with("media123")
    mock_openai_client.audio.transcriptions.create.assert_called_once()


# --- 3. FOLLOWUP SCHEDULER & SEQUENCE TESTS ---

@pytest.mark.asyncio
@patch("app.services.followup.followups_repo")
@patch("app.services.followup.leads_repo")
@patch("app.services.followup.send_followup", new_callable=AsyncMock)
async def test_process_lead_followup_sequence(mock_send, mock_leads_repo, mock_followups_repo):
    # Setup mock data for followups
    mock_sequence = [
        FollowupRow(id=1, user_type="farmer", lead_status="qualifying", day=1, send_after_hours=24, message_template_id="fu_farmer_q_d1", message_text_hindi="नमस्ते 🙏", next_action_if_no_reply="Wait 24h"),
        FollowupRow(id=2, user_type="farmer", lead_status="qualifying", day=2, send_after_hours=48, message_template_id="fu_farmer_q_d2", message_text_hindi="कैसे हो?", next_action_if_no_reply="Wait 24h"),
        FollowupRow(id=3, user_type="farmer", lead_status="qualifying", day=3, send_after_hours=72, message_template_id="fu_farmer_q_d3", message_text_hindi="अंतिम मौका 🌾", next_action_if_no_reply="Mark closed_lost")
    ]
    mock_followups_repo.get_sequence = AsyncMock(return_value=mock_sequence)
    
    # Test step 1: Send Day 1 followup
    lead_farmer_row = LeadFarmerRow(
        lead_id="lead_123",
        whatsapp_phone="919999999999",
        name="Ramesh",
        state="Madhya Pradesh",
        district="Ujjain",
        help_needed_for="both",
        lead_status="qualifying",
        followup_count=0,
        last_message_at=datetime.now(timezone.utc) - timedelta(hours=25),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        source_channel="whatsapp_organic"
    )
    mock_leads_repo.get_farmer = AsyncMock(return_value=lead_farmer_row)
    mock_leads_repo.upsert_farmer = AsyncMock()
    
    # Mock check idempotency on followup_service to return False
    with patch.object(followup_service, "_check_idempotency", AsyncMock(return_value=False)):
        # Run
        processed = await followup_service._process_lead_followup({
            "lead_id": "lead_123",
            "whatsapp_phone": "919999999999",
            "user_type": "farmer",
            "lead_status": "qualifying"
        })
        
        assert processed is True
        # Should send step 1 template
        mock_send.assert_called_once_with(
            phone="919999999999",
            template_id="fu_farmer_q_d1",
            fallback_text="नमस्ते 🙏",
            parameters=[]
        )
        # Should update/increment followup_count to 1 and set next_followup_at
        mock_leads_repo.upsert_farmer.assert_called_once()
        called_fields = mock_leads_repo.upsert_farmer.call_args[0][1]
        assert called_fields["followup_count"] == 1
        assert called_fields["next_followup_at"] is not None

@pytest.mark.asyncio
@patch("app.services.followup.followups_repo")
@patch("app.services.followup.leads_repo")
@patch("app.services.followup.send_followup", new_callable=AsyncMock)
async def test_process_lead_followup_final_action(mock_send, mock_leads_repo, mock_followups_repo):
    # Setup mock data for followups
    mock_sequence = [
        FollowupRow(id=1, user_type="farmer", lead_status="qualifying", day=1, send_after_hours=24, message_template_id="fu_farmer_q_d1", message_text_hindi="नमस्ते", next_action_if_no_reply="Wait 24h"),
        FollowupRow(id=2, user_type="farmer", lead_status="qualifying", day=2, send_after_hours=48, message_template_id="fu_farmer_q_d2", message_text_hindi="नमस्ते 2", next_action_if_no_reply="Wait 24h"),
        FollowupRow(id=3, user_type="farmer", lead_status="qualifying", day=3, send_after_hours=72, message_template_id="fu_farmer_q_d3", message_text_hindi="नमस्ते अंतिम", next_action_if_no_reply="Mark closed_lost")
    ]
    mock_followups_repo.get_sequence = AsyncMock(return_value=mock_sequence)
    
    # Setup: lead is at followup_count=2, about to send Day 3 followup
    lead_farmer_row = LeadFarmerRow(
        lead_id="lead_123",
        whatsapp_phone="919999999999",
        name="Ramesh",
        state="Madhya Pradesh",
        district="Ujjain",
        help_needed_for="both",
        lead_status="qualifying",
        followup_count=2,
        last_message_at=datetime.now(timezone.utc) - timedelta(hours=73),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        source_channel="whatsapp_organic"
    )
    mock_leads_repo.get_farmer = AsyncMock(return_value=lead_farmer_row)
    mock_leads_repo.upsert_farmer = AsyncMock()
    
    # Mock check idempotency on followup_service to return False
    with patch.object(followup_service, "_check_idempotency", AsyncMock(return_value=False)):
        # Run
        processed = await followup_service._process_lead_followup({
            "lead_id": "lead_123",
            "whatsapp_phone": "919999999999",
            "user_type": "farmer",
            "lead_status": "qualifying"
        })
        
        assert processed is True
        # Should send step 3 template
        mock_send.assert_called_once_with(
            phone="919999999999",
            template_id="fu_farmer_q_d3",
            fallback_text="नमस्ते अंतिम",
            parameters=[]
        )
        
        # Should update status to closed_lost
        mock_leads_repo.upsert_farmer.assert_any_call("919999999999", {
            "lead_status": "closed_lost",
            "next_followup_at": None,
            "updated_at": ANY
        })


# --- 4. TICKET SUPPORT FOLLOWUP TESTS ---

@pytest.mark.asyncio
@patch("app.services.followup.send_followup", new_callable=AsyncMock)
@patch("app.services.followup.notify")
@patch("app.services.followup.tickets_repo")
@patch("app.services.followup.supabase_client")
async def test_process_ticket_followups_open_escalates(mock_supabase, mock_tickets_repo, mock_notify, mock_send):
    # Setup mock open ticket that is 5 hours old (greater than 4 hours limit)
    # SLA is 2 hours (breached SLA)
    mock_ticket = {
        "ticket_id": "TKT-12345",
        "lead_id": "DIST-99",
        "whatsapp_phone": "919999999999",
        "user_type": "distributor_existing",
        "ticket_category": "order_status",
        "ticket_priority": "high",
        "ticket_status": "open",
        "description": "Wrong seeds delivered",
        "sla_target_hours": 2.0,
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    }
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute = MagicMock(
        return_value=MockResponse([mock_ticket])
    )
    
    mock_notify.send_to_sales_rep = AsyncMock()
    
    # Mock check idempotency on followup_service to return False (not sent)
    with patch.object(followup_service, "_check_idempotency", AsyncMock(return_value=False)):
        # Run open tickets processing
        count = await followup_service._process_ticket_followups()
        
        assert count == 1
        # Verify followup template sent
        mock_send.assert_called_once_with(
            phone="919999999999",
            template_id="fu_exdist_tkt_d1",
            fallback_text="आपकी ticket TKT-12345 हमारी टीम के पास है। हम जल्द ही update देंगे।",
            parameters=["TKT-12345"]
        )
        # Verify SLA breach escalation triggered
        mock_notify.send_to_sales_rep.assert_called_once()
        escalation_msg = mock_notify.send_to_sales_rep.call_args[0][1]
        assert "SLA Breach Escalation" in escalation_msg
        assert "TKT-12345" in escalation_msg

@pytest.mark.asyncio
@patch("app.services.followup.send_followup", new_callable=AsyncMock)
@patch("app.services.followup.tickets_repo")
@patch("app.services.followup.supabase_client")
async def test_process_ticket_followups_resolved_autocloses(mock_supabase, mock_tickets_repo, mock_send):
    # Setup mock resolved ticket that is 8 days old (greater than 7 days closure window)
    mock_ticket = {
        "ticket_id": "TKT-67890",
        "lead_id": "DIST-99",
        "whatsapp_phone": "919999999999",
        "user_type": "distributor_existing",
        "ticket_category": "stock_query",
        "ticket_priority": "medium",
        "ticket_status": "resolved",
        "description": "Stock details check",
        "resolved_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    }
    
    # Simple table.select.eq mocks for tickets query
    mock_select = MagicMock()
    mock_supabase.table.return_value.select = mock_select
    mock_eq = MagicMock()
    mock_select.return_value.eq = mock_eq
    
    # Mocking resolved query to return our ticket (first empty mock for open query, second resolved mock)
    mock_eq.return_value.execute.side_effect = [MockResponse([]), MockResponse([mock_ticket])]
    
    mock_tickets_repo.update_status = AsyncMock(return_value=True)
    
    # Mock check idempotency on followup_service to return True (already sent, so no new followup sent)
    with patch.object(followup_service, "_check_idempotency", AsyncMock(return_value=True)):
        # Run
        count = await followup_service._process_ticket_followups()
        
        # No new followups sent (since already sent)
        assert count == 0
        # Should auto-close the ticket
        mock_tickets_repo.update_status.assert_called_once_with("TKT-67890", "closed")
