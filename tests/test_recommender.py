import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Set mock env vars before any imports
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"

from app.services.recommender import recommender
from app.services.dealer_locator import dealer_locator
from app.models.db_models import RecommendationRuleRow, ProductRow, CropRow, RegionRow

class MockResponse:
    def __init__(self, data):
        self.data = data

# Mock response classes for Supabase client
@pytest.mark.asyncio
@patch("app.services.recommender.crops_repo")
@patch("app.services.recommender.rules_repo")
@patch("app.services.recommender.products_repo")
@patch("app.services.recommender.leads_repo")
@patch("app.services.recommender.whatsapp_client")
async def test_resolve_soybean_sowing_r002(mock_wa_client, mock_leads_repo, mock_products_repo, mock_rules_repo, mock_crops_repo):
    # Setup mocks
    mock_crops_repo.get_by_id = AsyncMock(return_value=CropRow(
        crop_id="CR01",
        crop_name_en="Soybean",
        crop_name_hi="सोयाबीन",
        in_catalog="Y"
    ))
    
    mock_rules_repo.match = AsyncMock(return_value=RecommendationRuleRow(
        rule_id="R002",
        crop="Soybean",
        crop_stage="sowing",
        problem_category="-",
        irrigation_type="Rainfed/Irrigated",
        region="MP",
        recommended_product_ids="PROD_S1, PROD_S2",
        next_action="send_recommendation",
        human_review_required=False
    ))
    
    # PROD_S1 has price, PROD_S2 does not (mrp_inr=None)
    mock_products_repo.get_by_id = AsyncMock(side_effect=lambda pid: {
        "PROD_S1": ProductRow(
            product_id="PROD_S1",
            variety_name="Vigour 335",
            crop="Soybean",
            duration_days="95",
            mrp_inr=150.0,
            key_traits="उच्च उपज क्षमता",
            pest_disease_tolerance="पीला मोज़ेक सहनशील",
            pack_size="20 kg",
            approved_for_recommendation="Y"
        ),
        "PROD_S2": ProductRow(
            product_id="PROD_S2",
            variety_name="Vigour 9560",
            crop="Soybean",
            duration_days="90",
            mrp_inr=None,
            key_traits="कम अवधि में पकने वाली",
            pest_disease_tolerance="सूखा सहनशील",
            pack_size=None,
            approved_for_recommendation="Y"
        )
    }.get(pid))
    
    mock_leads_repo.upsert_farmer = AsyncMock()
    mock_wa_client.send_text = AsyncMock()
    mock_wa_client.send_buttons = AsyncMock()
    
    collected = {
        "current_crop": "CR01",
        "crop_stage": "sowing",
        "state": "Madhya Pradesh",
        "district": "Indore",
        "total_land": 5.0
    }
    
    await recommender.resolve("919999999999", collected)
    
    # Check that crop detail lookup occurred
    mock_crops_repo.get_by_id.assert_called_once_with("CR01")
    
    # Check that rules_repo.match was called
    mock_rules_repo.match.assert_called_once_with("Soybean", "sowing", "-", "Irrigated", "MP")
    
    # Check that send_text was called for header, cards, and footer
    send_text_calls = [c[0][1] for c in mock_wa_client.send_text.call_args_list]
    
    assert any("आपकी सोयाबीन (बुवाई) के लिए हमारी सलाह" in text for text in send_text_calls)
    assert any("Vigour 335" in text for text in send_text_calls)
    assert any("150.0 रुपये" in text for text in send_text_calls)
    assert any("Vigour 9560" in text for text in send_text_calls)
    assert any("दर व कीमत के लिए नज़दीकी डीलर से पूछें।" in text for text in send_text_calls)
    assert any("कोई भी दवा/खुराक डालने से पहले" in text for text in send_text_calls)
    
    # Check that interactive buttons were sent
    mock_wa_client.send_buttons.assert_called_once()
    buttons_arg = mock_wa_client.send_buttons.call_args[0][2]
    assert any(b["id"] == "ACT_DEALER" for b in buttons_arg)
    assert any(b["id"] == "ACT_CALLBACK" for b in buttons_arg)
    assert any(b["id"] == "ACT_AGRONOMIST" for b in buttons_arg)
    
    # Check that lead was updated in database
    mock_leads_repo.upsert_farmer.assert_called_once()
    upserted_fields = mock_leads_repo.upsert_farmer.call_args[0][1]
    assert upserted_fields["lead_status"] == "recommendation_sent"
    assert upserted_fields["next_action"] == "send_recommendation"
    assert "PROD_S1" in upserted_fields["recommended_product_ids"]
    assert "PROD_S2" in upserted_fields["recommended_product_ids"]

