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

from app.ai.vision import vision_service

@pytest.mark.asyncio
@patch("app.ai.vision.ai_provider")
async def test_vision_service_diagnose_success(mock_provider):
    mock_response = """
    {
      "problem_category": "pest_attack",
      "secondary_possibilities": ["sucking_pest"],
      "severity": "high",
      "confidence": 0.85,
      "visible_symptoms_hindi": "पत्तियों पर छेद और सुंडी दिख रही है।",
      "needs_human": false
    }
    """
    mock_provider.complete = AsyncMock(return_value=mock_response)
    
    context = {
        "crop_name_hi": "सोयाबीन",
        "crop_name_en": "Soybean",
        "crop_stage": "flowering",
        "district": "Ujjain",
        "irrigation": "Irrigated",
        "user_complaint": "पत्तियों में छेद हैं"
    }
    
    res = await vision_service.diagnose(b"fake_image_bytes", "image/jpeg", context)
    
    assert res is not None
    assert res["problem_category"] == "pest_attack"
    assert res["confidence"] == 0.85
    assert res["severity"] == "high"
    assert res["needs_human"] is False
    
    mock_provider.complete.assert_called_once()
    kwargs = mock_provider.complete.call_args[1]
    assert "You are an agronomy assistant" in kwargs["system"]
    assert "सोयाबीन" in kwargs["user"]
    assert "Ujjain" in kwargs["user"]

@pytest.mark.asyncio
@patch("app.ai.vision.ai_provider")
async def test_vision_service_diagnose_failure(mock_provider):
    mock_provider.complete = AsyncMock(side_effect=Exception("Connection timed out"))
    
    context = {
        "crop_name_hi": "सोयाबीन",
        "crop_name_en": "Soybean"
    }
    
    res = await vision_service.diagnose(b"fake_image_bytes", "image/jpeg", context)
    
    assert res["problem_category"] == "unclear"
    assert res["confidence"] == 0.0
    assert res["needs_human"] is True
