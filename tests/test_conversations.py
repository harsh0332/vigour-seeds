import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from conftest import in_memory_db, mock_whatsapp_client, mock_ai_provider
from app.whatsapp.models import ParsedMessage
from app.flows.router import conversation_router
from app.db.repositories.sessions import sessions_repo

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
async def test_obviously_off_topic_no_llm():
    """
    Asserts: Obvious off-topic queries return the fixed refusal message directly
    and DO NOT call the LLM provider (complete).
    """
    phone = "919000001099"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_complete = AsyncMock()
    with patch.object(mock_ai_provider, "complete", mock_complete):
        msg = ParsedMessage(
            wamid="wamid.off_topic_test",
            from_phone=phone,
            type="text",
            text="write a python function to check if a number is prime",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]

        assert "माफ़ कीजिए किसान भाई" in last_msg
        mock_complete.assert_not_called()

@pytest.mark.asyncio
async def test_obviously_off_topic_joke_no_llm():
    """
    Asserts: Asking for a joke returns the fixed refusal message directly
    and DO NOT call the LLM provider.
    """
    phone = "919000001098"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_complete = AsyncMock()
    with patch.object(mock_ai_provider, "complete", mock_complete):
        msg = ParsedMessage(
            wamid="wamid.joke_test",
            from_phone=phone,
            type="text",
            text="ek mast chutkula sunao na",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]

        assert "माफ़ कीजिए किसान भाई" in last_msg
        mock_complete.assert_not_called()

@pytest.mark.asyncio
async def test_makka_beej_direct_products():
    """
    Asserts: "mujhe makka ka beej chahiye" directly runs find_products and returns maize seeds
    without looping on Kya Samasya hai or photo bhejo.
    """
    phone = "919000001097"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()
    
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].append({
        "product_id": "PROD_M1",
        "variety_name": "Vigour Maize 99",
        "crop": "Maize",
        "duration_days": "110",
        "mrp_inr": 350.0,
        "key_traits": "उच्च पैदावार, सूखा सहनशील",
        "pest_disease_tolerance": "tolerant",
        "pack_size": "5 kg",
        "approved_for_recommendation": "Y",
        "target_region": "MP"
    })

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Maize", "problem": "-"},
        {"action": "reply", "message": "नमस्ते! मक्का के लिए हमारे पास Vigour Maize 99 बीज उपलब्ध है।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.makka_test",
            from_phone=phone,
            type="text",
            text="mujhe makka ka beej chahiye",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour Maize 99" in last_msg
        assert "क्या समस्या है" not in last_msg
        assert "फोटो" not in last_msg

@pytest.mark.asyncio
async def test_pest_problem_react():
    """
    Asserts: Pest problem text triggers correct advice and product recommendations.
    """
    phone = "919000001096"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Soybean", "problem": "pests"},
        {"action": "reply", "message": "सोयाबीन में कीड़े लगने पर आप Vigour Protect का छिड़काव कर सकते हैं।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.pest_test",
            from_phone=phone,
            type="text",
            text="soybean me keede lag gaye hain",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour Protect" in last_msg
        assert "छिड़काव" in last_msg

@pytest.mark.asyncio
async def test_dealer_lookup_react():
    """
    Asserts: "dealer kaha milega" calls find_dealer action.
    """
    phone = "919000001095"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "state": "Madhya Pradesh",
            "district": "Dhar"
        }
    })
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "find_dealer"},
        {"action": "reply", "message": "धार जिले में हमारे मुख्य डीलर: न्यू किसान ट्रेडर्स हैं।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.dealer_test",
            from_phone=phone,
            type="text",
            text="dealer kaha milega btao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "न्यू किसान ट्रेडर्स" in last_msg

@pytest.mark.asyncio
async def test_greeting_and_onboarding_welcome():
    """
    Asserts: /reset then "Hye" -> welcome + Vigour intro + name request (no Refusal).
    """
    phone = "919000001001"
    await sessions_repo.delete(phone)
    
    # We send "/reset" first
    msg_reset = ParsedMessage(
        wamid="wamid.reset",
        from_phone=phone,
        type="text",
        text="/reset",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg_reset)
    mock_whatsapp_client.clear()
    
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "Vigour Seeds में आपका स्वागत है! मैं आपका कृषि सहायक हूँ। आपका नाम क्या है?"}
    ])
        
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg_hye = ParsedMessage(
            wamid="wamid.hye",
            from_phone=phone,
            type="text",
            text="Hye",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg_hye)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour" in last_msg
        assert "नाम" in last_msg
        assert "समझ" not in last_msg

