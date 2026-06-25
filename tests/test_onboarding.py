import pytest
from unittest.mock import AsyncMock, patch
from conftest import in_memory_db, mock_whatsapp_client, mock_ai_provider
from app.whatsapp.models import ParsedMessage
from app.flows.router import conversation_router
from app.db.repositories.sessions import sessions_repo
from tests.test_conversations import make_mock_complete_sequence

@pytest.mark.asyncio
async def test_full_onboarding_sequence():
    phone = "919000003002"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()

    # 1. Hello -> returns name prompt
    await conversation_router.route_message(ParsedMessage(wamid="w1", from_phone=phone, type="text", text="Hello", timestamp="1718563800"))
    assert "आपका नाम क्या है" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    # Verify session has last_onboarding_field = "name"
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("last_onboarding_field") == "name"
    assert not session.collected_json.get("name")

    # 2. Farmer replies "Mera naam Harsh hai" -> saves name, asks state/district
    await conversation_router.route_message(ParsedMessage(wamid="w2", from_phone=phone, type="text", text="Mera naam Harsh hai", timestamp="1718563800"))
    assert "आप किस राज्य और ज़िले से हैं" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    # Verify name saved
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("name") == "Harsh"
    assert session.collected_json.get("last_onboarding_field") == "state"

    # 3. Farmer replies "MP Indore" -> saves state/district, asks total land
    await conversation_router.route_message(ParsedMessage(wamid="w3", from_phone=phone, type="text", text="MP Indore", timestamp="1718563800"))
    assert "कुल कितनी ज़मीन" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    # Verify state/district saved
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("state") == "Madhya Pradesh"
    assert session.collected_json.get("district") == "Indore"
    assert session.collected_json.get("last_onboarding_field") == "total_land"

    # 4. Farmer replies "10 acre" -> saves total land, asks water source
    await conversation_router.route_message(ParsedMessage(wamid="w4", from_phone=phone, type="text", text="10 acre", timestamp="1718563800"))
    assert "सिंचाई का साधन" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    # Verify land saved
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("total_land") == 10.0
    assert session.collected_json.get("last_onboarding_field") == "water_source"

    # 5. Farmer replies "tubewell" -> saves water source, onboarding complete -> falls through to LLM
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "धन्यवाद हर्ष भाई, आपकी पूरी जानकारी सुरक्षित हो गई है। अब बताइए मैं आपकी क्या मदद करूँ?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(wamid="w5", from_phone=phone, type="text", text="tubewell", timestamp="1718563800"))
        assert "मदद करूँ" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    # Verify water source saved
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("water_source") == "tubewell"


@pytest.mark.asyncio
async def test_problem_request_priority_bypass():
    phone = "919000003003"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()

    # 1. Hello -> returns name prompt
    await conversation_router.route_message(ParsedMessage(wamid="w1", from_phone=phone, type="text", text="Hello", timestamp="1718563800"))
    assert "आपका नाम क्या है" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 2. Harsh -> saves name, asks state/district
    await conversation_router.route_message(ParsedMessage(wamid="w2", from_phone=phone, type="text", text="Harsh", timestamp="1718563800"))
    assert "आप किस राज्य और ज़िले से हैं" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 3. Farmer raises a problem: "makke me keede lag gaye hain"
    # This contains crop (makka / Maize) and problem (keede / insects), which is a farming request.
    # Therefore, onboarding should be bypassed and the LLM should be invoked.
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "मक्के की फसल में कीड़े के नियंत्रण के लिए आप..."}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(wamid="w3", from_phone=phone, type="text", text="makke me keede lag gaye hain", timestamp="1718563800"))
        assert "मक्के की फसल" in mock_whatsapp_client.sent_messages[-1]["body"]

    # Verify session has state/district as missing (since onboarding gate was bypassed)
    session = await sessions_repo.get(phone)
    assert not session.collected_json.get("state")
    assert not session.collected_json.get("total_land")