@pytest.mark.asyncio
@patch("app.services.recommender.crops_repo")
@patch("app.services.recommender.rules_repo")
@patch("app.services.recommender.products_repo")
@patch("app.services.recommender.leads_repo")
@patch("app.services.recommender.whatsapp_client")
async def test_resolve_okra_sowing_r050(mock_wa_client, mock_leads_repo, mock_products_repo, mock_rules_repo, mock_crops_repo):
    mock_crops_repo.get_by_id = AsyncMock(return_value=CropRow(
        crop_id="CR15",
        crop_name_en="Okra",
        crop_name_hi="भिंडी",
        in_catalog="Y"
    ))
    
    mock_rules_repo.match = AsyncMock(return_value=RecommendationRuleRow(
        rule_id="R050",
        crop="Okra",
        crop_stage="sowing",
        problem_category="-",
        irrigation_type="Rainfed/Irrigated",
        region="Any",
        recommended_product_ids="OKR003",
        next_action="send_recommendation",
        human_review_required=False
    ))
    
    mock_products_repo.get_by_id = AsyncMock(return_value=ProductRow(
        product_id="OKR003",
        variety_name="Vigour Divya",
        crop="Okra",
        duration_days="85",
        mrp_inr=400.0,
        key_traits="पीला मोज़ेक वायरस (YVMV) प्रतिरोधी",
        pest_disease_tolerance="उच्च रोग प्रतिरोधक",
        pack_size="1 kg",
        approved_for_recommendation="Y"
    ))
    
    mock_leads_repo.upsert_farmer = AsyncMock()
    mock_wa_client.send_text = AsyncMock()
    mock_wa_client.send_buttons = AsyncMock()
    
    collected = {
        "current_crop": "CR15",
        "crop_stage": "sowing",
        "state": "Maharashtra",
        "district": "Pune"
    }
    
    await recommender.resolve("919999999999", collected)
    
    send_text_calls = [c[0][1] for c in mock_wa_client.send_text.call_args_list]
    assert any("आपकी भिंडी (बुवाई) के लिए हमारी सलाह" in text for text in send_text_calls)
    assert any("Vigour Divya" in text for text in send_text_calls)
    assert any("400.0 रुपये" in text for text in send_text_calls)

@pytest.mark.asyncio
@patch("app.services.recommender.crops_repo")
@patch("app.services.recommender.rules_repo")
@patch("app.services.recommender.leads_repo")
@patch("app.services.recommender.whatsapp_client")
async def test_resolve_soybean_flowering_r003_escalation(mock_wa_client, mock_leads_repo, mock_rules_repo, mock_crops_repo):
    mock_crops_repo.get_by_id = AsyncMock(return_value=CropRow(
        crop_id="CR01",
        crop_name_en="Soybean",
        crop_name_hi="सोयाबीन",
        in_catalog="Y"
    ))
    
    # Rule R003 has escalate_agronomist action
    mock_rules_repo.match = AsyncMock(return_value=RecommendationRuleRow(
        rule_id="R003",
        crop="Soybean",
        crop_stage="flowering",
        problem_category="pest_attack",
        irrigation_type="Rainfed/Irrigated",
        region="MP",
        recommended_product_ids="",
        next_action="escalate_agronomist",
        human_review_required=True
    ))
    
    mock_leads_repo.upsert_farmer = AsyncMock()
    mock_wa_client.send_text = AsyncMock()
    
    collected = {
        "current_crop": "CR01",
        "crop_stage": "flowering",
        "problem_category": ["pest_attack"],
        "state": "Madhya Pradesh",
        "district": "Indore"
    }
    
    await recommender.resolve("919999999999", collected)
    
    # Verify agronomist escalation
    mock_leads_repo.upsert_farmer.assert_called_once()
    upserted_fields = mock_leads_repo.upsert_farmer.call_args[0][1]
    assert upserted_fields["lead_status"] == "escalated"
    assert upserted_fields["escalated_to_human"] is True
    assert upserted_fields["next_action"] == "escalate_agronomist"
    
    # Verify escalation message sent
    mock_wa_client.send_text.assert_called_once_with(
        "919999999999",
        "आपकी फसल की समस्या थोड़ी जटिल लग रही है 🌾 हमारे कृषि विशेषज्ञ (एग्रोनॉमिस्ट) जल्द ही आपसे संपर्क करेंगे। तब तक चिंता न करें।"
    )