@pytest.mark.asyncio
async def test_full_onboarding_flow():
    """
    Asserts: Full onboarding order works: name -> village+state -> land -> water -> crop -> problem.
    """
    phone = "919000001002"
    await sessions_repo.delete(phone)
    
    turns = [
        ("Hye", [{"action": "reply", "message": "नमस्ते! आपका नाम क्या है?"}], "नमस्ते! आपका नाम क्या है?"),
        ("महिपाल", [{"action": "save_profile", "fields": {"name": "महिपाल"}}, {"action": "reply", "message": "महिपाल जी, आप किस राज्य और जिला से हैं?"}], "महिपाल जी, आप किस राज्य और जिला से हैं?"),
        ("MP Dhar", [{"action": "save_profile", "fields": {"state": "Madhya Pradesh", "district": "Dhar"}}, {"action": "reply", "message": "धन्यवाद। आपकी कुल जमीन (एकड़ में) कितनी है?"}], "धन्यवाद। आपकी कुल जमीन (एकड़ में) कितनी है?"),
        ("10", [{"action": "save_profile", "fields": {"total_land": "10"}}, {"action": "reply", "message": "सिंचाई का साधन क्या है (जैसे ट्यूबवेल, कुआँ, नहर)?"}], "सिंचाई का साधन क्या है (जैसे ट्यूबवेल, कुआँ, नहर)?"),
        ("ट्यूबवेल", [{"action": "save_profile", "fields": {"water_source": "ट्यूबवेल"}}, {"action": "reply", "message": "आप अभी अपने खेत में कौन सी फसल उगा रहे हैं?"}], "आप अभी अपने खेत में कौन सी फसल उगा रहे हैं?"),
        ("Soybean", [{"action": "save_profile", "fields": {"crop": "Soybean"}}, {"action": "reply", "message": "आपकी Soybean फसल में अभी क्या दिक्कत आ रही है?"}], "आपकी Soybean फसल में अभी क्या दिक्कत आ रही है?")
    ]
    
    for user_input, mock_sequence, expected_reply in turns:
        mock_whatsapp_client.clear()
        mock_responses = make_mock_complete_sequence(mock_sequence)
        with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
            msg = ParsedMessage(
                wamid=f"wamid.onb.{user_input}",
                from_phone=phone,
                type="text",
                text=user_input,
                timestamp="1718563800"
            )
            await conversation_router.route_message(msg)
            
            reply = mock_whatsapp_client.sent_messages[-1]["body"]
            assert expected_reply in reply

@pytest.mark.asyncio
async def test_short_valid_answer_crop_stage():
    """
    Asserts: A short valid answer ("40" to "kitne din ki fasal") is accepted, NOT marked unclear.
    """
    phone = "919000001003"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean",
            "last_bot_question": "आपकी सोयाबीन फसल अभी कितने दिन की है?"
        }
    })
    
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "सोयाबीन में आप यूरिया डाल सकते हैं।"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_40",
            from_phone=phone,
            type="text",
            text="40",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "मुझे समझ नहीं आया" not in last_msg
        assert "सोयाबीन" in last_msg

@pytest.mark.asyncio
async def test_classifier_fertilizer_guidance():
    """
    Asserts: "khad kon se dale" -> answered (fertilizer guidance), not "samajh nahi aaya", not scheme/mandi.
    """
    phone = "919000001004"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean",
            "problem_summary": "खाद प्रबंधन"
        }
    })
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "सोयाबीन में आप बुवाई के समय DAP और यूरिया का उपयोग कर सकते हैं।"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_khad",
            from_phone=phone,
            type="text",
            text="khad kon se dale",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "DAP" in last_msg or "यूरिया" in last_msg
        assert "मुझे समझ नहीं आया" not in last_msg

@pytest.mark.asyncio
async def test_classifier_medicine_guidance():
    """
    Asserts: "dawai kon se dale" -> general medicine guidance, not scheme/mandi.
    """
    phone = "919000001005"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean",
            "problem_summary": "रोग नियंत्रण"
        }
    })
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "सोयाबीन में पीला मोज़ेक वायरस के लिए सही दवा और मात्रा के लिए नज़दीकी डीलर/कृषि अधिकारी से पुष्टि करें।"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_dawai",
            from_phone=phone,
            type="text",
            text="dawai kon se dale",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "सही दवा और मात्रा के लिए" in last_msg
        assert "डीलर" in last_msg

@pytest.mark.asyncio
async def test_classifier_soybean_seeds():
    """
    Asserts: "soybean ke acchi kism batao" -> proceeds to seed recommendation, not loan/insurance.
    """
    phone = "919000001006"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean"
        }
    })
    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Soybean", "problem": "-"},
        {"action": "reply", "message": "नमस्ते! हमारी सोयाबीन की प्रमुख किस्में: Vigour 335 और Vigour 9560 हैं।"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_soybean_kism",
            from_phone=phone,
            type="text",
            text="soybean ke acchi kism batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour 335" in last_msg or "Vigour 9560" in last_msg

@pytest.mark.asyncio
async def test_classifier_help_jankari():
    """
    Asserts: "tum aur kya jankari de sakte ho" -> help-style answer, not "samajh nahi aaya".
    """
    phone = "919000001007"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean"
        }
    })
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "मैं आपकी फसल प्रबंधन में मदद कर सकता हूँ।"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_help",
            from_phone=phone,
            type="text",
            text="tum aur kya jankari de sakte ho",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "मदद" in last_msg or "जानकारी" in last_msg or "सहायता" in last_msg

