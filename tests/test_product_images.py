import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from conftest import in_memory_db, mock_whatsapp_client, mock_ai_provider
from app.db.repositories.sessions import sessions_repo
from app.whatsapp.models import ParsedMessage
from app.flows.router import conversation_router
from app.whatsapp.client import whatsapp_client
from app.core.errors import MetaApiException
from app.whatsapp.client import WhatsAppClient

def make_mock_complete_sequence(json_responses):
    """
    Returns an AsyncMock that returns the given JSON responses in sequence.
    """
    call_idx = 0
    async def mock_call(system, user, json_mode=False):
        nonlocal call_idx
        if call_idx < len(json_responses):
            res = json_responses[call_idx]
            call_idx += 1
            if isinstance(res, dict):
                return json.dumps(res)
            return res
        return json.dumps({"action": "reply", "message": "नमस्ते!"})
    return mock_call

@pytest.mark.asyncio
async def test_send_image_client_success():
    """
    1. send_image success → correct payload, outbound "image" logged.
    """
    mock_whatsapp_client.clear()
    real_client = WhatsAppClient()
    mock_res = {"messages": [{"id": "wamid.success_image_id"}]}
    with patch.object(real_client, "_post_request", AsyncMock(return_value=mock_res)):
        res = await real_client.send_image(
            to="919000000001",
            image_url="https://mock.supabase.co/storage/v1/object/public/product-images/corn.png",
            caption="Test Caption"
        )
        assert res == mock_res

@pytest.mark.asyncio
async def test_send_image_client_failure():
    """
    2. send_image failure (mock _post_request raising / returning error) → returns the failure signal, does NOT raise.
    """
    real_client = WhatsAppClient()
    with patch.object(real_client, "_post_request", AsyncMock(side_effect=MetaApiException("Rate limit exceeded"))):
        res = await real_client.send_image(
            to="919000000001",
            image_url="https://mock.supabase.co/storage/v1/object/public/product-images/corn.png",
            caption="Test Caption"
        )
        assert res == {"image_failed": True}

@pytest.mark.parametrize("crop_name,variety_name,image_url,key_traits,hindi_crop", [
    ("Maize", "VIGOUR 60A90", "https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-1.png", "Drought tolerant; shelling 84%", "मक्का"),
    ("Soybean", "VIGOUR KARISHMA", "https://mock.supabase.co/storage/v1/object/public/crop-photos/soy-1.png", "High oil; rust tolerant", "सोयाबीन")
])
@pytest.mark.asyncio
async def test_agent_recommendation_image_flow(crop_name, variety_name, image_url, key_traits, hindi_crop):
    """
    3. Agent recommends a product WITH image_url -> send_image called once.
    4. Parametrized across Maize and Soybean.
    """
    phone = f"919000005001_{crop_name}"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "crop": crop_name
        }
    })
    mock_whatsapp_client.clear()

    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].append({
        "product_id": f"PROD_{crop_name[:3].upper()}",
        "variety_name": variety_name,
        "crop": crop_name,
        "key_traits": key_traits,
        "approved_for_recommendation": "Y",
        "image_url": image_url
    })

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": crop_name},
        {"action": "reply", "message": f"किसान भाई, {hindi_crop} के लिए आप *{variety_name}* लगा सकते हैं।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid=f"w_img_{crop_name}",
            from_phone=phone,
            type="text",
            text=f"{crop_name} seed help",
            timestamp="1718563800"
        ))
        
        assert len(mock_whatsapp_client.sent_messages) == 2
        
        first = mock_whatsapp_client.sent_messages[0]
        assert first["type"] == "text"
        assert variety_name in first["body"]
        
        second = mock_whatsapp_client.sent_messages[1]
        assert second["type"] == "image"
        assert second["image_url"] == image_url
        assert variety_name in second["caption"]
        assert hindi_crop in second["caption"]
        assert "डीलर" in second["caption"]

