import os
import pytest
from unittest.mock import MagicMock, patch

# Set mock env vars before any imports
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

from app.db.repositories.crops import crops_repo
from app.db.repositories.products import products_repo
from app.db.repositories.rules import rules_repo
from app.db.repositories.leads import leads_repo
from app.db.repositories.distributors import distributors_repo
from app.db.repositories.conversations import conversations_repo
from app.db.repositories.tickets import tickets_repo
from app.db.repositories.followups import followups_repo
from app.db.repositories.regions import regions_repo
from app.db.repositories.sessions import sessions_repo

from app.models.db_models import RecommendationRuleRow, ProductRow

# Mock response classes for Supabase client
class MockResponse:
    def __init__(self, data):
        self.data = data

@pytest.mark.asyncio
@patch("app.db.repositories.rules.supabase_client")
async def test_rules_repo_match_success(mock_supabase):
    # Setup mock data for recommendation rules
    mock_rules = [
        {
            "rule_id": "R001",
            "crop": "Soybean",
            "crop_stage": "sowing",
            "problem_category": "-",
            "irrigation_type": "Rainfed/Irrigated",
            "region": "MP, MH, RJ",
            "recommended_product_ids": "SBN001, SBN002",
            "next_action": "send_recommendation",
            "human_review_required": False,
            "notes": "Standard sowing"
        },
        {
            "rule_id": "R901",
            "crop": "Any",
            "crop_stage": "Any",
            "problem_category": "low_ai_confidence",
            "irrigation_type": "Any",
            "region": "Any",
            "recommended_product_ids": None,
            "next_action": "escalate_agronomist",
            "human_review_required": True,
            "notes": "Low AI confidence fallback"
        },
        {
            "rule_id": "R902",
            "crop": "Any",
            "crop_stage": "Any",
            "problem_category": "safety_critical",
            "irrigation_type": "Any",
            "region": "Any",
            "recommended_product_ids": None,
            "next_action": "escalate_agronomist",
            "human_review_required": True,
            "notes": "Safety critical fallback"
        }
    ]
    
    # Mock chain: supabase_client.table().select().execute()
    mock_execute = MagicMock(return_value=MockResponse(mock_rules))
    mock_select = MagicMock(return_value=MagicMock(execute=mock_execute))
    mock_table = MagicMock(return_value=MagicMock(select=mock_select))
    mock_supabase.table = mock_table

    # Test case 1: Standard Soybean sowing rule R001
    rule1 = await rules_repo.match("Soybean", "sowing", "none", "Irrigated", "MP")
    assert rule1 is not None
    assert rule1.rule_id == "R001"
    assert rule1.next_action == "send_recommendation"

    # Test case 2: Fallback low_ai_confidence rule R901
    rule2 = await rules_repo.match("Soybean", "vegetative", "low_ai_confidence", "Irrigated", "MP")
    assert rule2 is not None
    assert rule2.rule_id == "R901"
    assert rule2.human_review_required is True

    # Test case 3: Fallback safety_critical rule R902
    rule3 = await rules_repo.match("Wheat", "flowering", "safety_critical", "Rainfed", "UP")
    assert rule3 is not None
    assert rule3.rule_id == "R902"
    assert rule3.human_review_required is True

@pytest.mark.asyncio
@patch("app.db.repositories.products.supabase_client")
async def test_products_repo_list_approved_for(mock_supabase):
    mock_products = [
        {
            "product_id": "SBN001",
            "crop": "Soybean",
            "approved_for_recommendation": "Y",
            "target_region": "MP, MH, RJ"
        },
        {
            "product_id": "SBN002",
            "crop": "Soybean",
            "approved_for_recommendation": "Y",
            "target_region": "MP, MH"
        }
    ]
    
    # Mock chain: supabase_client.table().select().ilike().eq().execute()
    mock_execute = MagicMock(return_value=MockResponse(mock_products))
    mock_eq = MagicMock(return_value=MagicMock(execute=mock_execute))
    mock_ilike = MagicMock(return_value=MagicMock(eq=mock_eq))
    mock_select = MagicMock(return_value=MagicMock(ilike=mock_ilike))
    mock_table = MagicMock(return_value=MagicMock(select=mock_select))
    mock_supabase.table = mock_table

    # Test that list_approved_for returns only approved products
    prods = await products_repo.list_approved_for("Soybean", "sowing", "none", "MP")
    assert len(prods) == 2
    assert prods[0].product_id == "SBN001"
    assert prods[0].approved_for_recommendation == "Y"

@pytest.mark.asyncio
@patch("app.db.repositories.sessions.supabase_client")
async def test_sessions_repo_lifecycle(mock_supabase):
    session_data = {
        "whatsapp_phone": "919999999999",
        "current_flow": "farmer_onboarding",
        "current_step": "F_NAME",
        "collected_json": {"name": "Ramesh"},
        "last_message_at": "2026-06-16T12:00:00",
        "updated_at": "2026-06-16T12:00:00"
    }

    # Mock get, insert, update, delete chains
    mock_t = MagicMock()
    mock_supabase.table.return_value = mock_t

    # Mock select
    mock_select = MagicMock()
    mock_t.select.return_value = mock_select
    mock_select_eq = MagicMock()
    mock_select.eq.return_value = mock_select_eq
    mock_select_eq.execute.return_value = MockResponse([session_data])

    # Mock update
    mock_update = MagicMock()
    mock_t.update.return_value = mock_update
    mock_update_eq = MagicMock()
    mock_update.eq.return_value = mock_update_eq
    mock_update_eq.execute.return_value = MockResponse([session_data])

    # Mock insert
    mock_insert = MagicMock()
    mock_t.insert.return_value = mock_insert
    mock_insert.execute.return_value = MockResponse([session_data])

    # Mock delete
    mock_delete = MagicMock()
    mock_t.delete.return_value = mock_delete
    mock_delete_eq = MagicMock()
    mock_delete.eq.return_value = mock_delete_eq
    mock_delete_eq.execute.return_value = MockResponse([session_data])

    # 1. Get session
    session = await sessions_repo.get("919999999999")
    assert session is not None
    assert session.whatsapp_phone == "919999999999"
    assert session.current_step == "F_NAME"

    # 2. Upsert session patch
    patched_session = await sessions_repo.upsert("919999999999", {"current_step": "F_LOCATION"})
    assert patched_session is not None
