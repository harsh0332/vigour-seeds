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

from app.services.ticketing import ticketing
from app.models.db_models import TicketRow, DistributorActiveRow, SessionRow
from app.flows.distributor_existing import existing_distributor_flow_handler
from app.whatsapp.models import ParsedMessage

@pytest.mark.asyncio
@patch("app.services.ticketing.tickets_repo")
@patch("app.services.ticketing.distributors_repo")
@patch("app.services.ticketing.ai_provider")
@patch("app.services.ticketing.notify")
async def test_create_ticket_dispatch_delay(mock_notify, mock_ai, mock_dist_repo, mock_tickets_repo):
    # Mock AI subject summarization
    mock_ai.complete = AsyncMock(return_value="Dispatch Delay for VIG-4521")
    
    # Mock active distributor rep lookup
    mock_dist_repo.get_active_by_phone = AsyncMock(return_value=DistributorActiveRow(
        distributor_id="DIST001",
        whatsapp_phone="919876543210",
        contact_name="Ramesh Gupta",
        shop_name="Indore Beej House",
        state="Madhya Pradesh",
        district="Indore",
        territory_code="MP01",
        onboarded_date="2026-01-01",
        assigned_sales_rep="Rajesh Sharma",
        assigned_sales_rep_phone="919999999999",
        active_status="active"
    ))
    
    # Mock ticket repository create
    mock_created_ticket = TicketRow(
        ticket_id="TKT-DISPATCH",
        lead_id="DIST001",
        whatsapp_phone="919876543210",
        user_type="distributor_existing",
        ticket_category="dispatch_delay",
        ticket_priority="high",
        ticket_status="open",
        subject="Dispatch Delay for VIG-4521",
        description="order VIG-4521 nahi aaya",
        assigned_team="logistics",
        assigned_person="Rajesh Sharma",
        sla_target_hours=24.0,
        created_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    mock_tickets_repo.create = AsyncMock(return_value=mock_created_ticket)
    mock_notify.notify_team = AsyncMock()
    
    ticket = await ticketing.create_ticket(
        lead_id="DIST001",
        phone="919876543210",
        category="डिस्पैच",
        description="order VIG-4521 nahi aaya"
    )
    
    assert ticket.ticket_id == "TKT-DISPATCH"
    assert ticket.ticket_category == "dispatch_delay"
    assert ticket.ticket_priority == "high"
    assert ticket.sla_target_hours == 24.0
    assert ticket.assigned_team == "logistics"
    assert ticket.assigned_person == "Rajesh Sharma"
    assert ticket.subject == "Dispatch Delay for VIG-4521"
    
    # Verify AI call occurred
    mock_ai.complete.assert_called_once()
    
    # Verify repository call occurred with expected dict
    mock_tickets_repo.create.assert_called_once()
    passed_dict = mock_tickets_repo.create.call_args[0][0]
    assert passed_dict["ticket_category"] == "dispatch_delay"
    assert passed_dict["ticket_priority"] == "high"
    assert passed_dict["assigned_team"] == "logistics"
    
    # Verify notification triggered to team
    mock_notify.notify_team.assert_called_once_with("logistics", mock_created_ticket)

@pytest.mark.asyncio
@patch("app.services.ticketing.tickets_repo")
@patch("app.services.ticketing.distributors_repo")
@patch("app.services.ticketing.ai_provider")
@patch("app.services.ticketing.notify")
async def test_create_ticket_order_status(mock_notify, mock_ai, mock_dist_repo, mock_tickets_repo):
    mock_ai.complete = AsyncMock(return_value="Order Status Query")
    mock_dist_repo.get_active_by_phone = AsyncMock(return_value=None)
    
    mock_created_ticket = TicketRow(
        ticket_id="TKT-ORDER",
        lead_id="LEAD002",
        whatsapp_phone="919876543211",
        user_type="distributor_existing",
        ticket_category="order_status",
        ticket_priority="medium",
        ticket_status="open",
        subject="Order Status Query",
        description="Mera order confirm hua ya nahi?",
        assigned_team="sales",
        assigned_person=None,
        sla_target_hours=24.0,
        created_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    mock_tickets_repo.create = AsyncMock(return_value=mock_created_ticket)
    mock_notify.notify_team = AsyncMock()
    
    ticket = await ticketing.create_ticket(
        lead_id="LEAD002",
        phone="919876543211",
        category="ऑर्डर स्टेटस",
        description="Mera order confirm hua ya nahi?"
    )
    
    assert ticket.ticket_category == "order_status"
    assert ticket.ticket_priority == "medium"
    assert ticket.sla_target_hours == 24.0
    assert ticket.assigned_team == "sales"
    assert ticket.assigned_person is None
    
    mock_notify.notify_team.assert_called_once_with("sales", mock_created_ticket)

@pytest.mark.asyncio
@patch("app.flows.distributor_existing.distributors_repo")
@patch("app.flows.distributor_existing.whatsapp_client")
@patch("app.flows.distributor_existing.session_service")
@patch("app.flows.distributor_existing.ticketing")
async def test_existing_distributor_flow_ticketing(mock_ticketing, mock_sess_service, mock_wa_client, mock_dist_repo):
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
    mock_wa_client.send_text = AsyncMock()
    mock_wa_client.send_list = AsyncMock()
    mock_sess_service.set_step = AsyncMock()
    mock_sess_service.patch_collected = AsyncMock()
    mock_sess_service.reset = AsyncMock()
    
    session = SessionRow(
        whatsapp_phone="918888888888",
        current_flow="distributor_existing",
        current_step="ticket_init",
        collected_json={},
        last_message_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    
    # 1. Initialize step -> Greet and send list of categories
    msg1 = ParsedMessage(wamid="w1", from_phone="918888888888", type="text", text="Help", timestamp="1718563800")
    await existing_distributor_flow_handler.handle_message(msg1, session)
    
    mock_sess_service.set_step.assert_called_once_with("918888888888", "F_DIST_EX_CAT")
    mock_wa_client.send_list.assert_called_once()
    
    # 2. Select category (e.g. order_status) -> Move to F_DIST_EX_DESC
    session.current_step = "F_DIST_EX_CAT"
    msg2 = ParsedMessage(wamid="w2", from_phone="918888888888", type="list_reply", list_id="order_status", timestamp="1718563800")
    await existing_distributor_flow_handler.handle_message(msg2, session)
    
    mock_sess_service.patch_collected.assert_called_once_with("918888888888", {"ticket_category": "order_status"})
    mock_sess_service.set_step.assert_any_call("918888888888", "F_DIST_EX_DESC")
    mock_wa_client.send_text.assert_called_with("918888888888", "कृपया अपनी समस्या या पूछताछ का विवरण (Description) विस्तार से लिखें, ताकि हमारे प्रतिनिधि आपकी बेहतर मदद कर सकें:")
    
    # 3. Send Description -> Create ticket, confirm, and reset
    session.current_step = "F_DIST_EX_DESC"
    session.collected_json = {"ticket_category": "order_status"}
    msg3 = ParsedMessage(wamid="w3", from_phone="918888888888", type="text", text="order VIG-4521 nahi aaya", timestamp="1718563800")
    
    # Mock created ticket
    mock_ticket = TicketRow(
        ticket_id="TKT-EX-123",
        lead_id="DST001",
        whatsapp_phone="918888888888",
        user_type="distributor_existing",
        ticket_category="order_status",
        ticket_priority="medium",
        ticket_status="open",
        subject="Order query",
        description="order VIG-4521 nahi aaya",
        assigned_team="sales",
        assigned_person="Rajesh Kumar",
        sla_target_hours=24.0,
        created_at="2026-06-16T12:00:00",
        updated_at="2026-06-16T12:00:00"
    )
    mock_ticketing.create_ticket = AsyncMock(return_value=mock_ticket)
    
    await existing_distributor_flow_handler.handle_message(msg3, session)
    
    mock_ticketing.create_ticket.assert_called_once_with(
        lead_id="DST001",
        phone="918888888888",
        category="order_status",
        description="order VIG-4521 nahi aaya"
    )
    mock_sess_service.reset.assert_called_once_with("918888888888")
    
    # Confirm last message sent contains ticket details
    confirm_text = mock_wa_client.send_text.call_args_list[-1][0][1]
    assert "TKT-EX-123" in confirm_text
    assert "24" in confirm_text
