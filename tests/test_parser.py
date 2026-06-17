import os
import pytest
from unittest.mock import MagicMock, patch

# Set mock env variables
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

from app.whatsapp.parser import whatsapp_parser
from app.whatsapp.models import ParsedMessage

class MockResponse:
    def __init__(self, data):
        self.data = data

@pytest.mark.asyncio
@patch("app.whatsapp.parser.supabase_client")
@patch("app.whatsapp.parser.conversations_repo")
async def test_parse_message_new(mock_conv_repo, mock_supabase):
    # Simulate message not processed yet
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MockResponse([])
    
    # Mock log response
    mock_conv_repo.log = MagicMock()
    
    message_payload = {
        "from": "919999999999",
        "id": "wamid.HBgLOTE5OTk5OTk5OTk5FhUCABEYEzg0RDJDMTBGRDREMkREQzRFQgA=",
        "timestamp": "1718563800",
        "type": "text",
        "text": {"body": "hello vapour seeds"}
    }
    contact_payload = {
        "profile": {"name": "Amit Kumar"},
        "wa_id": "919999999999"
    }
    
    parsed = await whatsapp_parser.parse_message(message_payload, contact_payload)
    
    assert parsed is not None
    assert parsed.wamid == "wamid.HBgLOTE5OTk5OTk5OTk5FhUCABEYEzg0RDJDMTBGRDREMkREQzRFQgA="
    assert parsed.from_phone == "919999999999"
    assert parsed.profile_name == "Amit Kumar"
    assert parsed.type == "text"
    assert parsed.text == "hello vapour seeds"
    
    # Verify logged to conversations
    mock_conv_repo.log.assert_called_once()

@pytest.mark.asyncio
@patch("app.whatsapp.parser.supabase_client")
@patch("app.whatsapp.parser.conversations_repo")
async def test_parse_message_duplicate(mock_conv_repo, mock_supabase):
    # Simulate message already processed
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MockResponse([{"message_id": "wamid.123"}])
    
    mock_conv_repo.log = MagicMock()
    
    message_payload = {
        "from": "919999999999",
        "id": "wamid.123",
        "timestamp": "1718563800",
        "type": "text",
        "text": {"body": "duplicate message"}
    }
    
    parsed = await whatsapp_parser.parse_message(message_payload)
    
    # Must skip duplicate and return None
    assert parsed is None
    mock_conv_repo.log.assert_not_called()