@pytest.mark.asyncio
@patch("app.services.recommender.crops_repo")
@patch("app.services.recommender.rules_repo")
@patch("app.services.recommender.products_repo")
@patch("app.services.recommender.leads_repo")
@patch("app.services.recommender.whatsapp_client")
async def test_unapproved_variety_filtering(mock_wa_client, mock_leads_repo, mock_products_repo, mock_rules_repo, mock_crops_repo):
    mock_crops_repo.get_by_id = AsyncMock(return_value=CropRow(
        crop_id="CR01",
        crop_name_en="Soybean",
        crop_name_hi="सोयाबीन",
        in_catalog="Y"
    ))
    
    mock_rules_repo.match = AsyncMock(return_value=RecommendationRuleRow(
        rule_id="R002",
        crop="Soybean",
        crop_stage="sowing",
        problem_category="-",
        irrigation_type="Rainfed/Irrigated",
        region="MP",
        recommended_product_ids="PROD_APPROVED, PROD_UNAPPROVED",
        next_action="send_recommendation",
        human_review_required=False
    ))
    
    # PROD_APPROVED is approved_for_recommendation='Y'
    # PROD_UNAPPROVED is approved_for_recommendation='N'
    mock_products_repo.get_by_id = AsyncMock(side_effect=lambda pid: {
        "PROD_APPROVED": ProductRow(
            product_id="PROD_APPROVED",
            variety_name="Vigour Approved",
            crop="Soybean",
            duration_days="95",
            mrp_inr=150.0,
            key_traits="High yield",
            pest_disease_tolerance="Standard",
            pack_size="20 kg",
            approved_for_recommendation="Y"
        ),
        "PROD_UNAPPROVED": ProductRow(
            product_id="PROD_UNAPPROVED",
            variety_name="Vigour Unapproved",
            crop="Soybean",
            duration_days="90",
            mrp_inr=200.0,
            key_traits="Early maturity",
            pest_disease_tolerance="Standard",
            pack_size="20 kg",
            approved_for_recommendation="N"
        )
    }.get(pid))
    
    mock_leads_repo.upsert_farmer = AsyncMock()
    mock_wa_client.send_text = AsyncMock()
    mock_wa_client.send_buttons = AsyncMock()
    
    collected = {
        "current_crop": "CR01",
        "crop_stage": "sowing",
        "state": "Madhya Pradesh",
        "district": "Indore"
    }
    
    await recommender.resolve("919999999999", collected)
    
    # Check that only approved product is present in send_text calls
    send_text_calls = [c[0][1] for c in mock_wa_client.send_text.call_args_list]
    assert any("Vigour Approved" in text for text in send_text_calls)
    assert not any("Vigour Unapproved" in text for text in send_text_calls)

@pytest.mark.asyncio
@patch("app.services.dealer_locator.supabase_client")
async def test_dealer_locator_indore_depot_lookup(mock_supabase):
    # Mock regions query
    mock_region_data = {
        "region_id": "REG01",
        "state": "Madhya Pradesh",
        "state_code": "MP",
        "nearest_depot": "Indore Depot",
        "sales_rep_name": "Rajesh Sharma",
        "sales_rep_phone": "9876543210",
        "agronomist_name": "Amit Patel",
        "agronomist_phone": "9988776655",
        "is_active": "Y"
    }
    
    # Mock distributors query
    mock_dealers_data = [
        {
            "distributor_id": "D001",
            "shop_name": "Vigour Seeds Indore",
            "contact_name": "Ramesh Gupta",
            "whatsapp_phone": "9123456780"
        },
        {
            "distributor_id": "D002",
            "shop_name": "Kalyan Beej Bhandar",
            "contact_name": "Suresh Kalyan",
            "whatsapp_phone": "9876123450"
        }
    ]
    
    # Setup chain: supabase_client.table(table_name).select().eq().execute()
    mock_regions_execute = MagicMock(return_value=MockResponse([mock_region_data]))
    mock_distributors_execute = MagicMock(return_value=MockResponse(mock_dealers_data))
    
    # We need a routing mechanism to mock responses based on table name
    def table_mock_routing(table_name):
        mock_table = MagicMock()
        if table_name == "regions":
            mock_table.select.return_value.eq.return_value.execute = mock_regions_execute
        elif table_name == "distributors_active":
            mock_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute = mock_distributors_execute
        return mock_table
        
    mock_supabase.table.side_effect = table_mock_routing
    
    loc = await dealer_locator.locate("Madhya Pradesh", "Indore")
    
    assert loc["depot"] == "Indore Depot"
    assert loc["sales_rep_name"] == "Rajesh Sharma"
    assert loc["sales_rep_phone"] == "9876543210"
    assert loc["agronomist_name"] == "Amit Patel"
    assert loc["agronomist_phone"] == "9988776655"
    assert len(loc["dealers"]) == 2
    assert loc["dealers"][0]["shop_name"] == "Vigour Seeds Indore"
    assert loc["dealers"][1]["shop_name"] == "Kalyan Beej Bhandar"
