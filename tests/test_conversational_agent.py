import pytest
import json
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from conftest import in_memory_db, mock_whatsapp_client, mock_ai_provider
from app.whatsapp.models import ParsedMessage
from app.flows.router import conversation_router
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo

def make_mock_complete(extraction_dict, phrasing_response):
    async def mock_call(system, user, json_mode=False):
        if "extraction" in system or json_mode:
            return json.dumps(extraction_dict)
        return phrasing_response
    return mock_call

@pytest.mark.asyncio
async def test_conversational_greeting():
    """
    Test Scenario 1: Warm greeting when farmer types a greeting.
    """
    phone = "919000000010"
    await sessions_repo.delete(phone)
    
    mock_responses = make_mock_complete(
        {},
        "नमस्ते 🙏 Vigour Seeds में आपका स्वागत है। मैं आपका कृषि विशेषज्ञ Vigour मित्र हूँ। मैं आपकी क्या मदद कर सकता हूँ?"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_greet",
            from_phone=phone,
            type="text",
            text="नमस्ते",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour मित्र" in last_msg
        assert "नमस्ते" in last_msg

@pytest.mark.asyncio
async def test_conversational_location_normalization():
    """
    Test Scenario 2: Location normalization (Devanagari to English).
    """
    phone = "919000000011"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी"
        }
    })
    
    mock_responses = make_mock_complete(
        {"village_city": "उज्जैन", "state": "मध्य प्रदेश"},
        "धन्यवाद! मैंने आपका जिला उज्जैन और राज्य मध्य प्रदेश दर्ज कर लिया है।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_loc",
            from_phone=phone,
            type="text",
            text="मेरा जिला उज्जैन मध्य प्रदेश है",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        # Verify WhatsApp response
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "उज्जैन" in last_msg or "मध्य प्रदेश" in last_msg
        
        # Verify Session State is saved
        session = await sessions_repo.get(phone)
        assert session is not None
        assert session.collected_json.get("district") == "Ujjain"
        assert session.collected_json.get("state") == "Madhya Pradesh"

@pytest.mark.asyncio
async def test_conversational_product_recommendation():
    """
    Test Scenario 3: Product recommendations using approved products, max 3, with null price fallback.
    """
    phone = "919000000012"
    
    in_memory_db.tables["products"].append({
        "product_id": "PROD_UNAPPROVED",
        "variety_name": "Vigour Bad",
        "crop": "Soybean",
        "approved_for_recommendation": "N",
        "mrp_inr": 200.0,
        "pack_size": "20 kg"
    })
    in_memory_db.tables["products"].append({
        "product_id": "PROD_S3_NULL_PRICE",
        "variety_name": "Vigour Premium",
        "crop": "Soybean",
        "approved_for_recommendation": "Y",
        "mrp_inr": None,
        "pack_size": "20 kg"
    })
    
    for r in in_memory_db.tables["recommendation_rules"]:
        if r["rule_id"] == "R002":
            r["recommended_product_ids"] = "PROD_S1, PROD_S2, PROD_S3_NULL_PRICE"
            
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "हरीश",
            "district": "Ujjain",
            "state": "Madhya Pradesh"
        }
    })
    
    mock_responses = make_mock_complete(
        {"crop": "Soybean", "problem": "sowing"},
        "सोयाबीन बुवाई के लिए ये उत्पाद हैं:\n- Vigour 335 (उच्च उपज, कीमत: 150 रुपये)\n- Vigour Premium (रोग प्रतिरोधी, रेट की जानकारी के लिए अपने नज़दीकी डीलर से संपर्क करें)"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_reco",
            from_phone=phone,
            type="text",
            text="सोयाबीन बोने के लिए बढ़िया बीज बताओ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour 335" in last_msg
        assert "Vigour Premium" in last_msg
        assert "नज़दीकी डीलर से संपर्क करें" in last_msg or "डीलर से पूछें" in last_msg or "रेट की जानकारी" in last_msg
        
        from app.ai.agent import tool_find_products
        tool_results = await tool_find_products("Soybean", "sowing", phone)
        var_names = [p["variety_name"] for p in tool_results]
        assert "Vigour Bad" not in var_names
        assert "Vigour 335" in var_names
        assert "Vigour Premium" in var_names

@pytest.mark.asyncio
async def test_conversational_context_memory():
    """
    Test Scenario 4: Context memory (remembers crop and details across turns).
    """
    phone = "919000000013"
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "दीपक",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "crop": "Soybean"
        }
    })
    
    mock_responses = make_mock_complete(
        {"problem": "pest_attack"},
        "कीटों के लिए आप Vigour 335 का उपयोग कर सकते हैं।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)) as mock_complete:
        msg = ParsedMessage(
            wamid="wamid.test_mem",
            from_phone=phone,
            type="text",
            text="पत्तियों में कीड़े लग गए हैं",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        # Verify call contained Soybean in extraction context
        system_arg = mock_complete.call_args[1]["system"]
        assert "Soybean" in system_arg
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        assert "Vigour 335" in mock_whatsapp_client.sent_messages[-1]["body"]

@pytest.mark.asyncio
async def test_conversational_dealer_sharing():
    """
    Test Scenario 5: Dealer contact sharing based on location.
    """
    phone = "919000000014"
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "राजेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "recommended": True
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "उज्जैन में हमारे डीलर शर्मा सीड्स हैं (फ़ोन: 918888888888)।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_dealer",
            from_phone=phone,
            type="text",
            text="डीलर का नंबर बताओ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "918888888888" in last_msg
        assert "शर्मा सीड्स" in last_msg

@pytest.mark.asyncio
@patch("app.ai.agent.whatsapp_client")
async def test_conversational_vision_escalation(mock_download):
    """
    Test Scenario 6: Low-confidence image diagnosis triggers human agronomist escalation.
    """
    phone = "919000000015"
    
    mock_download.download_media = AsyncMock(return_value=(b"mock_bytes", "image/jpeg"))
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "सुरेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "crop": "Soybean"
        }
    })
    
    with patch("app.ai.vision.vision_service.diagnose", AsyncMock(return_value={
        "problem_category": "fungal_disease",
        "severity": "medium",
        "confidence": 0.4,
        "visible_symptoms_hindi": "पत्ते पीले होना",
        "needs_human": True
    })):
        mock_responses = make_mock_complete(
            {},
            "हमारे एग्रोनॉमिस्ट जल्द आपसे संपर्क करेंगे, और तब तक आप लिखकर मदद ले सकते हैं।"
        )
        
        with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
            msg = ParsedMessage(
                wamid="wamid.test_vision_low",
                from_phone=phone,
                type="image",
                media_id="media_test_vision_0.4",
                timestamp="1718563800"
            )
            await conversation_router.route_message(msg)
            
            lead = await leads_repo.get_farmer(phone)
            assert lead is not None
            assert lead.escalated_to_human is True
            assert lead.lead_status == "escalated"

