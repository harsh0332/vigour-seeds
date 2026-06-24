import pytest
from unittest.mock import AsyncMock, patch
from app.models.db_models import ProductRow, RecommendationRuleRow, CropRow
from app.ai.agent import tool_find_products

@pytest.mark.asyncio
@patch("app.ai.agent.crops_repo")
@patch("app.ai.agent.rules_repo")
@patch("app.ai.agent.products_repo")
async def test_find_products_soybean_only(mock_products_repo, mock_rules_repo, mock_crops_repo):
    mock_crops_repo.list_in_catalog = AsyncMock(return_value=[
        CropRow(crop_id="CR01", crop_name_en="Soybean", crop_name_hi="सोयाबीन", in_catalog="Y"),
        CropRow(crop_id="CR02", crop_name_en="Paddy", crop_name_hi="धान", in_catalog="Y"),
    ])
    
    mock_rules_repo.match = AsyncMock(return_value=RecommendationRuleRow(
        rule_id="R900",
        crop="Any",
        crop_stage="Any",
        problem_category="unclear_problem",
        irrigation_type="Any",
        region="Any",
        recommended_product_ids="PROD_P1, PROD_S1, PROD_P2",
        next_action="send_recommendation",
        human_review_required=False
    ))
    
    mock_products_repo.get_by_id = AsyncMock(side_effect=lambda pid: {
        "PROD_P1": ProductRow(
            product_id="PROD_P1",
            variety_name="Vigour 087",
            crop="Paddy",
            duration_days="120",
            mrp_inr=200.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="10 kg",
            approved_for_recommendation="Y"
        ),
        "PROD_S1": ProductRow(
            product_id="PROD_S1",
            variety_name="Vigour 335",
            crop="Soybean",
            duration_days="95",
            mrp_inr=150.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="20 kg",
            approved_for_recommendation="Y"
        ),
        "PROD_P2": ProductRow(
            product_id="PROD_P2",
            variety_name="Vigour Bajirao",
            crop="Paddy",
            duration_days="125",
            mrp_inr=210.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="10 kg",
            approved_for_recommendation="Y"
        )
    }.get(pid))
    
    results = await tool_find_products("Soybean", "unclear_problem")
    variety_names = [p["variety_name"] for p in results]
    assert "Vigour 335" in variety_names
    assert "Vigour 087" not in variety_names
    assert "Vigour Bajirao" not in variety_names
    for r in results:
        assert r["crop"].lower() == "soybean"

@pytest.mark.asyncio
@patch("app.ai.agent.crops_repo")
@patch("app.ai.agent.rules_repo")
@patch("app.ai.agent.products_repo")
async def test_find_products_paddy_only(mock_products_repo, mock_rules_repo, mock_crops_repo):
    mock_crops_repo.list_in_catalog = AsyncMock(return_value=[
        CropRow(crop_id="CR01", crop_name_en="Soybean", crop_name_hi="सोयाबीन", in_catalog="Y"),
        CropRow(crop_id="CR02", crop_name_en="Paddy", crop_name_hi="धान", in_catalog="Y"),
    ])
    
    mock_rules_repo.match = AsyncMock(return_value=RecommendationRuleRow(
        rule_id="R900",
        crop="Any",
        crop_stage="Any",
        problem_category="unclear_problem",
        irrigation_type="Any",
        region="Any",
        recommended_product_ids="PROD_P1, PROD_S1, PROD_P2",
        next_action="send_recommendation",
        human_review_required=False
    ))
    
    mock_products_repo.get_by_id = AsyncMock(side_effect=lambda pid: {
        "PROD_P1": ProductRow(
            product_id="PROD_P1",
            variety_name="Vigour 087",
            crop="Paddy",
            duration_days="120",
            mrp_inr=200.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="10 kg",
            approved_for_recommendation="Y"
        ),
        "PROD_S1": ProductRow(
            product_id="PROD_S1",
            variety_name="Vigour 335",
            crop="Soybean",
            duration_days="95",
            mrp_inr=150.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="20 kg",
            approved_for_recommendation="Y"
        ),
        "PROD_P2": ProductRow(
            product_id="PROD_P2",
            variety_name="Vigour Bajirao",
            crop="Paddy",
            duration_days="125",
            mrp_inr=210.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="10 kg",
            approved_for_recommendation="Y"
        )
    }.get(pid))
    
    results = await tool_find_products("Paddy", "unclear_problem")
    variety_names = [p["variety_name"] for p in results]
    assert "Vigour 087" in variety_names
    assert "Vigour Bajirao" in variety_names
    assert "Vigour 335" not in variety_names
    for r in results:
        assert r["crop"].lower() == "paddy"

@pytest.mark.asyncio
@patch("app.ai.agent.crops_repo")
@patch("app.ai.agent.rules_repo")
@patch("app.ai.agent.products_repo")
async def test_find_products_by_crop_fallback_only(mock_products_repo, mock_rules_repo, mock_crops_repo):
    mock_crops_repo.list_in_catalog = AsyncMock(return_value=[
        CropRow(crop_id="CR01", crop_name_en="Soybean", crop_name_hi="सोयाबीन", in_catalog="Y")
    ])
    
    mock_rules_repo.match = AsyncMock(return_value=None)
    
    mock_products_repo.list_by_crop = AsyncMock(return_value=[
        ProductRow(
            product_id="PROD_S1",
            variety_name="Vigour 335",
            crop="Soybean",
            duration_days="95",
            mrp_inr=150.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="20 kg",
            approved_for_recommendation="Y"
        ),
        ProductRow(
            product_id="PROD_P1",
            variety_name="Vigour 087",
            crop="Paddy",
            duration_days="120",
            mrp_inr=200.0,
            key_traits="traits",
            pest_disease_tolerance="tolerant",
            pack_size="10 kg",
            approved_for_recommendation="Y"
        )
    ])
    
    results = await tool_find_products("Soybean", "some_problem")
    variety_names = [p["variety_name"] for p in results]
    assert "Vigour 335" in variety_names
    assert "Vigour 087" not in variety_names
    for r in results:
        assert r["crop"].lower() == "soybean"

@pytest.mark.asyncio
@patch("app.ai.agent.crops_repo")
@patch("app.ai.agent.rules_repo")
@patch("app.ai.agent.products_repo")
async def test_find_products_zero_approved_products(mock_products_repo, mock_rules_repo, mock_crops_repo):
    mock_crops_repo.list_in_catalog = AsyncMock(return_value=[
        CropRow(crop_id="CR03", crop_name_en="Coriander", crop_name_hi="धनिया", in_catalog="Y")
    ])
    
    mock_rules_repo.match = AsyncMock(return_value=None)
    mock_products_repo.list_by_crop = AsyncMock(return_value=[])
    
    results = await tool_find_products("Coriander", "any_problem")
    assert results == []
