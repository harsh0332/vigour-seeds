import pytest
import json
from unittest.mock import AsyncMock, patch
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

# =====================================================================
# GROUP A — Greeting & onboarding
# =====================================================================

@pytest.mark.parametrize("greet_word", ["hi", "hello", "namaste", "ram ram"])
@pytest.mark.asyncio
async def test_group_a_greetings(greet_word):
    phone = "919000005001"
    await sessions_repo.delete(phone)
    # Send /reset
    await conversation_router.route_message(ParsedMessage(wamid="w_reset", from_phone=phone, type="text", text="/reset", timestamp="1718563800"))
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "नमस्ते किसान भाई! 🌱 मैं Vigour मित्र — Vigour Seeds का कृषि सहायक। पहले बताइए, आपका नाम क्या है?"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w_greet",
            from_phone=phone,
            type="text",
            text=greet_word,
            timestamp="1718563801"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour मित्र" in last_body
        assert "नाम क्या है" in last_body

@pytest.mark.asyncio
async def test_group_a_step_by_step_onboarding():
    phone = "919000005002"
    await sessions_repo.delete(phone)
    # Send /reset
    await conversation_router.route_message(ParsedMessage(wamid="w_reset", from_phone=phone, type="text", text="/reset", timestamp="1718563800"))
    mock_whatsapp_client.clear()

    # 1. Greetings
    mock_responses_1 = make_mock_complete_sequence([
        {"action": "reply", "message": "नमस्ते! आपका नाम क्या है?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses_1)):
        await conversation_router.route_message(ParsedMessage(wamid="w_g", from_phone=phone, type="text", text="Namaste", timestamp="1718563801"))
        assert "नाम" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 2. Farmer replies name. Bot saves name and asks state/district.
    mock_responses_2 = make_mock_complete_sequence([
        {"action": "save_profile", "fields": {"name": "Ramesh"}},
        {"action": "reply", "message": "धन्यवाद रमेश जी। आप किस राज्य और ज़िले से हैं?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses_2)):
        await conversation_router.route_message(ParsedMessage(wamid="w_n", from_phone=phone, type="text", text="Mera naam Ramesh hai", timestamp="1718563802"))
        assert "राज्य" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 3. Farmer replies state/district. Bot saves location and asks land.
    mock_responses_3 = make_mock_complete_sequence([
        {"action": "save_profile", "fields": {"state": "Madhya Pradesh", "district": "Ujjain"}},
        {"action": "reply", "message": "ठीक है रमेश जी। आपकी कुल कितनी ज़मीन है?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses_3)):
        await conversation_router.route_message(ParsedMessage(wamid="w_l", from_phone=phone, type="text", text="Ujjain, MP", timestamp="1718563803"))
        assert "ज़मीन" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 4. Farmer replies land. Bot saves land and asks water source.
    mock_responses_4 = make_mock_complete_sequence([
        {"action": "save_profile", "fields": {"total_land": 5.0}},
        {"action": "reply", "message": "धन्यवाद। सिंचाई का क्या साधन है?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses_4)):
        await conversation_router.route_message(ParsedMessage(wamid="w_w", from_phone=phone, type="text", text="5 acre", timestamp="1718563804"))
        assert "सिंचाई" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 5. Farmer replies water source. Bot saves water source and asks how it can help.
    mock_responses_5 = make_mock_complete_sequence([
        {"action": "save_profile", "fields": {"water_source": "Tube Well"}},
        {"action": "reply", "message": "धन्यवाद। अब बताइए मैं आपकी आज क्या मदद कर सकता हूँ?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses_5)):
        await conversation_router.route_message(ParsedMessage(wamid="w_h", from_phone=phone, type="text", text="TUBEWELL", timestamp="1718563805"))
        assert "मदद" in mock_whatsapp_client.sent_messages[-1]["body"]

@pytest.mark.asyncio
async def test_group_a_no_reask_known_or_unknown():
    phone = "919000005003"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "name": "Ramesh",
            "state": "Madhya Pradesh",
            "district": "Ujjain",
            "total_land": "unknown",
            "water_source": None
        }
    })
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "नमस्ते रमेश जी, आपकी सिंचाई का मुख्य साधन क्या है?"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="hello",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "सिंचाई" in last_body
        assert "राज्य" not in last_body
        assert "ज़मीन" not in last_body
        assert "नाम" not in last_body

# =====================================================================
# GROUP B — Direct seed request
# =====================================================================

@pytest.mark.parametrize("crop_name, user_query, variety_sample", [
    ("Maize", "makka ke beej batao", "VIGOUR 60A90"),
    ("Soybean", "soybean ke liye kaunsa beej chahiye", "Vigour 335"),
    ("Wheat", "gehun ka kaunsa variety achha hai", "Vigour Wheat Sample"),
    ("Tomato", "tamatar ke beej", "Vigour Tomato Sample"),
    ("Paddy", "dhaan ka beej chahiye", "Vigour Paddy Sample"),
    ("Chilli", "chilli ke beej batao", "Vigour Chilli Sample"),
    ("Okra", "okra beej", "Vigour Okra Sample")
])
@pytest.mark.asyncio
async def test_group_b_direct_seed_request(crop_name, user_query, variety_sample):
    phone = f"91900000501{ord(crop_name[0])}"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    # Map crop name to its database canonical equivalent
    db_crop = "Hot Pepper (Chilli)" if crop_name == "Chilli" else crop_name

    # Seed the product
    db_prod = {
        "product_id": f"PROD_{crop_name.upper()}",
        "variety_name": variety_sample,
        "crop": db_crop,
        "duration_days": "100",
        "mrp_inr": 200.0,
        "key_traits": "High Yield",
        "pest_disease_tolerance": "Tolerant",
        "pack_size": "10 kg",
        "approved_for_recommendation": "Y",
        "target_region": "MP"
    }
    in_memory_db.tables["products"] = [db_prod]

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": db_crop, "problem": "-"},
        {"action": "reply", "message": f"{crop_name} के लिए *{variety_sample}* बीज सबसे बढ़िया है।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text=user_query,
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert variety_sample in last_body
        assert "स्थिति" not in last_body
        assert "समस्या" not in last_body

# =====================================================================
# GROUP C — No-product crops
# =====================================================================

@pytest.mark.parametrize("crop_name, user_query", [
    ("Sorghum", "jowar ke beej batao"),
    ("Coriander", "dhaniya ka kaunsa beej aata hai"),
    ("Garlic", "lahsun ka beej chahiye")
])
@pytest.mark.asyncio
async def test_group_c_no_product_crops(crop_name, user_query):
    phone = f"91900000502{ord(crop_name[0])}"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    in_memory_db.tables["products"] = [
        {"product_id": "P1", "crop": "Maize", "approved_for_recommendation": "Y"},
        {"product_id": "P2", "crop": "Soybean", "approved_for_recommendation": "Y"}
    ]

    mock_responses = make_mock_complete_sequence([
        {"action": "list_available_crops"},
        {"action": "reply", "message": f"माफ़ कीजिए किसान भाई, अभी हमारे पास {crop_name} के लिए Vigour Seeds के अनुमोदित बीज नहीं हैं। हमारे पास Maize, Soybean के बीज हैं।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text=user_query,
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "नहीं" in last_body or "उपलब्ध नहीं" in last_body
        assert "Maize" in last_body

# =====================================================================
# GROUP D — Which crops do you have?
# =====================================================================

@pytest.mark.parametrize("query_text", [
    "tumhare paas kon kon si fasal ke beej hain",
    "saari fasal batao",
    "kya kya hai tumhare paas"
])
@pytest.mark.asyncio
async def test_group_d_list_crops(query_text):
    phone = "919000005030"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    in_memory_db.tables["products"] = [
        {"product_id": "P1", "crop": "Maize", "approved_for_recommendation": "Y"},
        {"product_id": "P2", "crop": "Soybean", "approved_for_recommendation": "Y"}
    ]

    mock_responses = make_mock_complete_sequence([
        {"action": "list_available_crops"},
        {"action": "reply", "message": "हमारे पास Maize और Soybean के बीज उपलब्ध हैं। आप किसका बीज चाहते हैं?"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text=query_text,
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Maize" in last_body
        assert "Soybean" in last_body

# =====================================================================
# GROUP E — Crop switching
# =====================================================================

@pytest.mark.parametrize("crop_a, crop_b, transition_query, variety_b", [
    ("Sorghum", "Maize", "ab mujhe makke ka beej chahiye", "VIGOUR 60A90"),
    ("Paddy", "Soybean", "chalo dhaan chodo, soybean ka batana", "Vigour 335")
])
@pytest.mark.asyncio
async def test_group_e_crop_switching(crop_a, crop_b, transition_query, variety_b):
    phone = f"91900000504{ord(crop_b[0])}"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "name": "Ramesh",
            "crop": crop_a
        }
    })
    mock_whatsapp_client.clear()

    in_memory_db.tables["products"] = [
        {"product_id": f"P_{crop_b}", "variety_name": variety_b, "crop": crop_b, "approved_for_recommendation": "Y"}
    ]

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": crop_b, "problem": "-"},
        {"action": "reply", "message": f"{crop_b} के लिए *{variety_b}* बीज उपलब्ध है।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text=transition_query,
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert variety_b in last_body
        
        session = await sessions_repo.get(phone)
        assert session.collected_json.get("crop") == crop_b

# =====================================================================
# GROUP F — General agronomy questions
# =====================================================================

@pytest.mark.parametrize("crop_name, user_query, variety_sample", [
    ("Maize", "makka me keede lag gaye", "VIGOUR 60A90"),
    ("Soybean", "soybean ki patti pili ho rahi", "Vigour 335"),
    ("Wheat", "gehu me dane chote hai", "Vigour Wheat Sample"),
    ("Tomato", "tamatar me fafund rog hai", "Vigour Tomato Sample"),
    ("Chilli", "chilli me khad kab dalu", "Vigour Chilli Sample"),
    ("Okra", "okra me paani kab du", "Vigour Okra Sample")
])
@pytest.mark.asyncio
async def test_group_f_agronomy(crop_name, user_query, variety_sample):
    phone = f"91900000505{ord(crop_name[0])}"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    # Map crop name to its database canonical equivalent
    db_crop = "Hot Pepper (Chilli)" if crop_name == "Chilli" else crop_name

    db_prod = {
        "product_id": f"PROD_{crop_name.upper()}",
        "variety_name": variety_sample,
        "crop": db_crop,
        "approved_for_recommendation": "Y"
    }
    in_memory_db.tables["products"] = [db_prod]

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": db_crop, "problem": user_query},
        {"action": "reply", "message": f"सलाह: खेत में उचित खाद व नमी बनाए रखें। सही दवा की खुराक के लिए नज़दीकी डीलर से संपर्क करें। इसके लिए हमारी *{variety_sample}* किस्म अच्छी है।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text=user_query,
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert variety_sample in last_body
        assert "डीलर" in last_body

# =====================================================================
# GROUP G — Short replies in context
# =====================================================================

@pytest.mark.asyncio
async def test_group_g_short_replies_yes():
    phone = "919000005060"
    await sessions_repo.delete(phone)
    from app.db.repositories.conversations import conversations_repo
    await conversations_repo.delete(phone)

    await sessions_repo.upsert(phone, {
        "collected_json": {
            "name": "Ramesh",
            "crop": "Maize"
        }
    })

    await conversations_repo.log({
        "whatsapp_phone": phone,
        "direction": "outbound",
        "message_text": "क्या आपको मक्के का बीज चाहिए?",
        "wamid": "bot_ask",
        "message_id": "msg_bot_ask",
        "message_type": "text",
        "handled_by": "bot",
        "lead_id": "L_test"
    })
    mock_whatsapp_client.clear()

    in_memory_db.tables["products"] = [
        {"product_id": "P_Maize", "variety_name": "VIGOUR 60A90", "crop": "Maize", "approved_for_recommendation": "Y"}
    ]

    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Maize", "problem": "-"},
        {"action": "reply", "message": "यहाँ मक्के के लिए *VIGOUR 60A90* बीज उपलब्ध है।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="haan",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "VIGOUR 60A90" in last_body

@pytest.mark.asyncio
async def test_group_g_short_replies_no():
    phone = "919000005061"
    await sessions_repo.delete(phone)
    from app.db.repositories.conversations import conversations_repo
    await conversations_repo.delete(phone)

    await sessions_repo.upsert(phone, {
        "collected_json": {
            "name": "Ramesh",
            "crop": "Maize"
        }
    })

    await conversations_repo.log({
        "whatsapp_phone": phone,
        "direction": "outbound",
        "message_text": "क्या आपको मक्के का बीज चाहिए?",
        "wamid": "bot_ask",
        "message_id": "msg_bot_ask",
        "message_type": "text",
        "handled_by": "bot",
        "lead_id": "L_test"
    })
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "कोई बात नहीं भाई। मैं आपकी और क्या मदद कर सकता हूँ?"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="nahi",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "कोई बात नहीं" in last_body
        assert "मदद" in last_body

# =====================================================================
# GROUP H — Identity / scope / safety
# =====================================================================

@pytest.mark.asyncio
async def test_group_h_identity_medicine():
    phone = "919000005070"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "किसान भाई, Vigour Seeds केवल अच्छे बीज बनाती है, दवा नहीं। दवा के लिए आप नज़दीकी डीलर से पूछें।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="Vigour ki koi dawai hai kya",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "दवा" in last_body
        assert "बीज" in last_body

@pytest.mark.parametrize("off_topic_query", [
    "joke sunao",
    "python code to reverse string"
])
@pytest.mark.asyncio
async def test_group_h_off_topic_obvious_refusal_no_llm(off_topic_query):
    phone = "919000005071"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    # The off-topic classifiers handle obvious cases directly, so no LLM call is made.
    mock_complete = AsyncMock()
    with patch.object(mock_ai_provider, "complete", mock_complete):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text=off_topic_query,
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "खेती" in last_body or "कृषि" in last_body
        mock_complete.assert_not_called()

@pytest.mark.asyncio
async def test_group_h_off_topic_non_obvious_refusal_via_llm():
    phone = "919000005074"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "माफ़ कीजिए भाई, मैं केवल खेती-बाड़ी और बीजों से जुड़े सवालों के जवाब दे सकता हूँ।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="aaj match kaun jeeta",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "खेती" in last_body or "बीज" in last_body

@pytest.mark.parametrize("query_text", [
    "PM Kisan ka paisa kab aayega",
    "aaj mandi bhav kya hai"
])
@pytest.mark.asyncio
async def test_group_h_gov_scheme_mandi_price(query_text):
    phone = "919000005072"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "माफ़ कीजिए, मेरे पास सरकारी योजनाओं या मंडी भाव की पक्की जानकारी नहीं है।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text=query_text,
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "पक्की जानकारी नहीं" in last_body or "माफ़ कीजिए" in last_body

@pytest.mark.asyncio
async def test_group_h_image_message_polite_refusal():
    phone = "919000005073"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_complete = AsyncMock()
    with patch.object(mock_ai_provider, "complete", mock_complete):
        msg = ParsedMessage(
            wamid="wamid.image_upload",
            from_phone=phone,
            type="image",
            media_id="media_12345",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        
        assert "फोटो नहीं देख पाता" in last_msg
        mock_complete.assert_not_called()

# =====================================================================
# GROUP I — No loops / no broken text / no fabrication
# =====================================================================

@pytest.mark.asyncio
async def test_group_i_no_consecutive_asks():
    phone = "919000005081"
    await sessions_repo.delete(phone)
    from app.db.repositories.conversations import conversations_repo
    await conversations_repo.delete(phone)

    await conversations_repo.log({
        "whatsapp_phone": phone,
        "direction": "outbound",
        "message_text": "मक्के की फसल अभी कितने दिन की है?",
        "wamid": "prev_out_wamid",
        "message_id": "msg_prev_out",
        "message_type": "text",
        "handled_by": "bot",
        "lead_id": "L_test"
    })
    
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "crop": "Maize"
        }
    })
    mock_whatsapp_client.clear()

    # The first model action is "ask", which should trigger consecutive ask guard,
    # requesting the model to reply instead.
    mock_responses = make_mock_complete_sequence([
        {"action": "ask", "message": "क्या आपने यूरिया डाला था?"},
        {"action": "reply", "message": "मक्के में संतुलित सिंचाई व खाद का उपयोग करें।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="nahi pata",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "संतुलित सिंचाई" in last_body

@pytest.mark.asyncio
async def test_group_i_no_repeated_replies():
    phone = "919000005082"
    await sessions_repo.delete(phone)
    await sessions_repo.upsert(phone, {
        "collected_json": {
            "greeted": True,
            "sent_messages_history": []
        }
    })
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "बहुत बढ़िया भाई!"},
        {"action": "reply", "message": "जी बिल्कुल!"},
        {"action": "reply", "message": "ठीक है!"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        replies = []
        for text in ["ok", "thanks", "aur kuch"]:
            await conversation_router.route_message(ParsedMessage(
                wamid=f"w_{text}",
                from_phone=phone,
                type="text",
                text=text,
                timestamp="1718563800"
            ))
            replies.append(mock_whatsapp_client.sent_messages[-1]["body"])
            
        assert replies[0] != replies[1]
        assert replies[1] != replies[2]

@pytest.mark.asyncio
async def test_group_i_no_empty_placeholders():
    phone = "919000005083"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "नमस्ते! हम फसल प्रबंधन में मदद करते हैं।"}
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="hello",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "null" not in last_body
        assert "none" not in last_body.lower()
        assert "unknown" not in last_body.lower()
        assert "{" not in last_body
        assert "}" not in last_body

@pytest.mark.asyncio
async def test_group_i_fabricated_product_reprompt():
    phone = "919000005084"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()

    in_memory_db.tables["products"] = [
        {"product_id": "P_Maize", "variety_name": "VIGOUR 60A90", "crop": "Maize", "approved_for_recommendation": "Y"}
    ]

    # First turn: LLM tries to reply with fabricated product name 'Vigour Maize 99'.
    # Second turn (after reprompt): LLM replies with approved variety.
    mock_responses = make_mock_complete_sequence([
        {"action": "find_products", "crop": "Maize", "problem": "-"},
        {"action": "reply", "message": "यहाँ Vigour Maize 99 बीज अच्छा है।"}, # Fabricated!
        {"action": "reply", "message": "यहाँ मक्के के लिए *VIGOUR 60A90* बीज अच्छा है।"} # Grounded
    ])

    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(
            wamid="w1",
            from_phone=phone,
            type="text",
            text="makke ka beej batao",
            timestamp="1718563800"
        ))
        
        last_body = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Maize 99" not in last_body
        assert "VIGOUR 60A90" in last_body