@pytest.mark.asyncio
async def test_conversational_json_parsing_and_reprompt():
    """
    Test Scenario 7: Malformed JSON output is handled gracefully.
    """
    phone = "919000000016"
    
    # First extraction response is malformed, phrasing is fine
    mock_responses = [
        "This is not JSON: {extracted fields}",
        "नमस्ते! मैं आपकी किस प्रकार मदद कर सकता हूँ?"
    ]
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)) as mock_complete:
        msg = ParsedMessage(
            wamid="wamid.test_malformed_reprompt",
            from_phone=phone,
            type="text",
            text="नमस्ते",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        assert "नमस्ते!" in mock_whatsapp_client.sent_messages[-1]["body"]

@pytest.mark.asyncio
async def test_conversational_maize_recommendation_and_translation():
    """
    Test Scenario 8: Verify crop synonym resolution and VIGOUR 60A90 recommendation.
    """
    phone = "919000000017"
    
    in_memory_db.tables["crops"].append({
        "crop_id": "CR02",
        "crop_name_hi": "मक्का",
        "crop_name_en": "Maize / Corn",
        "in_catalog": "Y"
    })
    
    maize_products = [
        {
            "product_id": "MZE001",
            "variety_name": "VIGOUR 60A90",
            "crop": "Maize",
            "approved_for_recommendation": "Y",
            "mrp_inr": None,
            "pest_disease_tolerance": "Highly tolerant to TLB & stem borer",
            "target_problem_fit": "stem borer prone areas",
            "pack_size": "4 kg",
            "duration_days": "120-125",
            "key_traits": "Shelling 84-85%; stay green"
        }
    ]
    for p in maize_products:
        in_memory_db.tables["products"].append(p)

    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "रामसिंह",
            "district": "Ujjain",
            "state": "Madhya Pradesh"
        }
    })
    
    mock_responses = make_mock_complete(
        {"crop": "Makka", "problem": "stem_borer"},
        "मक्का (Maize) के लिए सबसे बढ़िया बीज VIGOUR 60A90 है। दाम के लिए नज़दीकी डीलर से पूछें।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_maize",
            from_phone=phone,
            type="text",
            text="मक्का / Makka बोना है, कीड़े की समस्या है",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "VIGOUR 60A90" in last_msg
        assert "डीलर" in last_msg

@pytest.mark.asyncio
async def test_conversational_bare_city_normalization():
    """
    Verify that bare city 'Bhopal' alone resolves to state 'Madhya Pradesh' and district 'Bhopal'
    confidently without prompting for state.
    """
    from app.flows.farmer import parse_location
    active_states = [{"state": "Madhya Pradesh", "state_code": "MP"}]
    res = await parse_location("Bhopal", active_states)
    assert res is not None
    state, dist_norm, dist_raw = res
    assert state == "Madhya Pradesh"
    assert dist_norm == "Bhopal"
    assert dist_raw == "bhopal"

    res_hi = await parse_location("इंदौर", active_states)
    assert res_hi is not None
    state_hi, dist_norm_hi, dist_raw_hi = res_hi
    assert state_hi == "Madhya Pradesh"
    assert dist_norm_hi == "Indore"
    assert dist_raw_hi == "इंदौर"

@pytest.mark.asyncio
async def test_conversational_reset_prevention_on_short_reply():
    """
    Verify that when conversation history is present, short replies like 'batao'
    do not trigger a welcome re-greeting/reset.
    """
    phone = "919000000018"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "crop": "Maize"
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "हाँ रामजी भाई, मक्का की फसल में क्या समस्या आ रही है?"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)) as mock_complete:
        msg = ParsedMessage(
            wamid="wamid.test_short_reply",
            from_phone=phone,
            type="text",
            text="batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour मित्र" not in last_msg
        assert "स्वागत" not in last_msg

# New State Machine Scenario Tests

@pytest.mark.asyncio
async def test_sc1_first_message_asks_name():
    phone = "919000000021"
    await sessions_repo.delete(phone)
    
    mock_responses = make_mock_complete(
        {},
        "नमस्ते! Vigour Seeds एक विश्वसनीय बीज कंपनी है। आपका नाम क्या है?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.sc1",
            from_phone=phone,
            type="text",
            text="hello",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour Seeds" in last_msg
        assert "नाम" in last_msg
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("greeted") is True

@pytest.mark.asyncio
async def test_sc2_after_name_asks_location():
    phone = "919000000022"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी"
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "रामजी भाई, आप किस गाँव/शहर से हैं, और कौन से राज्य से?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.sc2",
            from_phone=phone,
            type="text",
            text="रामजी",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "राज्य" in last_msg

@pytest.mark.asyncio
async def test_sc3_after_location_asks_land():
    phone = "919000000023"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी",
            "district": "Ujjain",
            "state": "Madhya Pradesh"
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "आपके पास कितनी कृषि भूमि (एकड़/बीघा) है?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.sc3",
            from_phone=phone,
            type="text",
            text="उज्जैन, मध्य प्रदेश",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "एकड़" in last_msg or "भूमि" in last_msg or "ज़मीन" in last_msg

@pytest.mark.asyncio
async def test_sc4_after_land_asks_water():
    phone = "919000000024"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "खेत में पानी कहाँ से आता है? ट्यूबवेल, कुआँ, तालाब, नहर, नदी, या बारिश का पानी?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.sc4",
            from_phone=phone,
            type="text",
            text="5 एकड़",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "ट्यूबवेल" in last_msg or "कुआँ" in last_msg or "तालाब" in last_msg

@pytest.mark.asyncio
async def test_sc5_after_water_asks_crop():
    phone = "919000000025"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "ट्यूबवेल"
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "अभी खेत में कौन सी फसल लगाई है?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.sc5",
            from_phone=phone,
            type="text",
            text="ट्यूबवेल",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "फसल" in last_msg

@pytest.mark.asyncio
async def test_sc6_after_crop_asks_problem():
    phone = "919000000026"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "ट्यूबवेल",
            "crop": "Maize"
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "आपकी मक्का की फसल में क्या समस्या आ रही है?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.sc6",
            from_phone=phone,
            type="text",
            text="मक्का",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "समस्या" in last_msg

@pytest.mark.asyncio
async def test_sc8_no_repeat_guard():
    phone = "919000000028"
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "रामजी",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "ट्यूबवेल",
            "crop": "Maize",
            "last_bot_question": "आपकी मक्का की फसल में क्या समस्या आ रही है?",
            "sent_messages_history": ["आपकी मक्का की फसल में क्या समस्या आ रही है?"]
        }
    })
    
    async def mock_call(system, user, json_mode=False):
        if "extraction" in system or json_mode:
            return json.dumps({"problem": None})
        if "Rephrase" in system:
            return "किसान भाई, मक्का में क्या बीमारी या दिक्कत दिख रही है?"
        return "आपकी मक्का की फसल में क्या समस्या आ रही है?"
        
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_call)):
        msg = ParsedMessage(
            wamid="wamid.sc8",
            from_phone=phone,
            type="text",
            text="ji",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert last_msg == "किसान भाई, मक्का में क्या बीमारी या दिक्कत दिख रही है?"

@pytest.mark.asyncio
async def test_sc9_multi_field_extraction():
    phone = "919000000029"
    await sessions_repo.delete(phone)
    
    mock_responses = make_mock_complete(
        {"name": "Ramesh", "village_city": "Narsinghpur", "state": "MP"},
        "रमेश भाई, आपके पास कितनी कृषि भूमि (एकड़/बीघा) है?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.sc9",
            from_phone=phone,
            type="text",
            text="Ramesh, Narsinghpur MP",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("name") == "Ramesh"
        assert session.collected_json.get("state") == "Madhya Pradesh"
        assert session.collected_json.get("district") == "Narsinghpur"
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "भूमि" in last_msg or "ज़मीन" in last_msg

@pytest.mark.asyncio
async def test_conversational_testing_reset():
    phone = "919000000030"
    
    # Setup session
    await sessions_repo.upsert(phone, {
        "current_step": "STEP_5",
        "collected_json": {
            "greeted": True,
            "name": "रामजी"
        }
    })
    
    # Log a message in conversations repository
    from app.db.repositories.conversations import conversations_repo
    await conversations_repo.log({
        "whatsapp_phone": phone,
        "direction": "inbound",
        "message_text": "hello",
        "message_id": "wamid.dummy1",
        "lead_id": "L123",
        "message_type": "text",
        "handled_by": "bot"
    })
    
    session_before = await sessions_repo.get(phone)
    assert session_before is not None
    
    # Send /reset command
    msg = ParsedMessage(
        wamid="wamid.reset",
        from_phone=phone,
        type="text",
        text="/reset",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg)
    
    # Verify response message
    last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
    assert last_msg == "बातचीत रीसेट हो गई। नमस्ते!"
    
    # Verify DB rows cleared
    session_after = await sessions_repo.get(phone)
    assert session_after is None
    
    from app.db.client import supabase_client
    res = supabase_client.table("conversations").select("*").eq("whatsapp_phone", phone).execute()
    assert len(res.data) == 0

@pytest.mark.asyncio
async def test_conversational_post_recommendation_new_crop():
    phone = "919000000031"
    
    # 1. Setup a session that is already post-recommendation (greeted, name, loc, land, water, crop=Maize, recommended=True)
    await sessions_repo.upsert(phone, {
        "current_step": "STEP_8",
        "collected_json": {
            "greeted": True,
            "name": "Harsh",
            "district": "Narsinghpur",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "ट्यूबवेल",
            "crop": "Maize",
            "problem_summary": "केड़े",
            "recommended": True,
            "last_recommended_ids": ["VIGOUR 60A90"]
        }
    })
    
    # 2. Farmer asks about tomato (new crop) "टमाटर की फसल में भी समस्या आती है"
    mock_responses = make_mock_complete(
        {"crop": "tamatar"},
        "हर्ष भाई, आपकी टमाटर की फसल में क्या समस्या आ रही है?"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.new_crop",
            from_phone=phone,
            type="text",
            text="टमाटर की फसल में भी समस्या आती है",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("crop") == "Tomato"
        assert session.collected_json.get("recommended") is False
        assert session.collected_json.get("problem_summary") is None
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "टमाटर" in last_msg

@pytest.mark.asyncio
async def test_conversational_post_recommendation_new_problem():
    phone = "919000000032"
    
    # 1. Setup a session that is already post-recommendation
    await sessions_repo.upsert(phone, {
        "current_step": "STEP_8",
        "collected_json": {
            "greeted": True,
            "name": "Harsh",
            "district": "Narsinghpur",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "ट्यूबवेल",
            "crop": "Maize",
            "problem_summary": "केड़े",
            "recommended": True,
            "last_recommended_ids": ["VIGOUR 60A90"]
        }
    })
    
    # 2. Farmer asks about a new problem: "अब मक्का की फसल में पत्ते पीले पड़ रहे हैं"
    calls = []
    async def mock_call(system, user, json_mode=False):
        calls.append((system, user, json_mode))
        if json_mode or "extraction" in system:
            if len(calls) == 1:
                return json.dumps({"problem": "पत्ते पीले"})
            return json.dumps({})
        if len(calls) <= 2:
            return "हर्ष भाई, क्या पत्तियों पर कोई धब्बे हैं या पूरी पत्ती पीली है?"
        else:
            return "हर्ष भाई, मक्के की फसल के लिए आप Vigour 60A90 किस्म बो सकते हैं।"
            
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_call)):
        msg = ParsedMessage(
            wamid="wamid.new_problem",
            from_phone=phone,
            type="text",
            text="अब मक्का की फसल में पत्ते पीले पड़ रहे हैं",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("crop") == "Maize"
        # Since it's a new problem, it resets recommended/clarified and does the clarification turn first
        assert session.collected_json.get("recommended") is False
        assert session.collected_json.get("problem_clarified") is True
        assert session.collected_json.get("problem_summary") == "पत्ते पीले"
        
        # Turn 2: Farmer responds to the clarification
        msg2 = ParsedMessage(
            wamid="wamid.new_problem_reply",
            from_phone=phone,
            type="text",
            text="हाँ, पूरी पत्ती पीली है",
            timestamp="1718563860"
        )
        await conversation_router.route_message(msg2)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("recommended") is True
        assert session.collected_json.get("problem_summary") == "पत्ते पीले"

@pytest.mark.asyncio
async def test_crop_synonym_resolution_dhaniya():
    """
    Test धनिया resolution and ensure no collision with Paddy.
    """
    from app.data.crop_synonyms import resolve_crop
    
    # Check Hindi धनिया maps to Coriander / Spinach / Methi
    assert resolve_crop("धनिया") == "Coriander / Spinach / Methi"
    
    # Check Hinglish variations map to Coriander / Spinach / Methi
    assert resolve_crop("dhaniya") == "Coriander / Spinach / Methi"
    assert resolve_crop("dhanya") == "Coriander / Spinach / Methi"
    assert resolve_crop("dhaniyan") == "Coriander / Spinach / Methi"
    assert resolve_crop("dhaniye") == "Coriander / Spinach / Methi"
    assert resolve_crop("dhania") == "Coriander / Spinach / Methi"
    
    # Check Paddy / धान maps to Paddy
    assert resolve_crop("dhan") == "Paddy"
    assert resolve_crop("धान") == "Paddy"
    assert resolve_crop("dhaan") == "Paddy"
    assert resolve_crop("dhania") != "Paddy"
    assert resolve_crop("dhanya") != "Paddy"

@pytest.mark.asyncio
async def test_conversational_dhaniya_no_products():
    """
    Test धनिया maps to 0 approved products and outputs an honest message (no invented products).
    """
    phone = "919000000033"
    
    # Register coriander in catalog
    in_memory_db.tables["crops"].append({
        "crop_id": "CR90",
        "crop_name_hi": "धनिया",
        "crop_name_en": "Coriander / Spinach / Methi",
        "in_catalog": "Y"
    })
    
    # Register an unapproved coriander product
    in_memory_db.tables["products"].append({
        "product_id": "HRB001",
        "crop": "Coriander / Spinach / Methi",
        "variety_name": "Vigour Coriander-1",
        "approved_for_recommendation": "N",
        "mrp_inr": None,
        "pack_size": "500 g"
    })
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "हरिश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "ट्यूबवेल",
            "crop": "Coriander / Spinach / Methi",
            "problem_summary": "पत्ते खराब",
            "problem_clarified": True
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "हरिश भाई, हमारे पास वर्तमान में धनिया के लिए कोई स्वीकृत Vigour बीज उपलब्ध नहीं है। मैं आपको विशेषज्ञ से जोड़ सकता हूँ।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.dhaniya_test",
            from_phone=phone,
            type="text",
            text="बीज बताओ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("recommended") is True
        assert session.collected_json.get("last_recommended_ids") == []
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour Coriander-1" not in last_msg
        assert "उपलब्ध नहीं" in last_msg or "क्षमा करें" in last_msg or "नहीं है" in last_msg

@pytest.mark.asyncio
async def test_conversational_soybean_pest_reco():
    """
    Test Soybean + pests maps to real approved products and gives soybean-specific recommendation.
    """
    phone = "919000000034"
    
    # Ensure Soybean crop and approved products are in db (already seeded in conftest, but double check / register)
    # in_memory_db has PROD_S1 (Vigour 335) and PROD_S2 (Vigour 9560) approved for Soybean.
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "दिनेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "नहर",
            "crop": "Soybean",
            "problem_summary": "कीट का हमला",
            "problem_clarified": True
        }
    })
    
    # Mock LLM response recommending Vigour 335
    mock_responses = make_mock_complete(
        {},
        "दिनेश भाई, सोयाबीन में कीट की समस्या के लिए हम आपको Vigour 335 बीज की सलाह देते हैं जो कीट सहनशील है।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.soybean_pest_test",
            from_phone=phone,
            type="text",
            text="सलाह दो",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("recommended") is True
        assert "Vigour 335" in session.collected_json.get("last_recommended_ids")
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour 335" in last_msg
        assert "सोयाबीन" in last_msg


@pytest.mark.asyncio
async def test_conversational_repetition_and_short_messages():
    """
    Test that:
    1. "धन्यवाद" gets a warm short close, not a repeated question.
    2. Three consecutive short messages ("ok", "aur kya help", "thanks") never produce two identical replies.
    3. The "15-20 दिन" follow-up is never sent twice.
    """
    phone = "919000000035"
    await sessions_repo.delete(phone)
    
    # Setup session: recommended is True, but asked_followup is False (meaning it is about to enter STEP_8)
    await sessions_repo.upsert(phone, {
        "current_step": "STEP_8",
        "collected_json": {
            "greeted": True,
            "name": "दिनेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "नहर",
            "crop": "Soybean",
            "problem_summary": "कीट का हमला",
            "recommended": True
        }
    })
    
    # 1. First turn: Dinesh says "सलाह के लिए शुक्रिया" -> should get dealer + 15-20 days follow-up (STEP_8)
    mock_responses = make_mock_complete(
        {},
        "दिनेश भाई, हमारे डीलर शर्मा सीड्स हैं। क्या आपने पिछले 15-20 दिनों में कोई खाद या दवा डाली है?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.t1",
            from_phone=phone,
            type="text",
            text="सलाह के लिए शुक्रिया",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("asked_followup") is True
        
        last_msg1 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "15-20" in last_msg1
        
    # 2. Second turn: Dinesh says "ok" -> should be intercepted by short-reply handler (ok category)
    # and return a brief acknowledgement, not another "15-20 दिन" question.
    msg = ParsedMessage(
        wamid="wamid.t2",
        from_phone=phone,
        type="text",
        text="ok",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg)
    
    session = await sessions_repo.get(phone)
    last_msg2 = mock_whatsapp_client.sent_messages[-1]["body"]
    assert "15-20" not in last_msg2
    # Ensure it didn't repeat the first message
    assert last_msg1 != last_msg2
    
    # 3. Third turn: Dinesh says "aur kya help kar sakte ho" -> should be intercepted by help handler (open help)
    msg = ParsedMessage(
        wamid="wamid.t3",
        from_phone=phone,
        type="text",
        text="aur kya help kar sakte ho",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg)
    
    session = await sessions_repo.get(phone)
    last_msg3 = mock_whatsapp_client.sent_messages[-1]["body"]
    assert "15-20" not in last_msg3
    assert any(term in last_msg3 for term in ["मदद", "सहायता", "खोज", "पहचानने"])
    assert last_msg2 != last_msg3
    
    # 4. Fourth turn: Dinesh says "धन्यवाद" -> should get warm close (thanks category)
    msg = ParsedMessage(
        wamid="wamid.t4",
        from_phone=phone,
        type="text",
        text="धन्यवाद",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg)
    
    session = await sessions_repo.get(phone)
    last_msg4 = mock_whatsapp_client.sent_messages[-1]["body"]
    assert "15-20" not in last_msg4
    assert any(term in last_msg4 for term in ["मदद", "खुशी", "बात"])
    assert last_msg3 != last_msg4


@pytest.mark.asyncio
async def test_conversational_unclear_and_out_of_scope():
    """
    Test Scenario:
    1. Unclear/gibberish message -> returns a polite clarification request.
    2. Second unclear/gibberish message -> returns a DIFFERENT clarification request.
    3. Third unclear/gibberish message -> concrete next step fallback (asks for crop).
    4. Out-of-scope message (PM-Kisan) -> honest "no reliable info" reply and steers back.
    5. Out-of-scope message (Mandi prices) -> honest "no reliable info" reply, steers back, and is different from the previous.
    6. Chemical dosage query -> safety warning, steers back.
    """
    phone = "919000000036"
    await sessions_repo.delete(phone)
    
    # Initialize session with full profile collected so that it is past onboarding
    await sessions_repo.upsert(phone, {
        "current_step": "STEP_6",
        "collected_json": {
            "greeted": True,
            "name": "Harsh",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "नहर",
            "crop": "Soybean"
        }
    })
    
    # -- Turn 1: Gibberish message --
    mock_responses = make_mock_complete(
        {"is_unclear": True, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "..."
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.gibberish1",
            from_phone=phone,
            type="text",
            text="asdfgh",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("clarify_attempts") == 1
        
        last_msg1 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Harsh" in last_msg1 or "हर्ष" in last_msg1
        assert any(term in last_msg1 for term in ["समझ", "बताएँगे", "खुलकर"])

    # -- Turn 2: Second Gibberish message --
    mock_responses = make_mock_complete(
        {"is_unclear": True, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "..."
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.gibberish2",
            from_phone=phone,
            type="text",
            text="qwerty",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("clarify_attempts") == 2
        
        last_msg2 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert last_msg1 != last_msg2  # Must vary and not repeat!

    # -- Turn 3: Third Gibberish message -> Falls back to concrete step --
    mock_responses = make_mock_complete(
        {"is_unclear": True, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "..."
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.gibberish3",
            from_phone=phone,
            type="text",
            text="zxcvb",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("clarify_attempts") == 0
        
        last_msg3 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "फसल" in last_msg3

    # -- Turn 4: Out-of-scope (PM Kisan) --
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": "government scheme", "asks_chemical_dosage": False},
        "..."
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.out1",
            from_phone=phone,
            type="text",
            text="PM kisan yojana kitna paisa milega?",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg4 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert any(term in last_msg4 for term in ["पक्की जानकारी", "विश्वसनीय जानकारी", "सटीक डेटा"])
        # Steers back
        assert any(term in last_msg4 for term in ["मदद", "सहायता", "बीज", "फसल"])

    # -- Turn 5: Out-of-scope (Mandi price) --
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": "mandi price", "asks_chemical_dosage": False},
        "..."
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.out2",
            from_phone=phone,
            type="text",
            text="aaj ka wheat mandi bhav kya hai?",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg5 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert any(term in last_msg5 for term in ["पक्की जानकारी", "विश्वसनीय जानकारी", "सटीक डेटा"])
        assert last_msg4 != last_msg5  # Must vary!

    # -- Turn 6: Chemical dosage query --
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": None, "asks_chemical_dosage": True},
        "..."
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.dosage1",
            from_phone=phone,
            type="text",
            text="monocrotophos spray quantity details?",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg6 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert any(term in last_msg6 for term in ["छिड़काव मात्रा", "सटीक मात्रा", "छिड़काव"])
        assert any(term in last_msg6 for term in ["डीलर", "कृषि अधिकारी", "कृषि केंद्र", "स्थानीय"])
        assert any(term in last_msg6 for term in ["बीज", "उत्पाद", "फसल"])


@pytest.mark.asyncio
async def test_agronomist_stunted_maize():
    """
    Test Scenario: "मक्का छोटा रह गया क्या डालूँ"
    Verifies:
    1. Extracts crop=Maize and problem.
    2. Receives agronomist advice about nutrient deficiency / watering.
    3. Bridges to approved maize product variety (e.g. VIGOUR 60A90) if fitting.
    4. Safe: no fabricated chemical names or precise dosages.
    """
    phone = "919000000037"
    await sessions_repo.delete(phone)
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "दिनेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "नहर",
            "crop": "Maize",
            "problem_clarified": True
        }
    })
    
    mock_responses = make_mock_complete(
        {"crop": "Maize", "problem": "छोटा रह गया क्या डालूँ"},
        "दिनेश भाई, मक्के की बढ़वार रुकने या छोटा रहने का मुख्य कारण नाइट्रोजन या जिंक की कमी हो सकती है। आप खेत में यूरिया या जिंक सल्फेट डाल सकते हैं और पानी का सही अंतराल बनाए रखें। अच्छे परिणाम और शानदार पैदावार के लिए आप हमारे Vigour 60A90 किस्म का चयन कर सकते हैं।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.stunted_maize",
            from_phone=phone,
            type="text",
            text="मक्का छोटा रह गया क्या डालूँ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("crop") == "Maize"
        assert session.collected_json.get("recommended") is True
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert any(term in last_msg for term in ["बढ़वार", "रुका", "छोटा", "कमी", "यूरिया", "जिंक", "नाइट्रोजन"])
        assert "Vigour 60A90" in last_msg


@pytest.mark.asyncio
async def test_agronomist_pest_caterpillar():
    """
    Test Scenario: "इल्ली लग गई कौन सी दवा मार देगी"
    Verifies:
    1. Receives general IPM agronomist advice.
    2. Tells them to confirm precise chemical pesticide and dosage with dealer/officer.
    3. Bridges to a pest-tolerant approved soybean product (e.g. Vigour 335).
    4. NO fabricated chemical dosage as fact.
    """
    phone = "919000000038"
    await sessions_repo.delete(phone)
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "राजेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "कुआँ",
            "crop": "Soybean",
            "problem_clarified": True
        }
    })
    
    mock_responses = make_mock_complete(
        {"crop": "Soybean", "problem": "इल्ली लग गई कौन सी दवा मार देगी"},
        "राजेश भाई, सोयाबीन में इल्ली/कीट नियंत्रण के लिए खेतों की सफाई रखें और फेरोमोन ट्रैप लगाएं। सही रासायनिक दवा और छिड़काव की मात्रा के लिए नज़दीकी डीलर या कृषि अधिकारी से पुष्टि करें। अगली बार कीट प्रतिरोधी किस्म Vigour 335 बोने पर विचार करें।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.pest_caterpillar",
            from_phone=phone,
            type="text",
            text="इल्ली लग गई कौन सी दवा मार देगी",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("recommended") is True
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert any(term in last_msg for term in ["इल्ली", "कीट", "सफाई", "नियंत्रण", "ट्रैप"])
        assert any(term in last_msg for term in ["डीलर", "कृषि अधिकारी", "पुष्टि करें"])
        assert "Vigour 335" in last_msg


@pytest.mark.asyncio
async def test_agronomist_yellow_leaves():
    """
    Test Scenario: "पत्ती पीली पड़ रही है"
    Verifies:
    1. Explains likely causes (nitrogen deficiency, waterlogging/stress).
    2. Recommends next practical steps.
    """
    phone = "919000000039"
    await sessions_repo.delete(phone)
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "राजेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "कुआँ",
            "crop": "Soybean"
        }
    })
    
    mock_responses = make_mock_complete(
        {"crop": "Soybean", "problem": "पत्ती पीली पड़ रही है"},
        "राजेश भाई, पत्तियों के पीले पड़ने का मुख्य कारण खेत में पानी का जमाव (waterlogging) या नाइट्रोजन की कमी हो सकता है। जल निकासी ठीक करें और हल्की सिंचाई के बाद यूरिया डालें।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.yellow_leaves",
            from_phone=phone,
            type="text",
            text="पत्ती पीली पड़ रही है",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert any(term in last_msg for term in ["पीले", "पीली", "नाइट्रोजन", "कमी", "जल", "पानी", "निकासी"])


@pytest.mark.asyncio
async def test_soft_funnel_and_product_recommendation():
    """
    Test Scenario: Soft Funnel and Product Recommendation
    Verifies:
    1. First turn: Acknowledges problem and asks 1 clarifying question (symptoms, crop stage, or past treatments).
    2. Second turn: Gives practical agronomist advice, then recommends a fitting product with dealer info.
    """
    phone = "919000000080"
    await sessions_repo.delete(phone)
    
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "रामपाल",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "नहर",
            "crop": "Soybean"
        }
    })
    
    # Turn 1: Farmer introduces a pest problem.
    calls = []
    async def mock_call_turn1(system, user, json_mode=False):
        calls.append((system, user, json_mode))
        if json_mode or "extraction" in system:
            return json.dumps({"problem": "इल्ली लग गई"})
        return "रामपाल भाई, सोयाबीन की फसल में इल्ली की समस्या के लिए क्या यह पत्तियों पर है या तने पर? आपने इसके लिए कोई दवा छिड़की है?"

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_call_turn1)):
        msg = ParsedMessage(
            wamid="wamid.sf1",
            from_phone=phone,
            type="text",
            text="सोयाबीन में इल्ली लगी है",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert not session.collected_json.get("recommended")
        assert session.collected_json.get("problem_clarified") is True
        assert session.collected_json.get("problem_summary") == "इल्ली लग गई"
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "इल्ली" in last_msg

    # Turn 2: Farmer responds to the clarification
    calls2 = []
    async def mock_call_turn2(system, user, json_mode=False):
        calls2.append((system, user, json_mode))
        if json_mode or "extraction" in system:
            return json.dumps({})
        return "रामपाल भाई, सोयाबीन में इल्ली के लिए आप खेत साफ रखें। इसके लिए हमारे Vigour 335 किस्म का चयन कर सकते हैं। उज्जैन में डीलर शर्मा सीड्स से संपर्क करें।"

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_call_turn2)):
        msg2 = ParsedMessage(
            wamid="wamid.sf2",
            from_phone=phone,
            type="text",
            text="पत्तियों पर है",
            timestamp="1718563860"
        )
        await conversation_router.route_message(msg2)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("recommended") is True
        assert "Vigour 335" in session.collected_json.get("all_recommended_ids") or "Vigour 335" in session.collected_json.get("last_recommended_ids")
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour 335" in last_msg