@pytest.mark.asyncio
async def test_dont_know_scenarios():
    phone = "919000003004"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()

    # 1. Hello -> returns name prompt
    await conversation_router.route_message(ParsedMessage(wamid="w1", from_phone=phone, type="text", text="Hello", timestamp="1718563800"))
    assert "आपका नाम क्या है" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 2. "pata nahi" -> name is saved as "किसान भाई", asks state/district
    await conversation_router.route_message(ParsedMessage(wamid="w2", from_phone=phone, type="text", text="pata nahi", timestamp="1718563800"))
    assert "किसान भाई किसान, आप किस राज्य और ज़िले से हैं?" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("name") == "किसान भाई"

    # 3. "nhi pata" -> state/district saved as "Not Known", asks total land
    await conversation_router.route_message(ParsedMessage(wamid="w3", from_phone=phone, type="text", text="nhi pata", timestamp="1718563800"))
    assert "कुल कितनी ज़मीन" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("state") == "Not Known"
    assert session.collected_json.get("district") == "Not Known"

    # 4. "don't know" -> total_land saved as "Not Known", asks water source
    await conversation_router.route_message(ParsedMessage(wamid="w4", from_phone=phone, type="text", text="don't know", timestamp="1718563800"))
    assert "सिंचाई का साधन" in mock_whatsapp_client.sent_messages[-1]["body"]

    session = await sessions_repo.get(phone)
    assert session.collected_json.get("total_land") == "Not Known"

    # 5. "no idea" -> water_source saved as "Not Known", onboarding complete -> falls through to LLM
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "ठीक है भाई, कोई बात नहीं। अब बताइए मैं आपकी क्या मदद करूँ?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(wamid="w5", from_phone=phone, type="text", text="no idea", timestamp="1718563800"))
        assert "मदद करूँ" in mock_whatsapp_client.sent_messages[-1]["body"]

    session = await sessions_repo.get(phone)
    assert session.collected_json.get("water_source") == "Not Known"


@pytest.mark.asyncio
async def test_reask_prevention():
    phone = "919000003005"
    await sessions_repo.delete(phone)
    mock_whatsapp_client.clear()
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()

    # Pre-populate session with state and water_source, but name and land are missing
    from app.services.session import session_service
    session = await session_service.get_or_create(phone)
    collected = {
        "state": "Madhya Pradesh",
        "district": "Bhopal",
        "water_source": "well"
    }
    await sessions_repo.upsert(phone, {"collected_json": collected})

    # 1. Hello -> first missing field is name, so asks name
    await conversation_router.route_message(ParsedMessage(wamid="w1", from_phone=phone, type="text", text="Hello", timestamp="1718563800"))
    assert "आपका नाम क्या है" in mock_whatsapp_client.sent_messages[-1]["body"]

    # 2. Harsh -> saves name. Next missing field is total_land (state/district are already filled, water_source is filled)
    # So it should skip state/district and ask for total_land directly!
    await conversation_router.route_message(ParsedMessage(wamid="w2", from_phone=phone, type="text", text="Harsh", timestamp="1718563800"))
    assert "कुल कितनी ज़मीन" in mock_whatsapp_client.sent_messages[-1]["body"]
    
    session = await sessions_repo.get(phone)
    assert session.collected_json.get("name") == "Harsh"

    # 3. 5 acre -> saves land. Since water_source is already filled, all onboarding fields are complete!
    # So it should bypass asking water_source and fall through to LLM.
    mock_responses = make_mock_complete_sequence([
        {"action": "reply", "message": "धन्यवाद हर्ष भाई, आप सोयाबीन के बारे में क्या जानना चाहते हैं?"}
    ])
    with patch.object(mock_ai_provider, "complete", AsyncMock(side_effect=mock_responses)):
        await conversation_router.route_message(ParsedMessage(wamid="w3", from_phone=phone, type="text", text="5 acre", timestamp="1718563800"))
        assert "सोयाबीन" in mock_whatsapp_client.sent_messages[-1]["body"]

    session = await sessions_repo.get(phone)
    assert session.collected_json.get("total_land") == 5.0