@pytest.mark.parametrize("crop_name,variety_name,image_url,key_traits,hindi_crop", [
    ("Maize", "VIGOUR 60A90", "https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-1.png", "Drought tolerant; shelling 84%", "मक्का"),
    ("Soybean", "VIGOUR KARISHMA", "https://mock.supabase.co/storage/v1/object/public/crop-photos/soy-1.png", "High oil; rust tolerant", "सोयाबीन")
])
@pytest.mark.asyncio
async def test_agent_recommendation_image_failure_fallback(crop_name, variety_name, image_url, key_traits, hindi_crop):
    """
    3. Agent recommends a product WITH image_url but send_image fails/errors -> falls back to send_text.
    """
    phone = f"919000005002_{crop_name}"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "crop": crop_name
        }
    })
    mock_whatsapp_client.clear()

    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].append({
        "product_id": f"PROD_{crop_name[:3].upper()}",
        "variety_name": variety_name,
        "crop": crop_name,
        "key_traits": key_traits,
        "approved_for_recommendation": "Y",
        "image_url": image_url
    })

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": crop_name},
        {"action": "reply", "message": f"किसान भाई, {hindi_crop} के लिए आप *{variety_name}* लगा सकते हैं।"}
    ])

    async def mock_send_image_fail(*args, **kwargs):
        return {"image_failed": True}

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        with patch.object(mock_whatsapp_client, "send_image", AsyncMock(side_effect=mock_send_image_fail)):
            await conversation_router.route_message(ParsedMessage(
                wamid=f"w_img_fail_{crop_name}",
                from_phone=phone,
                type="text",
                text=f"{crop_name} seed help",
                timestamp="1718563800"
            ))
            
            assert len(mock_whatsapp_client.sent_messages) == 2
            assert mock_whatsapp_client.sent_messages[0]["type"] == "text"
            assert mock_whatsapp_client.sent_messages[1]["type"] == "text"
            
            fallback_body = mock_whatsapp_client.sent_messages[1]["body"]
            assert variety_name in fallback_body
            assert hindi_crop in fallback_body
            assert "डीलर" in fallback_body

@pytest.mark.parametrize("crop_name,variety_name,invalid_image_url,hindi_crop", [
    ("Maize", "VIGOUR 60A90", "", "मक्का"),                # empty
    ("Maize", "VIGOUR 60A90", "not_a_url", "मक्का"),        # invalid format
    ("Maize", "VIGOUR 60A90", "https://unsupported.com/image.pdf", "मक्का") # wrong extension
])
@pytest.mark.asyncio
async def test_agent_recommendation_invalid_image_url_fallback(crop_name, variety_name, invalid_image_url, hindi_crop):
    """
    4. Agent recommends a product WITHOUT/with invalid image_url -> text fallback directly, no send_image attempt.
    """
    phone = f"919000005003_{crop_name}_{hash(invalid_image_url)}"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "crop": crop_name
        }
    })
    mock_whatsapp_client.clear()

    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].append({
        "product_id": f"PROD_{crop_name[:3].upper()}",
        "variety_name": variety_name,
        "crop": crop_name,
        "key_traits": "Drought tolerant",
        "approved_for_recommendation": "Y",
        "image_url": invalid_image_url
    })

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": crop_name},
        {"action": "reply", "message": f"किसान भाई, {hindi_crop} के लिए आप *{variety_name}* लगा सकते हैं।"}
    ])

    send_image_spy = AsyncMock()

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        with patch.object(mock_whatsapp_client, "send_image", send_image_spy):
            await conversation_router.route_message(ParsedMessage(
                wamid="w_invalid_img",
                from_phone=phone,
                type="text",
                text=f"{crop_name} seed help",
                timestamp="1718563800"
            ))
            
            send_image_spy.assert_not_called()
            
            assert len(mock_whatsapp_client.sent_messages) == 1
            assert mock_whatsapp_client.sent_messages[0]["type"] == "text"
            assert variety_name in mock_whatsapp_client.sent_messages[0]["body"]