@pytest.mark.asyncio
async def test_pure_advice_no_product_push():
    """
    Test Scenario: Pure-advice query with no fitting product.
    Verifies: Gives agronomist advice without pushing any product when no product fits/exists.
    """
    phone = "919000000081"
    await sessions_repo.delete(phone)
    
    # 1. Setup a session for Tomato crop (which has no seeded products in conftest.py)
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "दिलीप",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "नहर",
            "crop": "Tomato",
            "problem_summary": "पत्ते सिकुड़ रहे हैं",
            "problem_clarified": True
        }
    })
    
    mock_responses = make_mock_complete(
        {},
        "दिलीप भाई, टमाटर के पत्तों के सिकुड़ने (leaf curl) का कारण वायरस या थ्रिप्स कीट हो सकता है। नियंत्रण के लिए संक्रमित पौधों को हटा दें। वर्तमान में हमारे पास टमाटर के स्वीकृत Vigour बीज उपलब्ध नहीं हैं।"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.pure_advice",
            from_phone=phone,
            type="text",
            text="क्या दवा डालूँ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("recommended") is True
        assert session.collected_json.get("last_recommended_ids") == []
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "टमाटर" in last_msg
        assert "सिकुड़ने" in last_msg
        # Ensure no product was pushed
        assert "Vigour" not in last_msg or "Vigour बीज उपलब्ध नहीं" in last_msg


@pytest.mark.asyncio
async def test_warm_thanks_close_no_pitch():
    """
    Test Scenario: Farmer says "धन्यवाद" which closes the loop warmly with no product pitch.
    """
    phone = "919000000082"
    await sessions_repo.delete(phone)
    
    await sessions_repo.upsert(phone, {
        "current_step": "STEP_8",
        "collected_json": {
            "greeted": True,
            "name": "दिनेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "नहर",
            "crop": "Soybean",
            "problem_summary": "इल्ली का हमला",
            "recommended": True
        }
    })
    
    msg = ParsedMessage(
        wamid="wamid.thanks",
        from_phone=phone,
        type="text",
        text="धन्यवाद",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg)
    
    last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
    assert any(term in last_msg for term in ["धन्यवाद", "मदद", "किसान भाई", "खुशी", "उपज"])
    assert "Vigour 335" not in last_msg and "Vigour 9560" not in last_msg


@pytest.mark.asyncio
async def test_no_repeated_pitches():
    """
    Test Scenario: Verifies that products in `all_recommended_ids` are not repeatedly pitched.
    """
    phone = "919000000083"
    await sessions_repo.delete(phone)
    
    # 1. Setup session where Vigour 335 is already recommended
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "greeted": True,
            "name": "राजेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "total_land": 5.0,
            "water_source": "कुआँ",
            "crop": "Soybean",
            "problem_summary": "इल्ली का हमला",
            "problem_clarified": True,
            "all_recommended_ids": ["Vigour 335"]
        }
    })
    
    # The AI should recommend Vigour 9560 (the only remaining approved soybean product), NOT Vigour 335.
    mock_responses = make_mock_complete(
        {},
        "राजेश भाई, सोयाबीन में इल्ली के लिए खेत साफ रखें। पहले हमने Vigour 335 की बात की थी, अब आप Vigour 9560 बीज बोने पर विचार करें जो कि कम समय में तैयार होता है。"
    )
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.repeat_pitch",
            from_phone=phone,
            type="text",
            text="दवा बताओ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("recommended") is True
        all_recs = session.collected_json.get("all_recommended_ids", [])
        assert "Vigour 9560" in all_recs
        assert "Vigour 335" in all_recs
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour 9560" in last_msg