@pytest.mark.asyncio
async def test_classifier_pm_kisan_out_of_scope():
    """
    Asserts: "PM Kisan ka paisa kab aayega" -> honest out-of-scope reply (deferred).
    """
    phone = "919000001008"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean"
        }
    })
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "माफ़ कीजिएगा, मैं सरकारी योजनाओं की जानकारी नहीं दे सकता।"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_pm_kisan",
            from_phone=phone,
            type="text",
            text="PM Kisan ka paisa kab aayega",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "माफ़" in last_msg or "योजना" in last_msg or "लोन" in last_msg or "सरकारी" in last_msg

@pytest.mark.asyncio
async def test_product_soybean_only():
    """
    Asserts: Soybean products list returns ONLY soybean varieties, never Paddy.
    """
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].append({
        "product_id": "PROD_P1",
        "variety_name": "Vigour 087",
        "crop": "Paddy",
        "duration_days": "120",
        "mrp_inr": 200.0,
        "key_traits": "उच्च पैदावार",
        "pest_disease_tolerance": "tolerant",
        "pack_size": "10 kg",
        "approved_for_recommendation": "Y",
        "target_region": "MP"
    })
    
    phone = "919000001009"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean"
        }
    })
    
    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Soybean", "problem": "-"},
        {"action": "reply", "message": "यहाँ सोयाबीन किस्में हैं: Vigour 335 और Vigour 9560।"}
    ])
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_soybean_products",
            from_phone=phone,
            type="text",
            text="saare product batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        
        assert "Vigour 335" in last_msg or "Vigour 9560" in last_msg
        assert "Vigour 087" not in last_msg

@pytest.mark.asyncio
async def test_product_crop_switch():
    """
    Asserts: Crop switch Paddy -> Soybean returns soybean-only products.
    """
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    in_memory_db.tables["products"].append({
        "product_id": "PROD_P1",
        "variety_name": "Vigour 087",
        "crop": "Paddy",
        "duration_days": "120",
        "mrp_inr": 200.0,
        "key_traits": "उच्च पैदावार",
        "pest_disease_tolerance": "tolerant",
        "pack_size": "10 kg",
        "approved_for_recommendation": "Y",
        "target_region": "MP"
    })
    
    phone = "919000001010"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Paddy",
            "recommended": True,
            "all_recommended_ids": ["Vigour 087"]
        }
    })
    
    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Soybean", "problem": "-"},
        {"action": "reply", "message": "यहाँ सोयाबीन किस्में हैं: Vigour 335 और Vigour 9560।"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_crop_switch",
            from_phone=phone,
            type="text",
            text="Mujhe soybean ke kism batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        
        assert "Vigour 335" in last_msg or "Vigour 9560" in last_msg
        assert "Vigour 087" not in last_msg

@pytest.mark.asyncio
async def test_product_zero_approved():
    """
    Asserts: Crop with zero approved products -> honest "no product" + dealer/rep.
    """
    phone = "919000001011"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Dhaniya"
        }
    })
    
    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Dhaniya", "problem": "-"},
        {"action": "reply", "message": "कोई अनुमोदित Vigour उत्पाद उपलब्ध नहीं है। संपर्क: 9999999999"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_zero_approved",
            from_phone=phone,
            type="text",
            text="saare product बताओ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "कोई अनुमोदित Vigour" in last_msg
        assert "संपर्क" in last_msg

@pytest.mark.asyncio
async def test_no_repeated_replies():
    """
    Asserts: Three consecutive short messages never produce identical replies in a row.
    """
    phone = "919000001012"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean",
            "recommended": True,
            "sent_messages_history": []
        }
    })
    
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "बहुत बढ़िया भाई!"},
        {"action": "reply", "message": "जी बिल्कुल!"},
        {"action": "reply", "message": "ठीक है महिपाल जी!"}
    ])
        
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        replies = []
        for user_text in ["ok", "thanks", "aur kya help"]:
            msg = ParsedMessage(
                wamid=f"wamid.repeat.{user_text}",
                from_phone=phone,
                type="text",
                text=user_text,
                timestamp="1718563800"
            )
            await conversation_router.route_message(msg)
            reply = mock_whatsapp_client.sent_messages[-1]["body"]
            replies.append(reply)
            
        assert replies[0] != replies[1]
        assert replies[1] != replies[2]

@pytest.mark.asyncio
async def test_no_broken_placeholder_text():
    """
    Asserts: No reply contains placeholder text like "स्पष्ट लक्षण नहीं हैं".
    """
    phone = "919000001013"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Soybean",
            "problem_summary": "स्पष्ट लक्षण नहीं हैं",
            "problem_clarified": True
        }
    })
    
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "हम आपको सोयाबीन के लिए सही सलाह देंगे।"}
    ])
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.placeholder_check",
            from_phone=phone,
            type="text",
            text="Mujhe soybean ke kism batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "स्पष्ट लक्षण नहीं हैं" not in last_msg
