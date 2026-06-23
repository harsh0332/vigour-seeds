import pytest
import json
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from conftest import in_memory_db, mock_whatsapp_client, mock_ai_provider
from app.whatsapp.models import ParsedMessage
from app.flows.router import conversation_router
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo

@pytest.mark.asyncio
async def test_conversational_greeting():
    """
    Test Scenario 1: Warm greeting when farmer types a greeting.
    """
    phone = "919000000010"
    
    mock_responses = [
        json.dumps({
            "action": "reply",
            "message": "नमस्ते 🙏 Vigour Seeds में आपका स्वागत है। मैं आपका कृषि विशेषज्ञ Vigour मित्र हूँ। मैं आपकी क्या मदद कर सकता हूँ?"
        }, ensure_ascii=False)
    ]
    
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
    
    # 1. First turn: Model calls normalize_location tool.
    # 2. Second turn: Model returns final reply with updated profile.
    mock_responses = [
        json.dumps({
            "action": "normalize_location",
            "args": {"text": "उज्जैन, मध्य प्रदेश"}
        }, ensure_ascii=False),
        json.dumps({
            "action": "reply",
            "message": "धन्यवाद! मैंने आपका जिला उज्जैन और राज्य मध्य प्रदेश दर्ज कर लिया है।",
            "updated_profile": {
                "name": "रामजी",
                "district": "Ujjain",
                "state": "Madhya Pradesh",
                "district_raw": "उज्जैन"
            }
        }, ensure_ascii=False)
    ]
    
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
        assert "उज्जैन" in last_msg
        assert "मध्य प्रदेश" in last_msg
        
        # Verify Session State is saved in Supabase / In-Memory DB
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
    
    # Let's seed an unapproved product and a product with null price to test filtering and fallback
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
    
    # Update recommendation rule in memory to include the new product id
    for r in in_memory_db.tables["recommendation_rules"]:
        if r["rule_id"] == "R002":
            r["recommended_product_ids"] = "PROD_S1, PROD_S2, PROD_S3_NULL_PRICE"
            
    # 1. First turn: Model calls find_products tool.
    # 2. Second turn: Model returns final reply with recommendations.
    mock_responses = [
        json.dumps({
            "action": "find_products",
            "args": {"crop": "Soybean", "problem": "sowing"}
        }, ensure_ascii=False),
        json.dumps({
            "action": "reply",
            "message": "सोयाबीन बुवाई के लिए ये उत्पाद हैं:\n- Vigour 335 (उच्च उपज, कीमत: 150 रुपये)\n- Vigour Premium (रोग प्रतिरोधी, रेट की जानकारी के लिए अपने नज़दीकी डीलर से संपर्क करें)",
            "updated_profile": {
                "crop": "Soybean",
                "crop_stage": "sowing",
                "last_recommended_ids": ["PROD_S1", "PROD_S3_NULL_PRICE"]
            }
        }, ensure_ascii=False)
    ]
    
    # Setup session with name & location so it's a complete lead
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "name": "हरीश",
            "district": "Ujjain",
            "state": "Madhya Pradesh"
        }
    })
    
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
        
        # Verify unapproved variety was filtered out by find_products tool
        # We can directly invoke the tool_find_products to verify filter
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
    
    # Seed session profile containing the crop name Soybean
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "name": "दीपक",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "crop": "Soybean"
        }
    })
    
    # Setup conversation history to simulate multiple turns
    in_memory_db.tables["conversations"].append({
        "whatsapp_phone": phone,
        "direction": "inbound",
        "message_text": "मैंने सोयाबीन बोया है",
        "created_at": "2026-06-16T12:00:00Z"
    })
    in_memory_db.tables["conversations"].append({
        "whatsapp_phone": phone,
        "direction": "outbound",
        "message_text": "बहुत बढ़िया! आपकी सोयाबीन फसल के बारे में बताएं।",
        "created_at": "2026-06-16T12:01:00Z"
    })
    
    mock_responses = [
        # Model should check history and call find_products for Soybean and pest_attack
        json.dumps({
            "action": "find_products",
            "args": {"crop": "Soybean", "problem": "pest_attack"}
        }, ensure_ascii=False),
        json.dumps({
            "action": "reply",
            "message": "कीटों के लिए आप Vigour 335 का उपयोग कर सकते हैं।"
        }, ensure_ascii=False)
    ]
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)) as mock_complete:
        msg = ParsedMessage(
            wamid="wamid.test_mem",
            from_phone=phone,
            type="text",
            text="पत्तियों में कीड़े लग गए हैं",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        # Verify that the complete call was made and the user prompt contained Soybean in history/profile
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
    
    # Seed session profile containing location Ujjain, Madhya Pradesh
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "name": "राजेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh"
        }
    })
    
    mock_responses = [
        json.dumps({
            "action": "find_dealer",
            "args": {"state": "Madhya Pradesh", "district": "Ujjain"}
        }, ensure_ascii=False),
        json.dumps({
            "action": "reply",
            "message": "उज्जैन में हमारे डीलर शर्मा सीड्स हैं (फ़ोन: 918888888888)।"
        }, ensure_ascii=False)
    ]
    
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
    
    # Mock download_media
    mock_download.download_media = AsyncMock(return_value=(b"mock_bytes", "image/jpeg"))
    
    # Seed session profile containing crop details
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "name": "सुरेश",
            "district": "Ujjain",
            "state": "Madhya Pradesh",
            "crop": "Soybean"
        }
    })
    
    # Mock vision service to return low confidence (e.g. 0.4) and needs_human = True
    with patch("app.ai.vision.vision_service.diagnose", AsyncMock(return_value={
        "problem_category": "fungal_disease",
        "severity": "medium",
        "confidence": 0.4,
        "visible_symptoms_hindi": "पत्ते पीले होना",
        "needs_human": True
    })):
        mock_responses = [
            json.dumps({
                "action": "reply",
                "message": "हमारे एग्रोनॉमिस्ट जल्द आपसे संपर्क करेंगे, और तब तक आप लिखकर मदद ले सकते हैं।",
                "updated_profile": {
                    "problem_summary": "fungal_disease"
                }
            }, ensure_ascii=False)
        ]
        
        with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
            msg = ParsedMessage(
                wamid="wamid.test_vision_low",
                from_phone=phone,
                type="image",
                media_id="media_test_vision_0.4",
                timestamp="1718563800"
            )
            await conversation_router.route_message(msg)
            
            # Verify session escalated_to_human is true and lead status updated
            lead = await leads_repo.get_farmer(phone)
            assert lead is not None
            assert lead.escalated_to_human is True
            assert lead.lead_status == "escalated"