@pytest.mark.asyncio
async def test_conversational_greeting_onboarding_and_whitelist():
    """
    Test Scenario: Verifies that greetings like "Hye", "Hello ji namaskar" are NOT treated as unclear
    and successfully run the onboarding welcome flow (STEP_0).
    """
    phone = "919000000084"
    
    # Test "Hye"
    await sessions_repo.delete(phone)
    mock_responses = make_mock_complete(
        {},
        "नमस्ते 🙏 Vigour Seeds में आपका स्वागत है। मैं आपका कृषि विशेषज्ञ Vigour मित्र हूँ। मैं आपकी क्या मदद कर सकता हूँ?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.whitelist1",
            from_phone=phone,
            type="text",
            text="Hye",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("greeted") is True
        
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour मित्र" in last_msg
        assert "नमस्ते" in last_msg

    # Test "Hello ji namaskar"
    await sessions_repo.delete(phone)
    mock_responses2 = make_mock_complete(
        {},
        "नमस्ते 🙏 Vigour Seeds में आपका स्वागत है। मैं आपका कृषि विशेषज्ञ Vigour मित्र हूँ। मैं आपकी क्या मदद कर सकता हूँ?"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses2)):
        msg2 = ParsedMessage(
            wamid="wamid.whitelist2",
            from_phone=phone,
            type="text",
            text="Hello ji namaskar",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg2)
        
        session2 = await sessions_repo.get(phone)
        assert session2.collected_json.get("greeted") is True
        
        last_msg2 = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour मित्र" in last_msg2
        assert "नमस्ते" in last_msg2