@pytest.mark.asyncio
async def test_multiple_products_one_image_and_text_listing():
    """
    5. Multiple products -> at most ONE image; others in text.
    """
    phone = "919000005004"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "crop": "Maize"
        }
    })
    mock_whatsapp_client.clear()

    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].extend([
        {
            "product_id": "PROD_M1",
            "variety_name": "VIGOUR 60A90",
            "crop": "Maize",
            "key_traits": "Drought tolerant",
            "approved_for_recommendation": "Y",
            "image_url": "https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-1.png"
        },
        {
            "product_id": "PROD_M2",
            "variety_name": "VIGOUR 30A90",
            "crop": "Maize",
            "key_traits": "High yield",
            "approved_for_recommendation": "Y",
            "image_url": "https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-2.png"
        }
    ])

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Maize"},
        {"action": "reply", "message": "किसान भाई, हमारे पास *VIGOUR 60A90* और *VIGOUR 30A90* दोनों मक्के की किस्में हैं।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w_multi_prod",
            from_phone=phone,
            type="text",
            text="makka options",
            timestamp="1718563800"
        ))
        
        assert len(mock_whatsapp_client.sent_messages) == 2
        
        first = mock_whatsapp_client.sent_messages[0]
        assert first["type"] == "text"
        
        second = mock_whatsapp_client.sent_messages[1]
        assert second["type"] == "image"
        assert second["image_url"] == "https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-1.png"
        assert "*VIGOUR 60A90*" in second["caption"]
        assert "*VIGOUR 30A90*" in second["caption"]

def test_strip_image_urls_helper():
    from app.ai.agent import strip_image_urls
    text = "यहाँ आपका उत्पाद है: https://kaubgntvamwamgodotew.supabase.co/storage/v1/object/public/product-images/maize.png\n\nकृपया इसे देखें।"
    assert strip_image_urls(text) == "यहाँ आपका उत्पाद है:\n\nकृपया इसे देखें।"
    
    text2 = "https://supabase.co/test.png\n\n\n"
    assert strip_image_urls(text2) == ""

@pytest.mark.asyncio
async def test_agent_response_contains_no_raw_urls():
    phone = "919000005009"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "crop": "Maize"
        }
    })
    mock_whatsapp_client.clear()

    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].append({
        "product_id": "PROD_M100",
        "variety_name": "VIGOUR TEST 99",
        "crop": "Maize",
        "key_traits": "High yield",
        "approved_for_recommendation": "Y",
        "image_url": "https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-99.png"
    })

    # The mock complete sequence
    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Maize"},
        {"action": "reply", "message": "यहाँ देखें: https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-99.png और *VIGOUR TEST 99* का उपयोग करें।"}
    ])

    complete_spy = AsyncMock(side_effect=mock_responses)

    with patch.object(mock_ai_provider, "complete", complete_spy):
        await conversation_router.route_message(ParsedMessage(
            wamid="w_no_url_test",
            from_phone=phone,
            type="text",
            text="makka variety link",
            timestamp="1718563800"
        ))

        # 1. Assert that the sent text reply does NOT contain raw url
        assert len(mock_whatsapp_client.sent_messages) == 2
        text_message = mock_whatsapp_client.sent_messages[0]
        assert text_message["type"] == "text"
        assert "http" not in text_message["body"]
        assert "supabase.co" not in text_message["body"]
        assert "VIGOUR TEST 99" in text_message["body"]

        # 2. Assert that the image message is still sent with the correct image URL and caption
        image_message = mock_whatsapp_client.sent_messages[1]
        assert image_message["type"] == "image"
        assert image_message["image_url"] == "https://mock.supabase.co/storage/v1/object/public/crop-photos/corn-99.png"
        assert "VIGOUR TEST 99" in image_message["caption"]

        # 3. Assert that LLM-facing JSON contains NO image_url
        assert complete_spy.call_count > 0
        for call in complete_spy.call_args_list:
            args, kwargs = call
            system_prompt = kwargs.get("system") or ""
            user_prompt = kwargs.get("user") or ""
            full_prompt = system_prompt + "\n" + user_prompt
            if "Tool Result" in full_prompt:
                assert "image_url" not in full_prompt