@pytest.mark.asyncio
async def test_conversational_json_parsing_and_reprompt():
    """
    Test Scenario 7: Malformed JSON output is re-prompted once, and falls back to plain Hindi.
    """
    phone = "919000000016"
    
    # 1. First response: Malformed JSON (missing braces/quotes)
    # 2. Second response: Corrected JSON reply
    mock_responses = [
        "This is not JSON: {action: reply, message: नमस्ते}",
        json.dumps({
            "action": "reply",
            "message": "नमस्ते! मैं आपकी किस प्रकार मदद कर सकता हूँ?"
        }, ensure_ascii=False)
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
        
        # Should be called twice (first time fails, second time succeeds after re-prompt)
        assert mock_complete.call_count == 2
        assert len(mock_whatsapp_client.sent_messages) > 0
        assert "नमस्ते!" in mock_whatsapp_client.sent_messages[-1]["body"]

@pytest.mark.asyncio
async def test_conversational_maize_recommendation_and_translation():
    """
    Test Scenario 8: Verify that Hinglish/Hindi crop name "Makka"/"मक्का" resolves to "Maize",
    returns the approved maize products, correctly handles null mrp_inr, and recommends VIGOUR 60A90.
    """
    phone = "919000000017"
    
    # 1. Seed crops table with Maize / Corn
    in_memory_db.tables["crops"].append({
        "crop_id": "CR02",
        "crop_name_hi": "मक्का",
        "crop_name_en": "Maize / Corn",
        "in_catalog": "Y"
    })
    
    # 2. Seed 7 maize products (5 approved, 2 unapproved)
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
        },
        {
            "product_id": "MZE002",
            "variety_name": "VIGOUR 30A90",
            "crop": "Maize",
            "approved_for_recommendation": "Y",
            "mrp_inr": None,
            "pest_disease_tolerance": "Standard",
            "target_problem_fit": "early maturity",
            "pack_size": "4 kg",
            "duration_days": "115-120",
            "key_traits": "stay green"
        },
        {
            "product_id": "MZE003",
            "variety_name": "VIGOUR 555",
            "crop": "Maize",
            "approved_for_recommendation": "Y",
            "mrp_inr": None,
            "pest_disease_tolerance": "Tolerant to leaf blight",
            "target_problem_fit": "long-duration rabi",
            "pack_size": "4 kg",
            "duration_days": "145-150",
            "key_traits": "stay green"
        },
        {
            "product_id": "MZE004",
            "variety_name": "VIGOUR 007",
            "crop": "Maize",
            "approved_for_recommendation": "Y",
            "mrp_inr": None,
            "pest_disease_tolerance": "Standard",
            "target_problem_fit": "lodging-prone",
            "pack_size": "4 kg",
            "duration_days": "115-120",
            "key_traits": "lodging resistant"
        },
        {
            "product_id": "MZE005",
            "variety_name": "VIGOUR AAMUKTHA",
            "crop": "Maize",
            "approved_for_recommendation": "Y",
            "mrp_inr": None,
            "pest_disease_tolerance": "Standard",
            "target_problem_fit": "lodging-prone",
            "pack_size": "4 kg",
            "duration_days": "115-120",
            "key_traits": "lodging resistant"
        },
        {
            "product_id": "MZE006",
            "variety_name": "VIGOUR 50x50",
            "crop": "Maize",
            "approved_for_recommendation": "N",
            "mrp_inr": None,
            "pest_disease_tolerance": "TBD",
            "target_problem_fit": "TBD",
            "pack_size": "4 kg",
            "duration_days": "TBD",
            "key_traits": "TBD"
        },
        {
            "product_id": "MZE007",
            "variety_name": "VIGOUR WHITE COBRA",
            "crop": "Maize",
            "approved_for_recommendation": "N",
            "mrp_inr": None,
            "pest_disease_tolerance": "TBD",
            "target_problem_fit": "white corn",
            "pack_size": "4 kg",
            "duration_days": "TBD",
            "key_traits": "white grain"
        }
    ]
    for p in maize_products:
        in_memory_db.tables["products"].append(p)

    # Seed Paddy & Hot Pepper (Chilli) products
    in_memory_db.tables["products"].append({
        "product_id": "PDY001",
        "variety_name": "VIGOUR 087",
        "crop": "Paddy",
        "approved_for_recommendation": "Y",
        "mrp_inr": 120.0,
        "pack_size": "20 kg",
        "duration_days": "120-125"
    })
    in_memory_db.tables["products"].append({
        "product_id": "HPP001",
        "variety_name": "VIGOUR TEJASWI",
        "crop": "Hot Pepper (Chilli)",
        "approved_for_recommendation": "Y",
        "mrp_inr": 500.0,
        "pack_size": "100 g",
        "duration_days": "180"
    })

    # 3. Seed recommendation rules
    in_memory_db.tables["recommendation_rules"].append({
        "rule_id": "R031",
        "crop": "Maize",
        "crop_stage": "sowing",
        "problem_category": "drought_prone",
        "irrigation_type": "Rainfed/Irrigated",
        "region": "MP",
        "recommended_product_ids": "MZE001",
        "next_action": "send_recommendation",
        "human_review_required": False
    })
    
    # Setup session profile
    await sessions_repo.upsert(phone, {
        "current_step": "start",
        "collected_json": {
            "name": "रामसिंह",
            "district": "Ujjain",
            "state": "Madhya Pradesh"
        }
    })
    
    # 4. Verify tool find_products crop normalization directly
    from app.ai.agent import tool_find_products
    # Direct check with "Makka"
    res_makka = await tool_find_products("Makka", "stem_borer", phone)
    variety_names_makka = [p["variety_name"] for p in res_makka]
    assert "VIGOUR 60A90" in variety_names_makka
    assert "VIGOUR 50x50" not in variety_names_makka # Not approved should be filtered
    
    # Direct check with "मक्का"
    res_hindi = await tool_find_products("मक्का", "stem_borer", phone)
    variety_names_hindi = [p["variety_name"] for p in res_hindi]
    assert "VIGOUR 60A90" in variety_names_hindi

    # Direct check with "dhan" -> "Paddy"
    res_dhan = await tool_find_products("dhan", "sowing", phone)
    assert len(res_dhan) > 0
    assert all(p["crop"] == "Paddy" for p in res_dhan)

    # Direct check with "mirchi" -> "Hot Pepper (Chilli)"
    res_mirchi = await tool_find_products("mirchi", "sowing", phone)
    assert len(res_mirchi) > 0
    assert all(p["crop"] == "Hot Pepper (Chilli)" for p in res_mirchi)

    # 5. Mock responses for full turn simulation
    mock_responses = [
        json.dumps({
            "action": "find_products",
            "args": {"crop": "Makka", "problem": "stem_borer"}
        }, ensure_ascii=False),
        json.dumps({
            "action": "reply",
            "message": "मक्का (Maize) के लिए सबसे बढ़िया बीज VIGOUR 60A90 है। यह तना छेदक (stem borer) के प्रति अत्यधिक सहनशील है और बेहतर दाने भरने में मदद करता है। दाम के लिए नज़दीकी डीलर से पूछें।",
            "updated_profile": {
                "crop": "Maize",
                "crop_stage": "sowing",
                "last_recommended_ids": ["MZE001"]
            }
        }, ensure_ascii=False)
    ]
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        msg = ParsedMessage(
            wamid="wamid.test_maize",
            from_phone=phone,
            type="text",
            text="मक्का / Makka बोना है, दाने छोटे होने और कीड़े की समस्या से बचाव के लिए बीज बताओ",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "VIGOUR 60A90" in last_msg
        assert "दाम के लिए नज़दीकी डीलर से पूछें" in last_msg
        assert "तना छेदक" in last_msg or "stem borer" in last_msg

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

    # Also test Devanagari bare city
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
        "current_step": "start",
        "collected_json": {
            "name": "रामजी",
            "state": "Madhya Pradesh",
            "district": "Ujjain",
            "crop": "Maize"
        }
    })
    
    # Mock LLM to return a normal follow-up asking for the problem, not a welcome greeting
    mock_responses = [
        json.dumps({
            "action": "reply",
            "message": "हाँ रामजी भाई, मक्का की फसल में क्या समस्या आ रही है? पत्तियां पीली हो रही हैं या कीड़े लगे हैं?"
        }, ensure_ascii=False)
    ]
    
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)) as mock_complete:
        msg = ParsedMessage(
            wamid="wamid.test_short_reply",
            from_phone=phone,
            type="text",
            text="batao",
            timestamp="1718563800"
        )
        await conversation_router.route_message(msg)
        
        # Verify greeting/intro was NOT generated in the response
        assert len(mock_whatsapp_client.sent_messages) > 0
        last_msg = mock_whatsapp_client.sent_messages[-1]["body"]
        assert "Vigour मित्र" not in last_msg
        assert "स्वागत" not in last_msg
        
        # Ensure system prompt had context memory instructions
        system_arg = mock_complete.call_args[1]["system"]
        assert "Vigour मित्र" in system_arg
        assert "batao" in mock_complete.call_args[1]["user"]