@pytest.mark.asyncio
async def test_sc_40_crop_stage_reply():
    phone = "919000000091"
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
    # Mock LLM returns is_unclear = True (simulating a false positive)
    # Our Python safety net should override this and treat it as in-scope!
    mock_responses = make_mock_complete(
        {"is_unclear": True, "out_of_scope_topic": "unknown", "asks_chemical_dosage": False, "problem": None},
        "आपकी सोयाबीन फसल अभी कितने दिन की है?"
    )
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
        assert "माफ़" not in last_msg


@pytest.mark.asyncio
async def test_sc_khad_advice():
    phone = "919000000092"
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
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "सोयाबीन में आप DAP और यूरिया डाल सकते हैं।"
    )
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


@pytest.mark.asyncio
async def test_sc_dawai_advice():
    phone = "919000000093"
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
            "problem_summary": "पीला मोज़ेक वायरस"
        }
    })
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "पीला मोज़ेक के लिए आप सामान्य नियंत्रण अपनाएं और सही दवा की मात्रा डीलर से पूछें।"
    )
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
        assert "माफ़ कीजिएगा" not in last_msg


@pytest.mark.asyncio
async def test_sc_list_products_soybean():
    phone = "919000000094"
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
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "नमस्ते"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_soybean_seeds",
            from_phone=phone,
            type="text",
            text="soybean ke acchi kism batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour 9560" in last_msg or "Vigour 335" in last_msg
        assert "Vigour Premium Gold" not in last_msg


@pytest.mark.asyncio
async def test_sc_crop_switch_variety_guard():
    phone = "919000000095"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल",
            "crop": "Dhan",
            "recommended": True,
            "all_recommended_ids": ["Vigour Premium Gold"]
        }
    })
    mock_responses = make_mock_complete(
        {"crop": "Soybean", "is_unclear": False, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "नमस्ते"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_switch",
            from_phone=phone,
            type="text",
            text="Mujhe soybean ke kism batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour 9560" in last_msg or "Vigour 335" in last_msg
        assert "Vigour Premium Gold" not in last_msg


@pytest.mark.asyncio
async def test_sc_help_capabilities():
    phone = "919000000096"
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
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "नमस्ते"
    )
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
        assert "फसल की समस्या" in last_msg or "बीमारी" in last_msg or "खाद-पानी" in last_msg


@pytest.mark.asyncio
async def test_sc_pm_kisan_out_of_scope():
    phone = "919000000097"
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
    mock_responses = make_mock_complete(
        {"is_unclear": False, "out_of_scope_topic": "government scheme", "asks_chemical_dosage": False},
        "योजना के बारे में जानकारी नहीं है"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_scheme",
            from_phone=phone,
            type="text",
            text="PM Kisan ka paisa kab aayega",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert any(word in last_msg for word in ["योजनाओं", "लोन", "बीमा", "मंडी", "सटीक डेटा"])



@pytest.mark.asyncio
async def test_sc_placeholder_problem_handling():
    phone = "919000000098"
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
            "problem_summary": "स्पष्ट लक्षण नहीं हैं"
        }
    })
    mock_responses = make_mock_complete(
        {"is_unclear": True, "out_of_scope_topic": None, "asks_chemical_dosage": False},
        "मुझे समझ नहीं आया"
    )
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_placeholder",
            from_phone=phone,
            type="text",
            text="xyzabc",
            timestamp="1718563800"
        )
        session = await sessions_repo.get(phone)
        collected = session.collected_json
        collected["clarify_attempts"] = 2
        await sessions_repo.upsert(phone, {"collected_json": collected})
        
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "स्पष्ट लक्षण नहीं हैं" not in last_msg
        assert "क्या दिक्कत आ रही है" in last_msg


@pytest.mark.asyncio
async def test_sc_list_products_no_crop():
    phone = "919000000099"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "name": "महिपाल",
            "district": "Dhar",
            "state": "Madhya Pradesh",
            "total_land": 10.0,
            "water_source": "ट्यूबवेल"
        }
    })
    msg = ParsedMessage(
        wamid="wamid.test_no_crop",
        from_phone=phone,
        type="text",
        text="saare product batao",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg)
    last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
    assert "आप किस फसल के बीजों" in last_msg


@pytest.mark.asyncio
async def test_sc_list_products_zero_approved():
    phone = "919000000100"
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
    msg = ParsedMessage(
        wamid="wamid.test_zero_approved",
        from_phone=phone,
        type="text",
        text="Veegor ke saare product batao",
        timestamp="1718563800"
    )
    await conversation_router.route_message(msg)
    last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
    assert "कोई अनुमोदित Vigour बीज उपलब्ध नहीं हैं" in last_msg
    assert "संपर्क" in last_msg

