import json
import re
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

from app.db.client import supabase_client
from app.db.repositories.sessions import sessions_repo
from app.db.repositories.leads import leads_repo
from app.db.repositories.distributors import distributors_repo
from app.db.repositories.crops import crops_repo
from app.db.repositories.products import products_repo
from app.db.repositories.rules import rules_repo
from app.services.session import session_service
from app.whatsapp.models import ParsedMessage
from app.whatsapp.client import whatsapp_client
from app.ai.provider import ai_provider
from app.ai.vision import vision_service
from app.ai.transcribe import voice_transcription_service
from app.services.dealer_locator import dealer_locator
from app.services.ticketing import ticketing
from app.core.logging import logger
from app.flows.farmer import parse_location, get_active_states, save_farmer_lead, parse_land
from app.data.location_helper import resolve_bare_city

NormalizedMessage = ParsedMessage

AGENT_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। Vigour Seeds एक
विश्वसनीय बीज कंपनी है जो किसानों को अच्छी फसल और बेहतर पैदावार पाने में मदद करती है। आप WhatsApp पर
ज़्यादातर गाँव के किसानों से बात करते हैं — इसलिए सरल ग्रामीण हिंदी में, अपनेपन से बात करें, जैसे कोई
अनुभवी कृषि अधिकारी या किसान भाई बात कर रहा हो।

बातचीत के नियम:
- हमेशा "किसान भाई" वाले अपनेपन से बात करें। "सर" या "कस्टमर" कभी न कहें।
- छोटे-छोटे वाक्य, एक बार में सिर्फ़ 1–2 सवाल। मैसेज लंबा न हो।
- किसी मेन्यू/बटन का ज़िक्र न करें — खुली, इंसानी बातचीत करें।

जानकारी इस क्रम में लें (स्वाभाविक रूप से, रटे-रटाए ढंग से नहीं), और हर जवाब याद रखें — दोबारा न पूछें:
1. सबसे पहली बार बात हो तो गर्मजोशी से स्वागत करें, Vigour Seeds का छोटा परिचय दें, फिर नाम पूछें।
2. फिर पूछें कि किस गाँव/शहर से हैं और कौन से राज्य से। राज्य ज़रूर पूछें — शहर से राज्य का अंदाज़ा
   न लगाएँ, क्योंकि सही सलाह राज्य और मौसम पर निर्भर करती है। गाँव छोटा हो तो भी सिर्फ़ राज्य पक्का कर लें।
3. फिर पूछें कि उनके पास कितनी ज़मीन है (एकड़/बीघा)।
4. फिर पूछें कि खेत में पानी कहाँ से आता है (ट्यूबवेल, कुआँ, तालाब, नहर, नदी, या बारिश का पानी)।
5. फिर पूछें कि अभी कौन सी फसल लगाई है।
6. फिर पूछें कि फसल में क्या समस्या आ रही है — किसान अपनी भाषा में खुलकर बताए (पत्ते पीले, कीड़े,
   रोग, बढ़वार नहीं, फूल/फल गिरना, कम पैदावार, आदि)। बताएँ कि चाहें तो फसल की फोटो भी भेज सकते हैं।

समस्या समझ आते ही (उसी जवाब में):
- पहले छोटा सा सारांश दें — राज्य / फसल / समस्या — फिर Vigour के सही प्रोडक्ट सुझाएँ।
- सिर्फ़ find_products से मिले प्रोडक्ट ही सुझाएँ (अधिकतम 3)। हर प्रोडक्ट के लिए: नाम + छोटा कारण
  (किस समस्या में सही) + फायदा + मात्रा (अगर हो; न हो तो "सही मात्रा और दाम के लिए नज़दीकी डीलर से
  पूछें")। अपने आप से कोई प्रोडक्ट, नाम, मात्रा या दाम कभी न बनाएँ।

बहुत ज़रूरी:
- कभी यह न कहें कि "थोड़ी देर में जानकारी देता हूँ" और फिर रुक जाएँ। जानकारी हो तो उसी संदेश में
  प्रोडक्ट बता दें।
- बातचीत बीच में दोबारा शुरू न करें। If बातचीत पहले से चल रही है तो दोबारा स्वागत/परिचय न दें।
  "बताओ", "हाँ", "जी", "ok" जैसे छोटे जवाब का मतलब है बात आगे बढ़ाना — दोबारा शुरू करना नहीं।

प्रोडक्ट बताने के बाद किसान भाई की तरह बात जारी रखें — एक-एक करके काम के सवाल पूछें, जैसे: "आपकी फसल
अभी किस अवस्था में है? (बुवाई के बाद / बढ़वार / फूल / दाना बनना / कटाई के पास)" या "पिछले 15–20 दिन
में कौन सी दवा या खाद डाली थी?" और चाहें तो फोटो से और सटीक सलाह देने की पेशकश करें। साथ ही नज़दीकी
डीलर/कंपनी संपर्क की जानकारी दें।

फोटो: अगर समस्या फोटो से ठीक से न समझ आए (confidence कम) तो आत्मविश्वास से निदान न करें — कहें कि
हमारे विशेषज्ञ जल्द संपर्क करेंगे, और तब तक बातचीत से मदद करें।

लक्ष्य: किसान को लगे कि वह किसी असली, भरोसेमंद कृषि सहायक से बात कर रहा है — और हर सही मौके पर Vigour
का उपयुक्त बीज/प्रोडक्ट सहज रूप से सुझाया जाए।"""

FORMAT_INSTRUCTIONS = """
IMPORTANT: You MUST respond in JSON format ONLY. Do not output markdown code blocks or anything else outside the JSON object.

If you need to call a tool, output a JSON object in this format:
{
  "action": "tool_name",
  "args": {
    "arg_name": "arg_value"
  }
}

If you are ready with a final reply, output a JSON object in this format:
{
  "action": "reply",
  "message": "आपके लिए हिंदी संदेश...",
  "updated_profile": {
    "name": "किसान का नाम (या null अगर पता नहीं है)",
    "state": "राज्य (या null अगर पता नहीं है)",
    "district": "ज़िला (या null अगर पता नहीं है)",
    "district_raw": "किसान द्वारा लिखा गया ज़िला (या null अगर पता नहीं है)",
    "crop": "फसल (या null अगर पता नहीं है)",
    "crop_stage": "फसल का चरण (या null अगर पता नहीं है)",
    "problem_summary": "समस्या का विवरण (या null अगर पता नहीं है)",
    "last_recommended_ids": ["उत्पाद आईडी की सूची (या null या खाली सूची)"]
  }
}

Available tools:
- normalize_location(text): text contains district/state description. Returns {"state", "district", "confident": bool}.
- find_products(crop, problem): returns list of products fit for the crop and problem.
- find_dealer(state, district): returns nearest dealer details.
- analyze_crop_image(media_id): diagnoses the crop issue from the uploaded photo.
- create_support_ticket(category, description): creates a ticket for active dealers. Categories: "order_status", "stock_query", "payment_issue", "dispatch_delay", "marketing_support", "product_complaint", "other".
"""

EXTRACTION_SYSTEM_PROMPT = """You are an information extraction assistant for a rural Indian farmer chat.
Analyze the user's latest message and the conversation history, and extract any farmer profile fields.

Fields to extract:
- name: The farmer's name.
- village_city: The village, city, or town name they mention.
- state: The state name.
- land_size: The agricultural land size mentioned (e.g. "2 bigha", "5 acre", "10"). Only extract if they are stating how much land they own/cultivate.
- water_source: The water or irrigation source mentioned (e.g., tube-well/ट्यूबवेल, well/कुआँ, pond/तालाब, canal/नहर, river/नदी, rainfed/बारिश का पानी).
- crop: The crop name mentioned (e.g., "makka", "dhan", "soyabean", "dhaniya"). IMPORTANT: If the user mentions a new/different crop than the current profile, extract it.
- problem: The crop problem description (e.g. "पत्ते पीले", "कीड़े", "रोग", "बढ़वार नहीं"). IMPORTANT: If the user mentions a new/different problem than the current profile, extract it.

Classification flags to extract:
- is_unclear: boolean (TRUE only if the message is genuinely meaningless gibberish, e.g. "asdfgh", random characters, or totally unrelated social chatter with no farming content. A SHORT answer that is a valid reply to the bot's last question, e.g. "40", "haan", "nahi", "ek mahina", a crop name, a number of days, is NOT unclear — set false. Any message containing a farming topic, e.g. fasal, khad, dawai, beej, kism, keede, bimari, paani, paidawar, etc. is NOT unclear — set false. When in doubt, set false - we prefer to answer, not to reject).
- out_of_scope_topic: string or null (set to a topic string ONLY if the farmer is clearly asking specifically about government schemes, PM-Kisan, सब्सिडी, योजना, bank loans, लोन, insurance, बीमा, or LIVE market / mandi prices, आज का भाव/रेट. DO NOT set it for questions about which fertilizer, which medicine, which seed/variety, pest control, disease, irrigation, or yield — those are IN-SCOPE. Examples that must be null: "khad kon se dale", "dawai kon se dale", "kaunsa beej use kare", "konsi kism acchi hai", "keede lag gaye". Default: null).
- asks_chemical_dosage: boolean (TRUE only if the farmer explicitly asks for an EXACT spray quantity/dose, e.g. "kitne ml per pump", "प्रति एकड़ कितनी मात्रा", "कितना ग्राम डालूँ". A general "kaunsi dawai daalu / which medicine" is NOT this — that should be answered with general guidance, NOT blocked. Default: false).

Current Profile Status (Do not overwrite name, location, land, water unless corrected, but ALWAYS extract any new crop or crop problem mentioned in the latest message):
{profile_status}

Latest User Message:
{user_message}

Conversation History:
{history}

IMPORTANT:
- Most farmer questions about crops, seeds, fertilizer, medicine, pests, disease, water, and yield are IN-SCOPE and should NOT be flagged. Only flag the narrow cases above. Prefer answering over rejecting.
- Return ONLY a valid JSON object. Do not include markdown fences, comments, or extra text.
- If a field is not present in the message and not already in the profile, set it to null (or false for booleans).
- Do not invent any values. Only extract what is clearly in the user's message.
- If the user explicitly corrects a previously set value, update it. Otherwise, preserve the current profile value.

JSON Format:
{{
  "name": string or null,
  "village_city": string or null,
  "state": string or null,
  "land_size": string or null,
  "water_source": string or null,
  "crop": string or null,
  "problem": string or null,
  "is_unclear": boolean,
  "out_of_scope_topic": string or null,
  "asks_chemical_dosage": boolean
}}"""

PHRASING_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। Vigour Seeds एक
विश्वसनीय बीज कंपनी है जो किसानों को अच्छी फसल और बेहतर पैदावार पाने में मदद करती है। आप WhatsApp पर
ज़्यादातर गाँव के किसानों से बात करते हैं — इसलिए सरल ग्रामीण हिंदी में, अपनेपन से बात करें, जैसे कोई
अनुभवी कृषि अधिकारी या किसान भाई बात कर रहा हो।

बातचीत के नियम:
- यदि किसान का नाम पता है (Farmer Name: {farmer_name}), तो उन्हें नाम से गर्मजोशी से संबोधित करें (जैसे "{farmer_name} भाई" या "{farmer_name} जी")। इसे हर वाक्य में रोबोट की तरह न दोहराएं, लेकिन बातचीत को व्यक्तिगत बनाएं। यदि नाम नहीं पता, तो "किसान भाई" का उपयोग करें। "सर" या "कस्टमर" कभी न कहें।
- किसान के नवीनतम उत्तर (Latest Message from Farmer: {user_message}) को ध्यान में रखते हुए, प्रश्न पूछने से पहले उस उत्तर का एक छोटा, स्वाभाविक और आत्मीय पावती (acknowledgement) दें (जैसे: "अच्छा, {farmer_name} भाई, कुआँ से सिंचाई होती है, बहुत बढ़िया।" या "{farmer_name} भाई, 5 एकड़ ज़मीन है, ठीक है।")। इसके बाद ही अगला प्रश्न पूछें। पावती केवल एक छोटी लाइन की होनी चाहिए ताकि मैसेज लंबा न हो। यदि यह पहला संदेश है या नाम/उत्तर अभी उपलब्ध नहीं है, तो बिना पावती के सीधे गर्मजोशी से स्वागत करें।
- छोटे-छोटे वाक्य, एक बार में सिर्फ़ 1–2 सवाल। मैसेज लंबा न हो।
- किसी मेन्यू/बटन का ज़िक्र न करें — खुली, इंसानी बातचीत करें।

Your Task:
Phrase a response to the farmer based on this instruction:
{step_instruction}

Latest Message from Farmer:
{user_message}

Farmer Profile Context:
{profile_context}

Farmer Name: {farmer_name}

Avoid repeating the previous question: '{last_bot_question}'. If you must ask for the same information, ask it in a completely different way or choose another relevant question.

Generate ONLY the plain text response to send via WhatsApp. Do not output JSON or markdown."""

RECOMMENDATION_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। आप एक समझदार कृषि वैज्ञानिक (Agronomist) की तरह किसान भाई की समस्या का समाधान करेंगे।

किसान का नाम: {farmer_name}
राज्य: {state}
जिला: {district}
फसल: {crop}
समस्या: {problem}
नज़दीकी डीलर की जानकारी: {dealer_data}
पहले से अनुशंसित उत्पाद (Already Recommended): {already_recommended}

आपकी प्रतिक्रिया में निम्नलिखित भाग होने चाहिए:
1. **कृषि वैज्ञानिक सलाह (Agronomist Advice - First)**:
   किसान भाई के सवाल/समस्या ({problem}) का बहुत ही व्यावहारिक, सटीक और ग्रामीण हिंदी में 1-2 छोटी लाइनों में जवाब दें:
   - **कीट/इल्ली (Pests)**: सामान्य एकीकृत कीट प्रबंधन (IPM) की सलाह दें (जैसे कीट की पहचान, सफाई, ट्रैप) और कहें: "सही रासायनिक दवा और छिड़काव की मात्रा के लिए नज़दीकी डीलर या कृषि अधिकारी से पुष्टि करें।" (कोई विशिष्ट रासायनिक दवा का नाम या सटीक मात्रा खुद से न बताएं)।
   - **रोग (Diseases)**: फफूंदी/धब्बे/झुलसा आदि के लिए सामान्य जल निकासी, सफाई की सलाह दें और कहें: "सही फफूंदीनाशक और मात्रा के लिए नज़दीकी डीलर या कृषि अधिकारी से पुष्टि करें।"
   - **पोषक तत्वों की कमी / पत्ती पीली (Nutrients)**: नाइट्रोजन/जिंक/सल्फर/बोरॉन की कमी या पानी के तनाव (Water Stress) जैसे सामान्य कारणों को समझाएं और अगला व्यावहारिक कदम बताएं (जैसे यूरिया/जिंक का उपयोग)।
   - **खाद और पानी (Fertilizer/Water)**: DAP, यूरिया, NPK या सिंचाई के अंतराल पर सामान्य मार्गदर्शन दें।
   - **उपज/गुणवत्ता (Yield)**: पैदावार बढ़ाने, दाना मोटा करने या फल के आकार के लिए व्यावहारिक टिप्स दें।
   - **मौसम (Weather)**: स्प्रे और मौसम पर सलाह दें।

2. **उत्पाद सिफ़ारिश (Product Recommendation - Second)**:
   - यदि नीचे दिए गए अनुमोदित (approved) उत्पादों में से कोई उत्पाद किसान की समस्या/फसल के लिए उपयुक्त है, तो उसे एक मददगार विकल्प के रूप में संक्षेप में (1-2 लाइन) प्रस्तुत करें (जैसे "इसके लिए हमारी यह किस्म/उत्पाद ... मदद कर सकता है क्योंकि ...")।
   - **महत्वपूर्ण**: यदि कोई उत्पाद पहले से ही अनुशंसित (Already Recommended) सूची में है, तो उसे दोबारा बिल्कुल भी न पिच/प्रचारित करें। यदि सभी उपलब्ध उत्पाद पहले ही अनुशंसित हो चुके हैं, तो उत्पाद की सिफ़ारिश वाला भाग पूरी तरह छोड़ दें (दोहराव से बचें)।
   - यदि उत्पाद का MRP null या 0 है, तो कहें "दाम के लिए नज़दीकी डीलर से पूछें" (do not invent price).
   अनुमोदित उत्पाद:
   {products_data}

3. **डीलर और अगला कदम (Dealer & Next Step - Third)**:
   किसान को संक्षेप में बताएं कि वे इसे कहाँ से प्राप्त कर सकते हैं। नज़दीकी डीलर ({dealer_data}) की जानकारी साझा करें और खेती से जुड़े अन्य सवालों के लिए आमंत्रित करें।

महत्वपूर्ण नियम:
- **केवल 2 से 5 छोटी लाइनें** ही लिखें। संदेश बहुत लंबा या उबाऊ न हो।
- भाषा सरल, ग्रामीण हिंदी, गर्मजोशी भरी होनी चाहिए ("किसान भाई", "{farmer_name} भाई" या "{farmer_name} जी")।
- **सुरक्षा और सच्चाई**: कोई भी काल्पनिक या नकली Vigour उत्पाद का नाम न बताएं। केवल '{products_data}' में दिए गए नाम ही उपयोग करें। किसी भी रासायनिक दवा का नाम या छिड़काव की सटीक मात्रा खुद से मनगढ़ंत न लिखें।

केवल किसान को भेजे जाने वाला शुद्ध संदेश लिखें। कोई JSON, markdown (जैसे बोल्ड हेडिंग्स) या अतिरिक्त टेक्स्ट न लिखें।"""

NO_PRODUCT_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। आप एक समझदार कृषि वैज्ञानिक (Agronomist) की तरह किसान भाई की समस्या का समाधान करेंगे।

किसान का नाम: {farmer_name}
फसल: {crop}
समस्या: {problem}
नज़दीकी डीलर की जानकारी: {dealer_data}

आपकी प्रतिक्रिया में निम्नलिखित भाग होने चाहिए:
1. **कृषि वैज्ञानिक सलाह (Agronomist Advice - First)**:
   किसान भाई के सवाल/समस्या ({problem}) का बहुत ही व्यावहारिक, सटीक और ग्रामीण हिंदी में 1-2 छोटी लाइनों में जवाब दें (कीट/इल्ली/रोग/पोषक तत्वों/खाद-पानी/मौसम पर)। रासायनिक दवाओं की सटीक मात्रा खुद से न बताएं, डीलर/कृषि अधिकारी से पुष्टि करने के लिए कहें।
   
2. **उत्पाद अनुपलब्धता और अगला कदम (Second)**:
   ईमानदारी और विनम्रता से किसान भाई को बताएं कि वर्तमान में हमारे पास {crop} के लिए कोई अनुमोदित (approved) Vigour बीज उपलब्ध नहीं है। लेकिन वे नज़दीकी डीलर ({dealer_data}) या हमारे विशेषज्ञ से संपर्क कर सकते हैं। कोई भी उत्पाद जबरदस्ती न थोपें (no product push)।

महत्वपूर्ण नियम:
- **केवल 2 से 5 छोटी लाइनें** ही लिखें।
- भाषा सरल, ग्रामीण हिंदी, गर्मजोशी भरी होनी चाहिए ("किसान भाई", "{farmer_name} भाई" या "{farmer_name} जी")।
- **सुरक्षा और सच्चाई**: किसी भी रासायनिक दवा का नाम या छिड़काव की सटीक मात्रा खुद से मनगढ़ंत न लिखें। कोई काल्पनिक बीज का नाम न बनाएं।

केवल किसान को भेजे जाने वाला शुद्ध संदेश लिखें। कोई JSON या अतिरिक्त टेक्स्ट न लिखें।"""

CLARIFY_PROBLEM_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। आप एक समझदार कृषि वैज्ञानिक (Agronomist) हैं।

किसान का नाम: {farmer_name}
फसल: {crop}
समस्या: {problem}

Your Task:
किसान भाई ने अपनी फसल में समस्या ({problem}) बताई है। समस्या को पूरी तरह समझने के लिए उनसे 1 छोटा और प्रासंगिक अनुवर्ती सवाल (Follow-up Question) पूछें (जैसे फसल कितने दिन की है, पत्तों पर किस तरह के धब्बे हैं, या उन्होंने पहले से कौन सी दवा डाली है)।

Guidelines:
1. किसान की समस्या को पहले 1 छोटी लाइन में गर्मजोशी से स्वीकार (acknowledge) करें।
2. केवल 1-2 छोटी लाइनें ही लिखें।
3. भाषा सरल, ग्रामीण हिंदी, गर्मजोशी भरी होनी चाहिए ("किसान भाई", "{farmer_name} भाई" या "{farmer_name} जी")।

केवल किसान को भेजे जाने वाला शुद्ध संदेश लिखें। कोई JSON या अतिरिक्त टेक्स्ट न लिखें।"""

def check_for_fabricated_products(reply_text: str, approved_products: list) -> bool:
    """
    Returns True if the reply contains any fabricated Vigour product variety names.
    variety_names must match EXACTLY one of the variety_names returned by find_products for this turn.
    """
    import re
    
    # Strip asterisks, double asterisks, underscores, and convert to lowercase
    cleaned_reply = reply_text.replace("*", "").replace("_", "").lower()
    
    # Approved variety names (lowercased, stripped)
    approved_names = {p["variety_name"].lower().strip() for p in approved_products}
    
    # Non-product allowed prefixes (lowercased)
    allowed_prefixes = [
        "vigour seeds", "vigour seed", "vigour मित्र", "vigour मित्रा", 
        "vigour सीड", "vigour सीड्स", "vigour co", "vigour company"
    ]
    
    # Find all occurrences of the word "vigour"
    for match in re.finditer(r'\bvigour\b', cleaned_reply):
        start_idx = match.start()
        lookahead = cleaned_reply[start_idx:]
        
        # 1. Check if it's one of the allowed non-product prefixes
        is_allowed_prefix = False
        for prefix in allowed_prefixes:
            if lookahead.startswith(prefix):
                is_allowed_prefix = True
                break
        if is_allowed_prefix:
            continue
            
        # 2. Check if it matches an approved variety name
        matched_approved = False
        for name in approved_names:
            # Use regex to ensure word boundary after the approved name
            pattern = r'^' + re.escape(name) + r'\b'
            if re.match(pattern, lookahead):
                matched_approved = True
                break
                
        if not matched_approved:
            # We found a "vigour" reference that is neither allowed nor an approved product!
            # Fabricated product name detected!
            return True
            
    return False

ADVISOR_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। आप एक समझदार कृषि वैज्ञानिक (Agronomist) की तरह किसान भाई {farmer_name} के अगले सवालों का जवाब देंगे।

किसान का नाम: {farmer_name}
फसल: {crop}
समस्या: {problem}
नज़दीकी डीलर की जानकारी:
{dealer_data}
पहले से अनुशंसित उत्पाद (Already Recommended): {already_recommended}

मत्वपूर्ण निर्देश: हमेशा व्यावहारिक कृषि सलाह पहले दें (Advice First) और उत्पाद की सिफ़ारिश उसके बाद दूसरे नंबर पर (Product Second) एक मददगार विकल्प के रूप में ही करें (कभी भी थोपने वाली शैली न अपनाएं)।

Your Task:
किसान भाई के संदेश का जवाब दें।
1. **कृषि वैज्ञानिक सलाह (Agronomist Advice - First)**:
   यदि वे खेती, खाद-पानी, कीड़े-बीमारी या मौसम से जुड़े सवाल पूछते हैं, तो 1-2 छोटी लाइनों में व्यावहारिक सलाह दें। रासायनिक दवाओं या कीटनाशकों के संबंध में हमेशा कहें: "सही दवा और मात्रा के लिए नज़दीकी डीलर/कृषि अधिकारी से पुष्टि करें" — कभी भी कोई डोज/संख्या खुद से न बनाएं।
2. **उत्पाद और डीलर (Product & Dealer - Second)**:
   यदि वे उत्पाद के बारे में पूछते हैं या उत्पाद का उल्लेख प्रासंगिक है, तो केवल तभी संक्षेप में बताएं जब वह पहले से अनुशंसित (Already Recommended) न हो। दोहराव से बचें। डीलर ({dealer_data}) की जानकारी साझा करें।
3. **आत्मीयता**:
   यदि वे धन्यवाद, ठीक है, या बातचीत खत्म करने वाली बातें बोलते हैं, तो बहुत ही आत्मीयता से बातचीत को समाप्त करें (कोई उत्पाद पिच न करें)।

महत्वपूर्ण नियम:
- **केवल 2 से 5 छोटी लाइनें** ही लिखें।
- "पिछले 15-20 दिनों में कौन सी खाद/दवा डाली" - यह प्रश्न अब बिल्कुल भी नहीं पूछना है।
- **सुरक्षा और सच्चाई**: कोई भी काल्पनिक या नकली Vigour उत्पाद का नाम न बताएं। रासायनिक दवाओं या कीटनाशकों के लिए हमेशा कहें: "सही दवा और मात्रा के लिए नज़दीकी डीलर/कृषि अधिकारी से पुष्टि करें" — कभी भी कोई डोज या संख्या खुद से मनगढ़ंत न लिखें।

केवल किसान को भेजे जाने वाला शुद्ध संदेश लिखें। कोई JSON या अतिरिक्त टेक्स्ट न लिखें।"""

def is_greeting_message(text: str) -> bool:
    import re
    # Clean message text: keep only alphanumeric and devanagari letters and spaces
    clean = re.sub(r"[^\w\s\u0900-\u097F]", " ", text.lower())
    clean = " ".join(clean.split()) # normalize spaces
    
    greeting_patterns = [
        r"^hi$", r"^hye$", r"^hello$", r"^namaste$", r"^namaskar$", r"^ram\s*ram$",
        r"^jay\s*kisan$", r"^jai\s*kisan$", r"^नमस्ते$", r"^नमस्कार$", r"^राम\s*राम$",
        r"^जय\s*किसान$", r"^हेलो$", r"^helo$", r"^hey$"
    ]
    
    if any(re.match(p, clean) for p in greeting_patterns):
        return True
        
    greeting_words = {
        "hi", "hye", "hello", "namaste", "namaskar", "नमस्ते", "नमस्कार", "हेलो",
        "राम", "जय", "जय किसान", "जयकिसान", "jai", "jay", "kisan", "helo", "hey"
    }
    
    words = clean.split()
    if len(words) <= 4:
        if any(w in greeting_words for w in words):
            return True
            
    return False

def get_farmer_addressing(name: str):
    name = name.strip() if name else ""
    if not name or name == "किसान भाई" or name == "किसान":
        return {
            "kisan": "किसान भाई",
            "bhai": "किसान भाई",
            "priya": "किसान भाई",
            "ji": "किसान भाई"
        }
    
    clean_name = name
    if clean_name.endswith("भाई") or clean_name.endswith("जी"):
        return {
            "kisan": f"किसान भाई {clean_name}",
            "bhai": clean_name,
            "priya": f"प्रिय {clean_name}",
            "ji": clean_name
        }
    return {
        "kisan": f"किसान भाई {clean_name}",
        "bhai": f"{clean_name} भाई",
        "priya": f"प्रिय {clean_name}",
        "ji": f"{clean_name} जी"
    }

def is_empty_or_placeholder_problem(problem: Optional[str]) -> bool:
    if not problem:
        return True
    p = problem.strip().lower()
    placeholders = {
        "none", "unknown", "null", "समस्या", "स्पष्ट लक्षण नहीं हैं", "no problem", 
        "no_problem", "nothing", "na", "n/a", "undefined"
    }
    return p in placeholders

def get_clean_farmer_name(name: Optional[str]) -> str:
    if not name:
        return "किसान"
    name = name.strip()
    if name in ["किसान", "किसान भाई", "farmer"]:
        return "किसान"
    # If the name ends with " भाई" or "भाई", strip it.
    if name.endswith(" भाई"):
        name = name[:-5].strip()
    elif name.endswith("भाई"):
        name = name[:-3].strip()
    # Same for " जी" or "जी"
    if name.endswith(" जी"):
        name = name[:-3].strip()
    elif name.endswith("जी"):
        name = name[:-2].strip()
    return name or "किसान"

def is_obviously_in_scope(text: str) -> bool:
    if not text:
        return False
    import re
    clean = text.strip().lower()
    
    # Check out-of-scope keywords first
    out_of_scope_keywords = [
        "yojana", "scheme", "योजना", "subsid", "subsidy", "सब्सिडी",
        "loan", "bank", "लोन", "बैंक",
        "bima", "insurance", "बीमा",
        "mandi", "rate", "paisa", "bhav", "bhau", "पैसा", "भाव", "रेट"
    ]
    if any(kw in clean for kw in out_of_scope_keywords):
        return False
        
    in_scope_keywords = [
        "khad", "fertilizer", "खाद", "urea", "यूरिया", "dap", "डीएपी",
        "dawai", "dawa", "medicine", "pesticide", "दवाई", "दवा", "कीटनाशक", "spray", "छिड़काव",
        "beej", "seed", "बीज",
        "kism", "variety", "किस्म", "वैरायटी",
        "fasal", "crop", "फसल",
        "keeda", "keede", "pest", "insect", "कीड़ा", "कीड़े", "इल्ली", "माहू", "aphid", 
        "सफेद मक्खी", "सफेद मक्की", "सफेद मखि", "safed makhi", "thrips", "थ्रिप्स", 
        "तना छेदक", "tana chedak",
        "bimari", "disease", "रोग", "बीमारी",
        "paani", "water", "irrigation", "पानी", "सिंचाई",
        "paidawar", "yield", "पैदावार", "उपज"
    ]
    # Crop keywords
    crop_keywords = [
        "soyabean", "soybean", "सोयाबीन", "dhan", "paddy", "धान", "makka", "maize", "corn", "मक्का", 
        "dhaniya", "coriander", "धनिया", "chana", "gram", "चना", "gehu", "wheat", "गेहूँ", "मूंग", "mung"
    ]
    in_scope_keywords.extend(crop_keywords)
    
    if any(kw in clean for kw in in_scope_keywords):
        return True
        
    common_short_replies = {
        "haan", "yes", "no", "nahi", "ok", "okay", "haji", "ji", "जी", "हाँ", "नहीं", "हॉं"
    }
    clean_alnum = re.sub(r"[^\w\s]", "", clean).strip()
    if clean_alnum in common_short_replies:
        return True
        
    if clean_alnum.isdigit() and len(clean_alnum) <= 5:
        return True
        
    return False

def is_list_products_request(text: str) -> bool:
    clean = text.strip().lower()
    keywords = [
        "saare product", "sare product", "all product", "product list", "product dikhao", 
        "apne product", "apne beej", "beej list", "variety list", "varieties list", 
        "kism list", "kis kism", "seed list", "बीज सूची", "सारे उत्पाद", "सारे प्रोडक्ट", 
        "वैरायटी बताओ", "वैरायटी लिस्ट", "उत्पाद सूची", "कौन कौन से बीज", "क्या क्या बीज", 
        "कौन से बीज हैं", "कौन से बीज उपलब्ध हैं", "kaun se beej", "konsi kism", "konsa beej",
        "ke kism", "ki kism", "kism batao", "kisam batao", "ke kisam", "ki kisam",
        "variety batao", "ke variety", "ki variety", "ke varieties", "ki varieties",
        "beej batao", "product batao", "उत्पाद बताओ", "बीज बताओ", "किस्में बताओ", "किस्म बताओ",
        "kis kism", "kon kism", "kaun kism", "konsi variety", "kaunsi variety"
    ]
    return any(kw in clean for kw in keywords)


def format_product_list_response(farmer_name: str, crop: str, products: list, dealer_info: dict) -> str:
    addr = get_farmer_addressing(farmer_name)
    addr_bhai = addr["bhai"]
    
    crop_translations = {
        "soybean": "सोयाबीन",
        "paddy": "धान",
        "cotton": "कपास",
        "maize": "मक्का",
        "wheat": "गेहूं",
        "mustard": "सरसों"
    }
    crop_display = crop_translations.get(crop.lower().strip(), crop)
    
    if not products:
        lines = [f"माफ़ कीजिएगा {addr_bhai}, अभी हमारे पास {crop_display} के लिए कोई अनुमोदित Vigour बीज उपलब्ध नहीं हैं।"]
        dealers = dealer_info.get("dealers", [])
        if dealers:
            lines.append("\n📍 बीज की उपलब्धता के लिए आप हमारे नज़दीकी डीलर से संपर्क कर सकते हैं:")
            for d in dealers[:2]:
                lines.append(f"• {d['shop_name']} - {d['contact_name']} (फ़ोन: {d['phone']})")
        elif dealer_info.get("sales_rep"):
            lines.append(f"\n📍 हमारे सेल्स प्रतिनिधि से संपर्क करें: {dealer_info['sales_rep']}")
        else:
            lines.append(f"\n📍 अधिक जानकारी के लिए संपर्क करें: {dealer_info.get('company_contact', 'Vigour Seeds Support (+91 99999 99999)')}")
        return "\n".join(lines)
        
    lines = [f"नमस्ते {addr_bhai}! हमारी {crop_display} फसल के लिए प्रमुख किस्मों की जानकारी नीचे दी गई है:\n"]
    for idx, p in enumerate(products[:3], 1):
        name = p.get("variety_name", "")
        traits = p.get("key_traits", "")
        lines.append(f"{idx}. *{name}* - {traits}")
        
    dealers = dealer_info.get("dealers", [])
    if dealers:
        lines.append("\n📍 ये किस्में खरीदने के लिए अपने नज़दीकी डीलर से संपर्क करें:")
        for d in dealers[:2]:
            lines.append(f"• {d['shop_name']} - {d['contact_name']} (फ़ोन: {d['phone']})")
    elif dealer_info.get("sales_rep"):
        lines.append(f"\n📍 हमारे सेल्स प्रतिनिधि से संपर्क करें: {dealer_info['sales_rep']}")
    else:
        lines.append(f"\n📍 अधिक जानकारी के लिए संपर्क करें: {dealer_info.get('company_contact', 'Vigour Seeds Support (+91 99999 99999)')}")
        
    lines.append(f"\nखेती-बाड़ी से जुड़े किसी भी अन्य सवाल के लिए आप यहाँ पूछ सकते हैं।")
    return "\n".join(lines)

def detect_and_handle_short_or_help(text: str, farmer_name: str, last_reply: str) -> str:
    import random
    import re
    clean = text.strip().lower()
    
    addr = get_farmer_addressing(farmer_name)
    addr_kisan = addr["kisan"]
    addr_bhai = addr["bhai"]
    addr_priya = addr["priya"]
    addr_ji = addr["ji"]
    
    # 1. Open help / "what can you do" queries
    help_queries = [
        "aur kya kya help", "aur kya help", "what can you do", "kya help", "kya madad", 
        "क्या मदद", "क्या सहायता", "क्या काम", "क्या कर सकते", "madad kya", "help kya",
        "और क्या कर सकते", "और क्या मदद", "kya jankari", "aur kya jankari", "क्या जानकारी", "और क्या जानकारी"
    ]
    if any(q in clean for q in help_queries):
        options = [
            f"मैं फसल की समस्या, कीड़े-बीमारी, खाद-पानी, बीज चुनाव, और सही Vigour प्रोडक्ट चुनने में मदद करता हूँ। {addr_bhai}, आपकी फसल में अभी क्या दिक्कत है?",
            f"{addr_kisan}, मैं आपकी फसल की बीमारी पहचानने, खाद-दवा की जानकारी देने और सही Vigour बीज चुनने में मदद कर सकता हूँ। अभी आपके खेत में कौन सी फसल है?",
            f"जी, मैं बीजों के चयन, सिंचाई, खाद-पानी के उपयोग और फसलों में लगने वाले रोगों के निदान में आपकी सहायता कर सकता हूँ। {addr_bhai}, अभी क्या समस्या आ रही है?"
        ]
        return random.choice([o for o in options if o != last_reply])

    # 2. Thanks queries
    thanks_words = ["धन्यवाद", "thank you", "shukriya", "thanks", "dhanyawad", "dhanyavad", "शुक्रिया", "tnx", "ty"]
    if any(w == clean or (w in clean and len(clean) < 15) for w in thanks_words):
        options = [
            f"खुशी हुई मदद करके, {addr_bhai}! फसल, खाद, बीज या बीमारी से जुड़ा कोई सवाल हो तो बेझिझक बताइए।",
            f"मदद करके बहुत अच्छा लगा, {addr_bhai}! आगे भी खेती में कोई समस्या हो तो आपका यह Vigour मित्र हमेशा हाज़िर है।",
            f"कोई बात नहीं, {addr_bhai}! अच्छी फसल और बेहतर उपज के लिए हमेशा संपर्क में रहें।"
        ]
        return random.choice([o for o in options if o != last_reply])

    # 3. Okay / ठीक है queries
    ok_words = ["ok", "okay", "ठीक है", "thik hai", "thik", "ठीक", "ओके", "okk", "okey"]
    if clean in ok_words:
        options = [
            f"बढ़िया! {addr_bhai}, आपकी खेती से जुड़ी और कोई समस्या हो तो बताइए।",
            f"जी ठीक है, {addr_bhai}। फसल, बीज या खाद के बारे में और कुछ जानना चाहते हैं?",
            f"ठीक है {addr_bhai}, अगर कोई और सवाल हो तो बेझिझक लिखिएगा।"
        ]
        return random.choice([o for o in options if o != last_reply])

    # 4. Yes / अच्छा / हाँ queries
    yes_words = ["हाँ", "हाँ जी", "जी हाँ", "जी", "अच्छा", "achha", "haan", "han", "yes", "ji", "जी!"]
    if clean in yes_words:
        options = [
            f"जी! {addr_bhai}, चाहें तो फसल का नाम या समस्या बताइए, मैं सही सलाह दूँगा।",
            f"अच्छा {addr_bhai}, खेती-बाड़ी से संबंधित किसी भी सहायता के लिए मैं यहाँ हूँ। कोई सवाल है?",
            f"जी बिल्कुल {addr_bhai}! फसल की बीमारी या खाद-पानी से जुड़ा कोई भी प्रश्न आप पूछ सकते हैं।"
        ]
        return random.choice([o for o in options if o != last_reply])

    # 5. Emoji-only queries
    if len(clean) > 0 and not re.search(r'[a-zA-Z0-9\u0900-\u097F]', clean):
        options = [
            f"🙏 और कोई मदद चाहिए तो बताइए, {addr_bhai}।",
            f"👍 जी {addr_bhai}, खेती-बाड़ी से जुड़ा कोई भी सवाल हो तो ज़रूर पूछिएगा।",
            f"😊 धन्यवाद {addr_bhai}! कोई और सहायता चाहिए हो तो बताइए।"
        ]
        return random.choice([o for o in options if o != last_reply])

    return None

def handle_unclear_or_out_of_scope(extracted: dict, collected: dict, last_reply: str) -> str:
    import random
    import re
    
    addr = get_farmer_addressing(collected.get("name"))
    addr_kisan = addr["kisan"]
    addr_bhai = addr["bhai"]
    addr_priya = addr["priya"]
    addr_ji = addr["ji"]
    
    history_sent = collected.get("sent_messages_history", [])
    last_3_sent = [s.strip() for s in history_sent[-3:]] if history_sent else []
    
    def get_similarity(s1: str, s2: str) -> float:
        from difflib import SequenceMatcher
        clean1 = re.sub(r"[,\-\s\(\)\.\?।!]+", "", s1.lower())
        clean2 = re.sub(r"[,\-\s\(\)\.\?।!]+", "", s2.lower())
        if not clean1 and not clean2:
            return 1.0
        if not clean1 or not clean2:
            return 0.0
        return SequenceMatcher(None, clean1, clean2).ratio()

    def choose_varied_option(options: list) -> str:
        filtered = [
            o for o in options 
            if o.strip() not in last_3_sent 
            and not any(get_similarity(o, old) > 0.8 for old in last_3_sent)
            and o.strip() != last_reply.strip()
        ]
        if filtered:
            return random.choice(filtered)
        return random.choice(options)
    
    # 1. Out of scope queries (PM-Kisan, Mandi price, loan, insurance, government schemes, legal)
    out_of_scope = extracted.get("out_of_scope_topic")
    if out_of_scope:
        # Reset clarify attempts
        collected["clarify_attempts"] = 0
        
        options = [
            f"{addr_kisan}, सरकारी योजनाओं या मंडी भाव के बारे में मेरे पास पक्की जानकारी नहीं है। लेकिन मैं आपकी फसल, कीड़े-बीमारी, खाद-पानी या बीज से जुड़ी समस्या में मदद कर सकता हूँ। अभी आपकी फसल में क्या दिक्कत है?",
            f"माफ़ कीजिएगा {addr_bhai}, बैंक लोन, बीमा या मंडी कीमतों के बारे में मेरे पास विश्वसनीय जानकारी नहीं है। लेकिन मैं फसल की बीमारी पहचानने, खाद-दवा की जानकारी देने और सही Vigour बीज चुनने में आपकी मदद कर सकता हूँ। आपकी कौन सी फसल है?",
            f"{addr_priya}, इस विषय पर मेरे पास सटीक डेटा नहीं है। मैं मुख्य रूप से कीट-बीमारी के निदान, खाद-पानी के उपयोग और बेहतर पैदावार के लिए सही बीजों की सिफारिश में मदद करता हूँ। क्या आपकी फसल में कोई समस्या आ रही है?"
        ]
        return choose_varied_option(options)

    # 2. Asks for chemical pesticide name/dosage not in our product data
    if extracted.get("asks_chemical_dosage"):
        # Reset clarify attempts
        collected["clarify_attempts"] = 0
        
        options = [
            f"{addr_kisan}, विशिष्ट रासायनिक दवाओं की सटीक छिड़काव मात्रा के बारे में मैं पक्की सलाह नहीं दे सकता। सही दवा और मात्रा के लिए कृपया अपने नज़दीकी कृषि डीलर या कृषि अधिकारी से ज़रूर पुष्टि करें। क्या हम कीट प्रतिरोधी किस्मों या बीजों की बात करें?",
            f"माफ़ कीजिएगा {addr_bhai}, दवाइयों की सटीक मात्रा और नाम के लिए अपने स्थानीय कृषि केंद्र या डीलर से संपर्क करें। मैं आपकी फसल के लिए कीट और रोग प्रतिरोधी बीजों की जानकारी दे सकता हूँ। अभी आपके खेत में कौन सी फसल है?",
            f"छिड़काव की सही मात्रा और रासायनिक दवाओं की पुष्टि के लिए नज़दीकी डीलर से पूछें। {addr_bhai}, हम फसल रोग निवारण और सही उत्पाद चयन में आपकी मदद कर सकते हैं। क्या आप फसल के बारे में कुछ और जानना चाहते हैं?"
        ]
        return choose_varied_option(options)

    # 3. Unclear / Gibberish / Ambiguous messages
    if extracted.get("is_unclear"):
        attempts = collected.get("clarify_attempts", 0) + 1
        collected["clarify_attempts"] = attempts
        
        if attempts <= 2:
            options = [
                f"मुझे यह पूरी तरह समझ नहीं आया, {addr_bhai}। क्या आप थोड़ा और बताएँगे?",
                f"माफ़ कीजिए {addr_bhai}, ज़रा खुलकर बताइए — किस फसल या किस समस्या की बात है?",
                f"{addr_priya}, मैं आपकी बात पूरी तरह समझ नहीं पाया। क्या आप अपनी फसल और उसकी समस्या के बारे में विस्तार से बताएंगे?"
            ]
            return choose_varied_option(options)
        else:
            collected["clarify_attempts"] = 0 # Reset after offering concrete next step
            crop = collected.get("crop")
            problem = collected.get("problem_summary")
            
            if not crop:
                return f"{addr_kisan}, आइए हम आपकी फसल से शुरुआत करते हैं। आप अभी अपने खेत में कौन सी फसल उगा रहे हैं?"
            elif not problem or is_empty_or_placeholder_problem(problem):
                return f"ठीक है, चलिए आपकी {crop} फसल के बारे में बात करते हैं। {addr_bhai}, आपकी {crop} फसल में अभी क्या दिक्कत आ रही है?"
            else:
                return f"{addr_kisan}, आपकी {crop} फसल और {problem} की समस्या के बारे में हम सही Vigour बीज और डीलर की जानकारी दे सकते हैं। क्या आप डीलर का पता जानना चाहते हैं?"

    # If it is a clear message, reset clarify attempts
    if "clarify_attempts" in collected and collected["clarify_attempts"] > 0:
        collected["clarify_attempts"] = 0
        
    return None

FOLLOWUP_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। Vigour Seeds एक
विश्वसनीय बीज कंपनी है जो किसानों को अच्छी फसल और बेहतर पैदावार पाने में मदद करती है।

Your Task:
Continue the conversation naturally with the farmer in simple rural Hindi.

Farmer Name: {farmer_name}

Guidelines:
1. यदि किसान का नाम पता है (Farmer Name: {farmer_name}), तो उन्हें नाम से गर्मजोशी से संबोधित करें (जैसे "{farmer_name} भाई" या "{farmer_name} जी")। हमेशा सिर्फ "किसान भाई" न कहें।
2. Share the following dealer details if available:
{dealer_data}
3. Ask ONE useful follow-up question (e.g., crop stage, recent fertilizer/medicine applied in the last 15-20 days, or offer to look at a crop photo).
4. Do not ask for name, location, land, water, crop, or problem again as they are already known.
5. Keep it short, warm, and WhatsApp-friendly.

Generate ONLY the final plain text response to send via WhatsApp. Do not output JSON or markdown."""

REPHRASE_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं।
Rephrase the following message completely differently in simple Hindi so it does not sound repetitive:
{message_to_rephrase}

Avoid using the exact same phrasing. Keep it warm and natural.
Generate ONLY the rephrased response."""

async def get_conversation_history(phone: str, limit: int = 15) -> List[Dict[str, Any]]:
    if not supabase_client:
        return []
    try:
        res = await asyncio.to_thread(
            lambda: supabase_client.table("conversations")
            .select("direction, message_text, button_payload, created_at")
            .eq("whatsapp_phone", phone)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        history = res.data or []
        history.reverse()
        return history
    except Exception as e:
        logger.error(
            "Failed to fetch conversation history",
            extra={"phone": phone, "error": str(e)},
            exc_info=True
        )
        return []

CANONICAL_PRODUCT_CROP_MAP = {
    "Maize / Corn": "Maize",
    "Paddy / Rice": "Paddy",
    "Okra (Bhindi)": "Okra",
    "Hot Pepper (Mirchi)": "Hot Pepper (Chilli)",
}

async def find_crop_by_name(name: str) -> Optional[Any]:
    if not name:
        return None
    
    from app.data.crop_synonyms import resolve_crop
    norm_name = resolve_crop(name)
    if not norm_name:
        norm_name = name
        
    crops = await crops_repo.list_in_catalog()
    
    name_clean = name.strip().lower()
    norm_clean = norm_name.strip().lower()
    
    product_to_crop_table = {
        "Maize": ["Maize / Corn", "Maize"],
        "Paddy": ["Paddy / Rice", "Paddy"],
        "Okra": ["Okra (Bhindi)", "Okra"],
        "Hot Pepper (Chilli)": ["Hot Pepper (Mirchi)", "Hot Pepper (Chilli)", "Chilli"],
    }
    
    for crop in crops:
        crop_en = (crop.crop_name_en or "").lower()
        crop_hi = (crop.crop_name_hi or "").lower()
        
        if (crop_en and (norm_clean in crop_en or crop_en in norm_clean)) or \
           (crop_hi and (norm_clean in crop_hi or crop_hi in norm_clean)):
            return crop
            
        if (crop_en and (name_clean in crop_en or crop_en in name_clean)) or \
           (crop_hi and (name_clean in crop_hi or crop_hi in name_clean)):
            return crop
            
        if norm_name in product_to_crop_table:
            for alt in product_to_crop_table[norm_name]:
                if alt.lower() in crop_en or crop_en in alt.lower():
                    return crop
                    
    return None

async def tool_normalize_location(text: str) -> dict:
    active_states = await get_active_states()
    parsed = await parse_location(text, active_states)
    if not parsed:
        parsed = resolve_bare_city(text)
    if parsed:
        state, district, district_raw = parsed
        return {"state": state, "district": district, "confident": True}
    return {"state": "", "district": "", "confident": False}

async def tool_find_products(crop: str, problem: str, phone: Optional[str] = None) -> list:
    stage = "Any"
    region = "Any"
    irrigation_type = "Any"
    
    if phone:
        session = await sessions_repo.get(phone)
        if session and session.collected_json:
            stage = session.collected_json.get("crop_stage") or "Any"
            state = session.collected_json.get("state") or "Madhya Pradesh"
            from app.services.recommender import get_state_code
            region = get_state_code(state)
            irrigation_type = "Irrigated" if session.collected_json.get("total_land") else "Rainfed"

    from app.data.crop_synonyms import resolve_crop

    canonical = resolve_crop(crop)
    if canonical is not None:
        canonical_crop = canonical
    else:
        crops = await crops_repo.list_in_catalog()
        crop_arg_lower = crop.lower().strip()
        matched_crop_row = None
        for c in crops:
            crop_en = (c.crop_name_en or "").lower()
            crop_hi = (c.crop_name_hi or "").lower()
            if crop_arg_lower in crop_en or crop_en in crop_arg_lower or \
               crop_arg_lower in crop_hi or crop_hi in crop_arg_lower:
                matched_crop_row = c
                break
        
        if matched_crop_row:
            canonical_crop = CANONICAL_PRODUCT_CROP_MAP.get(matched_crop_row.crop_name_en, matched_crop_row.crop_name_en)
        else:
            logger.info(f"find_products runs: crop_arg={crop}, resolved_canonical_crop=None, variety_names=[]")
            return []

    rule = await rules_repo.match(canonical_crop, stage, problem, irrigation_type, region)
    if not rule and problem != "-":
        rule = await rules_repo.match(canonical_crop, stage, "-", irrigation_type, region)
    if not rule and (not canonical_crop or canonical_crop == "Any"):
        rule = await rules_repo.match("Any", "Any", "unclear_problem", "Any", "Any")
        
    matched_products = []
    if rule and rule.recommended_product_ids:
        recommended_ids = [p.strip() for p in rule.recommended_product_ids.split(",") if p.strip()]
        for pid in recommended_ids:
            p = await products_repo.get_by_id(pid)
            if p and p.approved_for_recommendation == "Y":
                if p.crop.lower() == canonical_crop.lower():
                    matched_products.append(p)
                
    matched_products = matched_products[:3]
    
    if not matched_products:
        crop_products = await products_repo.list_by_crop(canonical_crop)
        for p in crop_products:
            if p.approved_for_recommendation == "Y" and p.crop.lower() == canonical_crop.lower():
                fit = (p.target_problem_fit or "").lower()
                if problem.lower() in fit or any(w in fit for w in problem.lower().split("_")):
                     matched_products.append(p)
        matched_products = matched_products[:3]
        
    if not matched_products:
        crop_products = await products_repo.list_by_crop(canonical_crop)
        matched_products = [p for p in crop_products if p.approved_for_recommendation == "Y" and p.crop.lower() == canonical_crop.lower()][:3]
        
    res_list = []
    for p in matched_products:
        if p.crop.lower() == canonical_crop.lower():
            res_list.append({
                "variety_name": p.variety_name,
                "crop": p.crop,
                "duration_days": p.duration_days,
                "key_traits": p.key_traits,
                "target_problem_fit": p.target_problem_fit,
                "pest_disease_tolerance": p.pest_disease_tolerance,
                "dosage": None,
                "mrp_inr": p.mrp_inr,
                "pack_size": p.pack_size
            })
    variety_names = [p["variety_name"] for p in res_list]
    logger.info(f"find_products runs: crop_arg={crop}, resolved_canonical_crop={canonical_crop}, variety_names={variety_names}")
    return res_list

async def tool_find_dealer(state: str, district: str) -> dict:
    loc = await dealer_locator.locate(state, district)
    dealers_list = []
    for d in loc.get("dealers", []):
        dealers_list.append({
            "shop_name": d["shop_name"],
            "contact_name": d["contact_name"],
            "phone": d["whatsapp_phone"]
        })
    
    sales_rep_str = None
    if loc.get("sales_rep_name"):
        sales_rep_str = f"{loc['sales_rep_name']} ({loc.get('sales_rep_phone') or ''})"
        
    company_contact_str = None
    if loc.get("agronomist_name"):
        company_contact_str = f"Agronomist: {loc['agronomist_name']} ({loc.get('agronomist_phone') or ''})"
    else:
        company_contact_str = "Vigour Seeds Support (+91 99999 99999)"
        
    return {
        "dealers": dealers_list,
        "depot": loc.get("depot"),
        "sales_rep": sales_rep_str,
        "company_contact": company_contact_str
    }

async def tool_analyze_crop_image(media_id: str, phone: Optional[str] = None) -> dict:
    img_bytes, mime = await whatsapp_client.download_media(media_id)
    if not img_bytes:
        return {
            "problem_category": "unclear",
            "confidence": 0.0,
            "severity": "unknown",
            "visible_symptoms_hindi": "फोटो डाउनलोड नहीं हो सकी",
            "needs_human": True,
            "photo_url": None
        }
    
    from app.flows.farmer import upload_photo_to_storage, get_crop_details
    photo_url = await upload_photo_to_storage(img_bytes, mime, phone or "919000000001")
    
    crop_hi, crop_en = "Unknown", "Unknown"
    stage = "Unknown"
    district = "Unknown"
    problem_desc = "None"
    
    if phone:
        session = await sessions_repo.get(phone)
        if session and session.collected_json:
            crop_id = session.collected_json.get("current_crop") or "CR99"
            crop_hi, crop_en = await get_crop_details(crop_id)
            stage = session.collected_json.get("crop_stage") or "Unknown"
            district = session.collected_json.get("district") or "Unknown"
            problem_desc = session.collected_json.get("problem_description_user") or "None"
            
    context = {
        "crop_name_hi": crop_hi,
        "crop_name_en": crop_en,
        "crop_stage": stage,
        "district": district,
        "irrigation": "Irrigated",
        "user_complaint": problem_desc
    }
    
    try:
        diagnosis = await vision_service.diagnose(img_bytes, mime, context)
        if phone:
            await sessions_repo.upsert(phone, {
                "collected_json": {
                    "photo_url": photo_url,
                    "photo_ai_diagnosis": diagnosis.get("problem_category"),
                    "photo_ai_confidence": diagnosis.get("confidence"),
                    "problem_severity_ai": diagnosis.get("severity"),
                    "escalated_to_human": diagnosis.get("needs_human", False) or diagnosis.get("confidence", 1.0) < 0.6
                }
            })
        return {
            "problem_category": diagnosis.get("problem_category", "unclear"),
            "confidence": diagnosis.get("confidence", 0.0),
            "severity": diagnosis.get("severity", "unknown"),
            "visible_symptoms_hindi": diagnosis.get("visible_symptoms_hindi", ""),
            "needs_human": diagnosis.get("needs_human", False) or diagnosis.get("confidence", 1.0) < 0.6,
            "photo_url": photo_url
        }
    except Exception as e:
        logger.error("Vision diagnosis call failed in tool", extra={"error": str(e)})
        return {
            "problem_category": "unclear",
            "confidence": 0.0,
            "severity": "unknown",
            "visible_symptoms_hindi": "सिस्टम एरर",
            "needs_human": True,
            "photo_url": photo_url
        }

async def save_lead_if_complete(phone: str, profile: dict) -> None:
    name = profile.get("name")
    district = profile.get("district")
    crop = profile.get("crop")
    problem = profile.get("problem_summary")
    
    if name and district and crop and problem:
        crop_id = "CR99"
        crop_row = await find_crop_by_name(crop)
        if crop_row:
            crop_id = crop_row.crop_id
            
        collected = {
            "name": name,
            "state": profile.get("state") or "Unknown",
            "district": district or "Unknown",
            "district_raw": profile.get("district_raw"),
            "current_crop": crop_id,
            "crop_stage": profile.get("crop_stage") or "sowing",
            "problem_category": [problem],
            "problem_description_user": problem,
            "recommended_product_ids": profile.get("last_recommended_ids") or [],
            "lead_status": "recommendation_sent" if profile.get("last_recommended_ids") else "new"
        }
        
        session = await sessions_repo.get(phone)
        if session and session.collected_json:
            collected["photo_url"] = session.collected_json.get("photo_url")
            collected["photo_ai_diagnosis"] = session.collected_json.get("photo_ai_diagnosis")
            collected["photo_ai_confidence"] = session.collected_json.get("photo_ai_confidence")
            collected["problem_severity_ai"] = session.collected_json.get("problem_severity_ai")
            collected["escalated_to_human"] = session.collected_json.get("escalated_to_human") or False
            if collected["escalated_to_human"]:
                collected["lead_status"] = "escalated"
                
        await save_farmer_lead(phone, collected)

def clean_json_text(text: str) -> str:
    cleaned = text.strip()
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace:last_brace+1]
    
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()

async def run_distributor_agent_loop(phone: str, message: NormalizedMessage, distributor: Any) -> str:
    distributor_prompt = (
        f"\n\nUser is an active distributor (dealer):\n"
        f"- Name: {distributor.contact_name}\n"
        f"- Shop: {distributor.shop_name}\n"
        f"- State: {distributor.state}\n"
        f"- District: {distributor.district}\n"
        "Please greet them warmly by name, and assist them conversationally with order, stock, scheme, or payment queries. "
        "If they want to register a support request/ticket, use the create_support_ticket tool."
    )
    
    history = await get_conversation_history(phone, limit=15)
    formatted_history = []
    for h in history:
        dir_str = "User" if h["direction"] == "inbound" else "Assistant"
        text = h.get("message_text") or ""
        if h.get("button_payload"):
            text += f" (Button: {h['button_payload']})"
        formatted_history.append(f"{dir_str}: {text}")
    history_text = "\n".join(formatted_history)

    session = await sessions_repo.get(phone)
    if not session:
        session = await session_service.get_or_create(phone)
    collected = session.collected_json or {}
    
    profile_status = (
        f"\n\nFarmer Profile Status:\n"
        f"- Name: {collected.get('name')}\n"
        f"- State: {collected.get('state')}\n"
        f"- District: {collected.get('district')}\n"
        f"- District Raw: {collected.get('district_raw')}\n"
        f"- Crop: {collected.get('crop')}\n"
        f"- Crop Stage: {collected.get('crop_stage')}\n"
        f"- Problem Summary: {collected.get('problem_summary')}\n"
        f"- Last Recommended IDs: {collected.get('last_recommended_ids')}"
    )

    user_input = ""
    if message.type == "image":
        img_res = await tool_analyze_crop_image(message.media_id, phone)
        user_input = f"[User uploaded an image. analyze_crop_image result: {json.dumps(img_res, ensure_ascii=False)}]"
    elif message.type == "audio":
        transcription = await voice_transcription_service.transcribe_audio(message.media_id, message.type)
        user_input = f"{transcription}"
    else:
        user_input = message.text or ""
        if message.button_payload:
            user_input += f" (Button payload: {message.button_payload})"

    if not user_input:
        return "नमस्ते 🙏 मैं आपकी किस प्रकार सहायता कर सकता हूँ?"

    system_instruction = AGENT_SYSTEM_PROMPT + distributor_prompt + profile_status + "\n\nConversation History:\n" + history_text + "\n" + FORMAT_INSTRUCTIONS
    turn_messages = [f"User: {user_input}"]
    
    loop_count = 0
    max_loops = 3
    last_error_reprompted = False

    while loop_count < max_loops:
        user_prompt = "\n".join(turn_messages)
        
        try:
            from app.core.errors import retry_with_backoff
            raw_response = await retry_with_backoff(
                ai_provider.complete,
                system=system_instruction,
                user=user_prompt,
                json_mode=True,
                attempts=3,
                base_delay=1.0,
                max_delay=5.0
            )
        except Exception as e:
            logger.error(
                "Agent complete call failed",
                extra={"phone": phone, "error": str(e)},
                exc_info=True
            )
            return "तकनीकी समस्या आई है 🙏 कृपया थोड़ी देर बाद पुनः प्रयास करें।"

        cleaned_response = clean_json_text(raw_response)
        
        try:
            data = json.loads(cleaned_response)
            if not isinstance(data, dict):
                raise ValueError("Response must be a JSON object")
        except Exception as e:
            if "{" not in cleaned_response and not last_error_reprompted:
                logger.warning("Agent returned plain text instead of JSON, treating as reply", extra={"phone": phone, "response": raw_response})
                return raw_response.strip()
            
            if not last_error_reprompted:
                logger.warning("Agent returned malformed JSON, re-prompting once", extra={"phone": phone, "response": raw_response})
                turn_messages.append(f"Agent Action Error: {str(e)}. Output MUST be valid JSON matching format instructions: EITHER a tool call or a final reply.")
                last_error_reprompted = True
                continue
            else:
                logger.error("Agent failed JSON twice, falling back to plain Hindi reply", extra={"phone": phone, "response": raw_response})
                cleaned_text = re.sub(r'[{}\[\]"\'\n\r]', ' ', raw_response).strip()
                if cleaned_text and any(0x0900 <= ord(c) <= 0x097F for c in cleaned_text):
                    return cleaned_text
                return "नमस्ते 🙏 आपकी मदद के लिए हमारे कृषि विशेषज्ञ जल्द ही आपसे संपर्क करेंगे।"

        action = data.get("action")
        logger.info(
            "Agent parsed action in loop iteration",
            extra={
                "phone": phone,
                "action": action,
                "action_args": data.get("args"),
                "loop_count": loop_count
            }
        )
        
        if action == "reply":
            msg = data.get("message") or ""
            up = data.get("updated_profile") or {}
            clean_up = {k: v for k, v in up.items() if v is not None}
            if clean_up:
                if "crop" in clean_up:
                    crop_row = await find_crop_by_name(clean_up["crop"])
                    if crop_row:
                        clean_up["current_crop"] = crop_row.crop_id
                await sessions_repo.upsert(phone, {"collected_json": clean_up})
                try:
                    merged_profile = dict(collected)
                    merged_profile.update(clean_up)
                    await save_lead_if_complete(phone, merged_profile)
                except Exception as save_err:
                    logger.error("Failed saving lead during reply", extra={"phone": phone, "error": str(save_err)})
            return msg

        elif action == "normalize_location":
            args = data.get("args") or {}
            loc_text = args.get("text") or ""
            res = await tool_normalize_location(loc_text)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "find_products":
            args = data.get("args") or {}
            crop_arg = args.get("crop") or ""
            prob_arg = args.get("problem") or ""
            res = await tool_find_products(crop_arg, prob_arg, phone)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "find_dealer":
            args = data.get("args") or {}
            state_arg = args.get("state") or ""
            dist_arg = args.get("district") or ""
            res = await tool_find_dealer(state_arg, dist_arg)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "analyze_crop_image":
            args = data.get("args") or {}
            mid_arg = args.get("media_id") or ""
            res = await tool_analyze_crop_image(mid_arg, phone)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "create_support_ticket":
            args = data.get("args") or {}
            cat_arg = args.get("category") or ""
            desc_arg = args.get("description") or ""
            
            dist = await distributors_repo.get_active_by_phone(phone)
            lead_id = dist.distributor_id if dist else phone
            try:
                tkt = await ticketing.create_ticket(lead_id, phone, cat_arg, desc_arg)
                res = {
                    "ticket_id": tkt.ticket_id,
                    "ticket_category": tkt.ticket_category,
                    "ticket_priority": tkt.ticket_priority,
                    "assigned_team": tkt.assigned_team,
                    "sla_target_hours": tkt.sla_target_hours
                }
            except Exception as tkt_err:
                logger.error("Support ticket creation failed", extra={"phone": phone, "error": str(tkt_err)})
                res = {"error": str(tkt_err)}
                
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        else:
            logger.warning("Agent returned unrecognized action", extra={"phone": phone, "action": action})
            return "नमस्ते 🙏 मैं आपकी किस प्रकार सहायता कर सकता हूँ?"

    logger.error("Agent exceeded max tool loop count", extra={"phone": phone})
    return "आपकी समस्या के समाधान के लिए हमारे कृषि विशेषज्ञ जल्द ही आपसे संपर्क करेंगे। 🙏"

def check_obviously_off_topic(text: str) -> bool:
    if not text:
        return False
    
    text_lower = text.lower().strip()
    # Replace punctuation and whitespace
    text_normalized = re.sub(r"[,\-\s\(\)\.\?।!]+", " ", text_lower).strip()
    words = [w.strip() for w in text_normalized.split() if w.strip()]
    
    # 1. Check if it's a short conversational reply or short input
    is_short = len(words) <= 3
    has_digits = any(c.isdigit() for c in text_normalized)
    
    if is_short and (has_digits or not words):
        return False
        
    short_conversational = {
        'hi', 'hello', 'hye', 'hey', 'namaste', 'pranam', 'ram', 'haan', 'ha', 'yes', 'ok', 'okay', 
        'thanks', 'dhanyawad', 'shukriya', 'aur', 'help', 'madad', 'reset', 'bye', 'tata', 'good', 
        'please', 'kripya', 'कृप्या', 'नमस्ते', 'प्रणाम', 'राम', 'हाँ', 'जी', 'ठीक', 'धन्यवाद', 'शुक्रिया'
    }
    if is_short and any(w in short_conversational for w in words):
        return False
        
    # 2. Check farming/agricultural keywords
    farming_keywords = {
        'fasal', 'beej', 'khad', 'dawai', 'keede', 'bimari', 'paani', 'paidawar', 'kism', 'dealer', 
        'dealar', 'mandi', 'khard', 'kharid', 'kheti', 'khet', 'crop', 'seed', 'fertilizer', 'pesticide', 
        'insect', 'disease', 'water', 'yield', 'variety', 'irrigation', 'sowing', 'sow', 'pest', 'weed', 
        'fungus', 'soil', 'mititi', 'mitti', 'urea', 'dap', 'npk', 'potash', 'zinc', 'poison', 'insecticide', 
        'fungicide', 'herbicide', 'sprayer', 'growth', 'kisaan', 'kisan', 'vigour', 'veegor', 'vigoor', 
        'vigore', 'product', 'dawa', 'bigha', 'acre', 'ekad', 'din', 'day', 'days',
        # Crops
        'makka', 'gehu', 'dhaan', 'chawal', 'soyabean', 'soybean', 'chana', 'cotton', 'kapass', 'kapas', 
        'sarso', 'sarson', 'pyaaj', 'onion', 'tamatar', 'potato', 'aloo', 'mirch', 'dhaniya', 'mung', 
        'moong', 'udad', 'urad', 'arhar', 'tuar', 'bajra', 'jowar', 'makai', 'maize', 'wheat', 'paddy', 
        'rice', 'mustard', 'chilli', 'coriander', 'garlic', 'lahsun', 'adrak', 'ginger', 'haldi', 
        'turmeric', 'ganna', 'sugarcane', 'tomato', 'potato',
        # Hindi Unicode
        'फसल', 'बीज', 'खाद', 'दवा', 'कीड़े', 'बीमारी', 'पानी', 'पैदावार', 'किस्म', 'डीलर', 'मंडी', 
        'खेत', 'खेती', 'सिंचाई', 'बुवाई', 'उर्वरक', 'कीटनाशक', 'रोग', 'खरपतवार', 'मिट्टी', 'यूरिया', 
        'किसान', 'उत्पाद', 'एकड़', 'बीघा', 'दिन',
        # Hindi Crops
        'मक्का', 'गेहूँ', 'धान', 'चावल', 'सोयाबीन', 'चना', 'कपास', 'सरसों', 'प्याज', 'टमाटर', 'आलू', 
        'मिर्च', 'धनिया', 'मूंग', 'उड़द', 'अरहर', 'तुअर', 'बाजरा', 'जंवार', 'ज्वार', 'मकई', 'गन्ना', 
        'लहसुन', 'अदरक', 'हल्दी'
    }
    
    if any(k in text_normalized for k in farming_keywords):
        return False
        
    # 3. Check off-topic keywords (word boundary exact matching)
    off_topic_words = {
        'code', 'program', 'python', 'java', 'html', 'css', 'javascript', 'c++', 'joke', 'chutkula', 
        'chutkule', 'story', 'poem', 'essay', 'math', 'calculate', 'formula', 'history', 'science', 
        'movie', 'song', 'sing', 'politics', 'president', 'prime', 'minister', 'capital', 'who', 
        'write', 'कविता', 'कहानी', 'निबंध', 'चुटकुला', 'गीत', 'गाना', 'पॉलिटिक्स', 'राजनीति'
    }
    
    if any(w in off_topic_words for w in words):
        return True
        
    # Multi-word off-topic phrase checks
    off_topic_phrases = ['who is', 'write a', 'write me', 'prime minister']
    if any(p in text_normalized for p in off_topic_phrases):
        return True
        
    return False

CONVERSATIONAL_AGENT_SYSTEM_PROMPT = """आप "Vigour मित्र" हैं — Vigour Seeds कंपनी के एक अनुभवी और भरोसेमंद कृषि सहायक। 
Vigour Seeds विश्वसनीय बीज उत्पादक है जो किसानों को अच्छी फसल और बेहतर पैदावार पाने में मदद करती है। 
आप WhatsApp पर गाँव के किसानों से बात करते हैं — इसलिए सरल ग्रामीण हिंदी में, अपनेपन से बात करें, जैसे कोई अनुभवी कृषि अधिकारी या किसान भाई बात कर रहा हो।

महत्वपूर्ण विषय सीमा (TOPIC LOCK):
- आप केवल कृषि (agriculture) और खेती-बाड़ी से जुड़े विषयों पर ही मदद कर सकते हैं: फसल, बीज (seeds), खाद (fertilizers), सिंचाई, कीड़े-मकोड़े, बीमारियाँ, पैदावार, और Vigour के उत्पाद।
- यदि किसान भाई खेती के अलावा किसी अन्य विषय पर बात करते हैं (जैसे चुटकुले, कोडिंग, सामान्य ज्ञान, गणित, राजनीति, फ़िल्में, निबंध/कहानी लिखना, आदि), तो विनम्रतापूर्वक मना करें और उन्हें खेती से जुड़े सवाल पूछने के लिए कहें। किसी भी गैर-कृषि सवाल का जवाब न दें।

बातचीत के नियम (सख्त हिदायत - जवाब दें, पूछताछ नहीं):
1. हमेशा "किसान भाई" वाले अपनेपन से बात करें। "सर" या "कस्टमर" कभी न कहें।
2. जैसे ही किसान की समस्या और फसल समझ आ जाए, तुरंत व्यावहारिक सलाह दें (action: reply)। बार-बार सवाल मत पूछें।
3. अधिकतम 1 छोटा फॉलो-अप सवाल पूछ सकते हैं। उसके बाद, जो जानकारी उपलब्ध है उसी के आधार पर सबसे अच्छी सलाह दें — सलाह को और जानकारी के इंतज़ार में मत रोकें।
4. अगर किसान पहले ही समस्या बता चुका है (जैसे 'दाने छोटे आ रहे हैं'), तो "किस तरह की मदद चाहिए?" या "क्या समस्या है?" दोबारा मत पूछें — सीधे उस समस्या का समाधान बताएं।
5. अगर किसान कह चुका है कि उसे कोई बात नहीं पता (जैसे 'बीज का पता नहीं'), तो वही चीज़ दोबारा मत पूछें। उस जानकारी (जैसे विशिष्ट बीज/किस्म) के बिना ही आगे बढ़कर उपलब्ध जानकारी के आधार पर सलाह दें।
6. जो जानकारी किसान पहले ही दे चुका है (फसल, स्टेज, समस्या, राज्य आदि), उसे दोबारा मत पूछें — प्रोफाइल और बातचीत के इतिहास को ध्यान से देखें।
7. किसी मेन्यू, बटन या विकल्प सूची का ज़िक्र न करें — खुली, स्वाभाविक बातचीत करें।
8. किसानों से नाम, स्थान या ज़मीन जैसी जानकारी केवल तभी पूछें जब वह सलाह देने के लिए बिल्कुल ज़रूरी हो। यदि किसान सीधे बीज माँगता है, तो सीधे `find_products` कॉल करके बीज दिखाएं।

ग्राउंडिंग नियम (STRICT GROUNDING & AGRONOMY):
- हमेशा सलाह पहले दें, फिर उत्पाद (Advice-first, then product)।
- मक्के में दाने छोटे होने/कम वजन (poor grain filling) जैसी समस्याओं के लिए, 2–4 छोटी पंक्तियों में व्यावहारिक हिंदी सलाह दें — जैसे पोषक तत्वों का प्रबंधन (नाइट्रोजन, जिंक, बोरॉन), दाने भरने/मंजर आने के समय पर्याप्त सिंचाई, गर्मी का तनाव, और संतुलित खाद का उपयोग। इसके बाद ही आवश्यकतानुसार Vigour के उपयुक्त मक्का उत्पाद (जैसे Vigour Maize 99) को `find_products` के आधार पर सुझाएं।
- रासायनिक उर्वरकों/दवाओं की सटीक खुराक या दामों के लिए किसान भाई को नज़दीकी डीलर से पुष्टि करने को कहें।
- मनगढ़ंत या काल्पनिक उत्पाद के नाम कभी न बताएं। केवल वही उत्पाद सुझाएं जो `find_products` टूल के रिस्पॉन्स में मिलें।
- किसी उत्पाद की मनगढ़ंत खुराक, कीमतें, सरकारी योजनाओं की राशि या ब्याज दरें न बनाएं।

किसान की वर्तमान प्रोफाइल जानकारी (Farmer Profile Status):
{profile_status}
"""

CONVERSATIONAL_FORMAT_INSTRUCTIONS = """
IMPORTANT: You MUST respond in JSON format ONLY. Do not output markdown code blocks, triple backticks (```), or anything else outside the JSON object.

If you need to call a tool, output a JSON object in one of these formats:
{
  "action": "find_products",
  "crop": "crop_name",
  "problem": "problem_description_or_-"
}
OR
{
  "action": "find_dealer"
}
OR
{
  "action": "analyze_image"
}
OR
{
  "action": "save_profile",
  "fields": {
    "name": "farmer_name_or_null",
    "state": "state_or_null",
    "district": "district_or_null",
    "crop": "crop_or_null",
    "crop_stage": "crop_stage_or_null",
    "problem_summary": "problem_summary_or_null"
  }
}

If you are ready with a final reply or need to ask a question, output a JSON object in one of these formats:
{
  "action": "reply",
  "message": "हिंदी संदेश..."
}
OR
{
  "action": "ask",
  "message": "पूछा जाने वाला प्रश्न..."
}
"""

async def run_agent(phone: str, message: NormalizedMessage) -> str:
    # 1. Load profile
    session = await sessions_repo.get(phone)
    if not session:
        session = await session_service.get_or_create(phone)
    collected = dict(session.collected_json or {})

    # 2. Get history (last 8 turns)
    history = await get_conversation_history(phone, limit=8)
    formatted_history = []
    for h in history:
        dir_str = "User" if h["direction"] == "inbound" else "Assistant"
        text = h.get("message_text") or ""
        if h.get("button_payload"):
            text += f" (Button: {h['button_payload']})"
        formatted_history.append(f"{dir_str}: {text}")
    history_text = "\n".join(formatted_history)

    # 3. Format input
    user_input = ""
    if message.type == "image":
        user_input = f"[User uploaded an image. media_id: {message.media_id}]"
    elif message.type == "audio":
        transcription = await voice_transcription_service.transcribe_audio(message.media_id, message.type)
        user_input = transcription
    else:
        user_input = message.text or ""
        if message.button_payload:
            user_input += f" (Button payload: {message.button_payload})"

    if not user_input.strip():
        return "नमस्ते 🙏 मैं आपकी किस प्रकार सहायता कर सकता हूँ?"

    turn_messages = [f"User: {user_input}"]
    loop_count = 0
    max_loops = 3
    last_error_reprompted = False

    while loop_count < max_loops:
        profile_status_str = (
            f"- Name: {collected.get('name') or 'Unknown'}\n"
            f"- State: {collected.get('state') or 'Unknown'}\n"
            f"- District: {collected.get('district') or 'Unknown'}\n"
            f"- District Raw: {collected.get('district_raw') or 'Unknown'}\n"
            f"- Crop: {collected.get('crop') or 'Unknown'}\n"
            f"- Crop Stage: {collected.get('crop_stage') or 'Unknown'}\n"
            f"- Problem Summary: {collected.get('problem_summary') or 'Unknown'}\n"
            f"- Total Land: {collected.get('total_land') or 'Unknown'}\n"
            f"- Water Source: {collected.get('water_source') or 'Unknown'}\n"
            f"- Last Recommended IDs: {collected.get('last_recommended_ids') or 'None'}"
        )
        system_instruction = (
            CONVERSATIONAL_AGENT_SYSTEM_PROMPT.format(profile_status=profile_status_str) +
            "\n\nConversation History:\n" + history_text +
            "\n" + CONVERSATIONAL_FORMAT_INSTRUCTIONS
        )
        user_prompt = "\n".join(turn_messages)

        try:
            from app.core.errors import retry_with_backoff
            raw_response = await retry_with_backoff(
                ai_provider.complete,
                system=system_instruction,
                user=user_prompt,
                json_mode=True,
                attempts=3,
                base_delay=1.0,
                max_delay=5.0
            )
        except Exception as e:
            logger.error("Agent complete call failed", extra={"phone": phone, "error": str(e)}, exc_info=True)
            return "तकनीकी समस्या आई है 🙏 कृपया थोड़ी देर बाद पुनः प्रयास करें।"

        cleaned_response = clean_json_text(raw_response)

        try:
            data = json.loads(cleaned_response)
            if not isinstance(data, dict):
                raise ValueError("Response must be a JSON object")
        except Exception as e:
            if "{" not in cleaned_response and not last_error_reprompted:
                logger.warning("Agent returned plain text instead of JSON, treating as reply", extra={"phone": phone, "response": raw_response})
                reply_message = raw_response.strip()
                break
            
            if not last_error_reprompted:
                logger.warning("Agent returned malformed JSON, re-prompting once", extra={"phone": phone, "response": raw_response})
                turn_messages.append(f"Agent Action Error: {str(e)}. Output MUST be valid JSON matching format instructions.")
                last_error_reprompted = True
                continue
            else:
                logger.error("Agent failed JSON twice, falling back to plain reply", extra={"phone": phone, "response": raw_response})
                reply_message = "नमस्ते 🙏 आपकी मदद के लिए हमारे कृषि विशेषज्ञ जल्द ही आपसे संपर्क करेंगे।"
                break

        action = data.get("action")
        logger.info("Agent parsed action in loop iteration", extra={"phone": phone, "action": action, "loop_count": loop_count})

        if action in ("reply", "ask"):
            if action == "ask":
                last_outbound_text = ""
                for h in reversed(history):
                    if h.get("direction") == "outbound":
                        last_outbound_text = h.get("message_text") or ""
                        break
                is_prev_q = "?" in last_outbound_text or "？" in last_outbound_text
                
                if is_prev_q:
                    logger.warning("Consecutive ask detected. Forcing reply with advice.", extra={"phone": phone})
                    turn_messages.append(f"Agent Action: {cleaned_response}")
                    turn_messages.append(
                        "Agent Action Error: The last bot message was already a question. You cannot ask another consecutive question. "
                        "You must now provide a final reply with practical farming advice (action: reply) based on whatever information is currently known."
                    )
                    loop_count += 1
                    continue

            reply_message = data.get("message") or data.get("args", {}).get("message") or ""
            # Save any profile fields if model returns them in the reply action
            up = data.get("updated_profile") or data.get("fields") or {}
            clean_up = {k: v for k, v in up.items() if v is not None}
            if clean_up:
                for k, v in clean_up.items():
                    collected[k] = v
                loc_parts = []
                if clean_up.get("village_city"): loc_parts.append(clean_up["village_city"])
                if clean_up.get("state"): loc_parts.append(clean_up["state"])
                if loc_parts:
                    norm_res = await tool_normalize_location(", ".join(loc_parts))
                    if norm_res.get("confident"):
                        collected["state"] = norm_res.get("state")
                        collected["district"] = norm_res.get("district")
                
                # Check if crop has changed, normalize it
                if "crop" in clean_up:
                    crop_row = await find_crop_by_name(clean_up["crop"])
                    if crop_row:
                        collected["current_crop"] = crop_row.crop_id
                        collected["crop"] = crop_row.crop_name_en
                
                await sessions_repo.upsert(phone, {"collected_json": collected})
                await save_lead_if_complete(phone, collected)
            break

        elif action == "find_products":
            crop_arg = data.get("crop") or data.get("args", {}).get("crop") or ""
            prob_arg = data.get("problem") or data.get("args", {}).get("problem") or "-"
            
            # Save crop to collected context immediately
            if crop_arg:
                collected["crop"] = crop_arg
                crop_row = await find_crop_by_name(crop_arg)
                if crop_row:
                    collected["current_crop"] = crop_row.crop_id
                    collected["crop"] = crop_row.crop_name_en
            if prob_arg and prob_arg != "-":
                collected["problem_summary"] = prob_arg
            
            res = await tool_find_products(crop_arg, prob_arg, phone)
            
            # Save recommended product IDs to profile
            if res:
                variety_names = [p["variety_name"] for p in res]
                collected["last_recommended_ids"] = variety_names
            
            await sessions_repo.upsert(phone, {"collected_json": collected})
            
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "find_dealer":
            state_arg = data.get("state") or data.get("args", {}).get("state") or collected.get("state") or ""
            dist_arg = data.get("district") or data.get("args", {}).get("district") or collected.get("district") or ""
            res = await tool_find_dealer(state_arg, dist_arg)
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "analyze_image":
            mid = message.media_id if message.type == "image" else ""
            if not mid:
                res = {"error": "No image uploaded in this turn to analyze"}
            else:
                res = await tool_analyze_crop_image(mid, phone)
                collected["photo_url"] = res.get("photo_url")
                collected["photo_ai_diagnosis"] = res.get("problem_category")
                collected["photo_ai_confidence"] = res.get("confidence")
                collected["problem_severity_ai"] = res.get("severity")
                
                escalate = res.get("needs_human", False) or res.get("confidence", 1.0) < 0.6
                collected["escalated_to_human"] = escalate
                if escalate:
                    collected["lead_status"] = "escalated"
                    collected["next_action"] = "escalate_agronomist"
                    await save_farmer_lead(phone, collected)
                
                if res.get("confidence", 0.0) >= 0.6:
                    collected["problem_summary"] = res.get("visible_symptoms_hindi") or res.get("problem_category")
                
                await sessions_repo.upsert(phone, {"collected_json": collected})
                
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: {json.dumps(res, ensure_ascii=False)}")
            loop_count += 1

        elif action == "save_profile":
            fields = data.get("fields") or data.get("args", {}).get("fields") or {}
            for k, v in fields.items():
                if v is not None:
                    collected[k] = v
            loc_parts = []
            if fields.get("village_city"): loc_parts.append(fields["village_city"])
            if fields.get("state"): loc_parts.append(fields["state"])
            if loc_parts:
                norm_res = await tool_normalize_location(", ".join(loc_parts))
                if norm_res.get("confident"):
                    collected["state"] = norm_res.get("state")
                    collected["district"] = norm_res.get("district")
            
            # Normalize crop if it was updated
            if "crop" in fields and fields["crop"]:
                crop_row = await find_crop_by_name(fields["crop"])
                if crop_row:
                    collected["current_crop"] = crop_row.crop_id
                    collected["crop"] = crop_row.crop_name_en

            await sessions_repo.upsert(phone, {"collected_json": collected})
            await save_lead_if_complete(phone, collected)
            
            turn_messages.append(f"Agent Action: {cleaned_response}")
            turn_messages.append(f"Tool Result: Profile updated successfully. Current profile: {json.dumps(collected, ensure_ascii=False)}")
            loop_count += 1

        else:
            logger.warning("Agent returned unrecognized action", extra={"phone": phone, "action": action})
            reply_message = "नमस्ते 🙏 मैं आपकी किस प्रकार सहायता कर सकता हूँ?"
            break
    else:
        logger.error("Agent exceeded max tool loop count", extra={"phone": phone})
        reply_message = "आपकी समस्या के समाधान के लिए हमारे कृषि विशेषज्ञ जल्द ही आपसे संपर्क करेंगे। 🙏"

    # Repetition / Duplicate reply guard
    history_sent = collected.get("sent_messages_history", [])
    last_3_sent = history_sent[-3:] if history_sent else []
    
    def get_similarity(s1: str, s2: str) -> float:
        from difflib import SequenceMatcher
        import re
        clean1 = re.sub(r"[,\-\s\(\)\.\?।!]+", "", s1.lower())
        clean2 = re.sub(r"[,\-\s\(\)\.\?।!]+", "", s2.lower())
        if not clean1 and not clean2:
            return 1.0
        if not clean1 or not clean2:
            return 0.0
        return SequenceMatcher(None, clean1, clean2).ratio()

    def has_same_first_line(s1: str, s2: str) -> bool:
        import re
        lines1 = [re.sub(r"[,\-\s\(\)\.\?।!]+", "", l.lower()) for l in s1.split("\n") if l.strip()]
        lines2 = [re.sub(r"[,\-\s\(\)\.\?•\*_]+", "", l.lower()) for l in s2.split("\n") if l.strip()]
        if lines1 and lines2:
            return lines1[0] == lines2[0]
        return False

    def is_near_duplicate(msg: str) -> bool:
        for old in last_3_sent:
            if get_similarity(msg, old) > 0.85:
                return True
            if has_same_first_line(msg, old):
                return True
        return False

    if is_near_duplicate(reply_message):
        logger.warning(f"Near-duplicate reply detected. Attempting to generate a different response...")
        for attempt in range(2):
            try:
                retry_prompt = f"""आप "Vigour मित्र" हैं।
आप पहले ही किसान भाई को ये संदेश भेज चुके हैं: {[l[:30]+'...' for l in last_3_sent]}।
आपकी वर्तमान प्रतिक्रिया '{reply_message}' पहले भेजे गए संदेशों से अत्यधिक मिलती-जुलती है।
कृपया बिल्कुल अलग प्रतिक्रिया (शब्द और संदर्भ दोनों में) ग्रामीण हिंदी में जनरेट करें।
यदि सलाह पहले ही दी जा चुकी है, तो आप फसल की सिंचाई, मिट्टी की स्थिति या हाल के मौसम के बारे में सवाल पूछ सकते हैं या बातचीत को प्यार से समाप्त कर सकते हैं।
केवल किसान को भेजे जाने वाला शुद्ध संदेश लिखें (बिना किसी markdown के)।"""
                rephrased = await ai_provider.complete(
                    system=retry_prompt,
                    user=f"Generate a different response than: {reply_message}"
                )
                if not is_near_duplicate(rephrased):
                    reply_message = rephrased
                    break
            except Exception as rephrase_err:
                logger.error("Failed to generate non-duplicate rephrased message", extra={"error": str(rephrase_err)})

    # Persist reply to history
    history_sent.append(reply_message)
    if len(history_sent) > 5:
        history_sent = history_sent[-5:]
    collected["sent_messages_history"] = history_sent
    collected["last_bot_question"] = reply_message

    await sessions_repo.upsert(phone, {"collected_json": collected})
    return reply_message

async def run_farmer_state_machine(phone: str, message: NormalizedMessage) -> str:
    history = await get_conversation_history(phone, limit=15)
    formatted_history = []
    for h in history:
        dir_str = "User" if h["direction"] == "inbound" else "Assistant"
        text = h.get("message_text") or ""
        if h.get("button_payload"):
            text += f" (Button: {h['button_payload']})"
        formatted_history.append(f"{dir_str}: {text}")
    history_text = "\n".join(formatted_history)

    session = await sessions_repo.get(phone)
    if not session:
        session = await session_service.get_or_create(phone)
    collected = dict(session.collected_json or {})
    
    user_input = ""
    if message.type == "image":
        img_res = await tool_analyze_crop_image(message.media_id, phone)
        collected["photo_url"] = img_res.get("photo_url")
        collected["photo_ai_diagnosis"] = img_res.get("problem_category")
        collected["photo_ai_confidence"] = img_res.get("confidence")
        collected["problem_severity_ai"] = img_res.get("severity")
        
        escalate = img_res.get("needs_human", False) or img_res.get("confidence", 1.0) < 0.6
        collected["escalated_to_human"] = escalate
        if escalate:
            collected["lead_status"] = "escalated"
            collected["next_action"] = "escalate_agronomist"
            await save_farmer_lead(phone, collected)
        
        if img_res.get("confidence", 0.0) >= 0.6:
            collected["problem_summary"] = img_res.get("visible_symptoms_hindi") or img_res.get("problem_category")
        
        user_input = f"[User uploaded an image. analyze_crop_image result: {json.dumps(img_res, ensure_ascii=False)}]"
    elif message.type == "audio":
        transcription = await voice_transcription_service.transcribe_audio(message.media_id, message.type)
        user_input = f"{transcription}"
    else:
        user_input = message.text or ""
        if message.button_payload:
            user_input += f" (Button payload: {message.button_payload})"

    if not user_input:
        return "नमस्ते 🙏 मैं आपकी किस प्रकार सहायता कर सकता हूँ?"

    # LLM extraction call
    profile_status_str = json.dumps(collected, ensure_ascii=False)
    extraction_prompt = EXTRACTION_SYSTEM_PROMPT.format(
        profile_status=profile_status_str,
        user_message=user_input,
        history=history_text
    )
    
    extracted = {}
    try:
        raw_extraction = await ai_provider.complete(
            system=extraction_prompt,
            user=f"Extract from: {user_input}",
            json_mode=True
        )
        cleaned_ext = clean_json_text(raw_extraction)
        extracted = json.loads(cleaned_ext)
    except Exception as e:
        logger.error("Failed to extract fields using LLM", extra={"error": str(e)})

    if is_greeting_message(user_input):
        extracted["is_unclear"] = False

    if is_obviously_in_scope(user_input):
        extracted["is_unclear"] = False
        extracted["out_of_scope_topic"] = None

    # Resolve extracted values
    if extracted.get("name") and not collected.get("name"):
        collected["name"] = extracted["name"].strip()
        
    loc_parts = []
    if extracted.get("village_city"):
        loc_parts.append(extracted["village_city"])
    if extracted.get("state"):
        loc_parts.append(extracted["state"])
    if loc_parts:
        loc_text = ", ".join(loc_parts)
        norm_res = await tool_normalize_location(loc_text)
        if norm_res.get("confident"):
            if norm_res.get("state"):
                collected["state"] = norm_res["state"]
            if norm_res.get("district"):
                collected["district"] = norm_res["district"]
            if extracted.get("village_city"):
                collected["district_raw"] = extracted["village_city"]
        else:
            if extracted.get("village_city"):
                collected["district_raw"] = extracted["village_city"]
                from app.flows.farmer import parse_location
                parsed = await parse_location(extracted["village_city"], [])
                if parsed:
                    collected["district"] = parsed[1]
                else:
                    collected["district"] = extracted["village_city"].title()
            if extracted.get("state"):
                collected["state"] = extracted["state"]

    if extracted.get("land_size") and collected.get("total_land") is None:
        val = parse_land(extracted["land_size"])
        if val is not None:
            collected["total_land"] = val
            
    if extracted.get("water_source") and not collected.get("water_source"):
        collected["water_source"] = extracted["water_source"]
        
    # Resolve extracted crop if present
    new_crop_canonical = None
    if extracted.get("crop"):
        from app.data.crop_synonyms import resolve_crop
        new_crop_canonical = resolve_crop(extracted["crop"])
        if not new_crop_canonical:
            matched_crop_row = await find_crop_by_name(extracted["crop"])
            if matched_crop_row:
                new_crop_canonical = CANONICAL_PRODUCT_CROP_MAP.get(
                    matched_crop_row.crop_name_en, matched_crop_row.crop_name_en
                )
            else:
                new_crop_canonical = extracted["crop"]

    # Check if a new crop or problem is introduced (especially post-recommendation / STEP 8)
    is_new_crop = new_crop_canonical and collected.get("crop") and new_crop_canonical.lower() != collected.get("crop").lower()
    is_new_problem = extracted.get("problem") and collected.get("recommended") and extracted["problem"] != collected.get("problem_summary")
    
    if is_new_crop or is_new_problem:
        # Start a fresh mini-cycle for the new crop/problem post-recommendation
        collected["recommended"] = False
        collected["asked_followup"] = False
        collected["problem_clarified"] = False
        collected.pop("last_recommended_ids", None)
        collected["escalated_to_human"] = False
        collected.pop("photo_url", None)
        collected.pop("photo_ai_diagnosis", None)
        collected.pop("photo_ai_confidence", None)
        collected.pop("problem_severity_ai", None)
        
        if is_new_crop:
            collected["crop"] = new_crop_canonical
            collected.pop("all_recommended_ids", None)
            if extracted.get("problem"):
                collected["problem_summary"] = extracted["problem"]
            else:
                collected["problem_summary"] = None
        else: # is_new_problem
            collected["problem_summary"] = extracted["problem"]
    else:
        # Standard resolution (first time setting crop or problem)
        if new_crop_canonical and not collected.get("crop"):
            collected["crop"] = new_crop_canonical
        if extracted.get("problem") and not collected.get("problem_summary"):
            collected["problem_summary"] = extracted["problem"]

    # State machine routing
    current_step = None
    step_instruction = ""
    
    if not collected.get("greeted"):
        current_step = "STEP_0"
        step_instruction = "Send a short warm welcome and briefly introduce Vigour Seeds as a trusted seed company that helps farmers get healthy crops and good yield (1-2 lines, simple Hindi, no marketing fluff), then ask for their name."
        collected["greeted"] = True
    elif not collected.get("name"):
        current_step = "STEP_1"
        step_instruction = "Politely ask for the farmer's name in simple Hindi (using trusted village advisor tone)."
    elif not collected.get("state") or not collected.get("district"):
        if collected.get("district") and not collected.get("state"):
            if not collected.get("asked_state_once"):
                current_step = "STEP_2_STATE_ONLY"
                step_instruction = f"The farmer provided the village/city as '{collected.get('district_raw') or collected.get('district')}', but the state (राज्य) is missing. Ask them politely to specify which state (राज्य) they are from."
                collected["asked_state_once"] = True
            else:
                collected["state"] = "Madhya Pradesh"
                
        if not collected.get("state") or not collected.get("district"):
            current_step = "STEP_2"
            step_instruction = "Ask the farmer which village/city AND state (राज्य) they are from. Ask for the state explicitly. Example: 'आप किस गाँव/शहर से हैं, और कौन से राज्य से? (जैसे: नरसिंहपुर, मध्य प्रदेश)'"
            
    if current_step is None and collected.get("total_land") is None:
        current_step = "STEP_3"
        step_instruction = "Ask how much agricultural land they have (एकड़/बीघा)."
        
    if current_step is None and not collected.get("water_source"):
        current_step = "STEP_4"
        step_instruction = "Ask what their water/irrigation source is. Give natural examples in the question (like tube-well, well, pond, canal, river, or rainfed water) instead of buttons. Example: 'आपके खेत में पानी कहाँ से आता है? ट्यूबवेल, कुआँ, तालाब, नहर, नदी, या बारिश का पानी?'"
        
    if current_step is None and not collected.get("crop"):
        current_step = "STEP_5"
        step_instruction = "Ask which crop they are currently growing."
        
    if current_step is None and not collected.get("problem_summary"):
        current_step = "STEP_6"
        step_instruction = "Ask what problem the crop is facing in their own words. Mention they can also send a photo of the crop."
        
    if current_step is None:
        if not collected.get("recommended"):
            current_step = "STEP_7"
        else:
            if not collected.get("asked_followup"):
                current_step = "STEP_8"
            else:
                current_step = "STEP_ADVISOR"

    reply_message = ""
    last_bot_q = collected.get("last_bot_question") or ""
    
    # Intercept list-products query
    if is_list_products_request(user_input):
        crop = collected.get("crop")
        if not crop:
            reply_message = "आप किस फसल के बीजों/उत्पादों के बारे में जानना चाहते हैं? (जैसे: सोयाबीन, धान, मक्का)"
        else:
            products = await tool_find_products(crop, "-", phone)
            dealer_info = await tool_find_dealer(collected.get("state"), collected.get("district"))
            reply_message = format_product_list_response(collected.get("name"), crop, products, dealer_info)
            collected["recommended"] = True
            collected["asked_followup"] = True
            all_recs = collected.get("all_recommended_ids", [])
            for p in products:
                if p["variety_name"] not in all_recs:
                    all_recs.append(p["variety_name"])
            collected["all_recommended_ids"] = all_recs
            collected["last_recommended_ids"] = [p["variety_name"] for p in products]
            try:
                await save_lead_if_complete(phone, collected)
            except Exception as save_err:
                logger.error("Failed saving lead during list product interception", extra={"phone": phone, "error": str(save_err)})
    else:
        unclear_reply = None
        if current_step in ["STEP_6", "STEP_7", "STEP_8", "STEP_ADVISOR"]:
            if is_obviously_in_scope(user_input):
                if extracted.get("asks_chemical_dosage"):
                    unclear_reply = handle_unclear_or_out_of_scope(extracted, collected, last_bot_q)
                else:
                    unclear_reply = None
            else:
                unclear_reply = handle_unclear_or_out_of_scope(extracted, collected, last_bot_q)
        
        # 0. Check for short/acknowledgement/help queries first
        short_reply = None
        if not unclear_reply:
            if collected.get("recommended"):
                short_reply = detect_and_handle_short_or_help(user_input, collected.get("name"), last_bot_q)
            else:
                # Check for open help queries globally
                clean_input = user_input.strip().lower()
                help_queries = [
                    "aur kya kya help", "aur kya help", "what can you do", "kya help", "kya madad", 
                    "क्या मदद", "क्या सहायता", "क्या काम", "क्या कर सकते", "madad kya", "help kya",
                    "और क्या कर सकते", "और क्या मदद", "kya jankari", "aur kya jankari", "क्या जानकारी", "और क्या जानकारी"
                ]
                if any(q in clean_input for q in help_queries):
                    short_reply = detect_and_handle_short_or_help(user_input, collected.get("name"), last_bot_q)

        if unclear_reply:
            reply_message = unclear_reply
        elif short_reply:
            reply_message = short_reply
        else:
            if current_step == "STEP_7":
                if not collected.get("problem_clarified"):
                    prob_summary = collected.get("problem_summary")
                    if is_empty_or_placeholder_problem(prob_summary):
                        prob_summary = "समस्या"
                    clarify_prompt = CLARIFY_PROBLEM_SYSTEM_PROMPT.format(
                        farmer_name=get_clean_farmer_name(collected.get("name")),
                        crop=collected.get("crop"),
                        problem=prob_summary
                    )
                    reply_message = await ai_provider.complete(
                        system=clarify_prompt,
                        user=user_input
                    )
                    collected["problem_clarified"] = True
                else:
                    products = await tool_find_products(collected["crop"], collected["problem_summary"], phone)
                    dealer_info = await tool_find_dealer(collected.get("state"), collected.get("district"))
                    dealer_data_str = json.dumps(dealer_info, ensure_ascii=False)
                    already_recommended_list = collected.get("all_recommended_ids", [])
                    
                    prob_summary = collected.get("problem_summary")
                    if is_empty_or_placeholder_problem(prob_summary):
                        prob_summary = "समस्या"
                    
                    if len(products) == 0:
                        no_prod_prompt = NO_PRODUCT_SYSTEM_PROMPT.format(
                            farmer_name=get_clean_farmer_name(collected.get("name")),
                            crop=collected.get("crop"),
                            problem=prob_summary,
                            dealer_data=dealer_data_str
                        )
                        reply_message = await ai_provider.complete(
                            system=no_prod_prompt,
                            user=f"Explain no products available for: {collected.get('crop')}"
                        )
                    else:
                        products_data_str = json.dumps(products, ensure_ascii=False)
                        recommend_prompt = RECOMMENDATION_SYSTEM_PROMPT.format(
                            farmer_name=get_clean_farmer_name(collected.get("name")),
                            state=collected.get("state"),
                            district=collected.get("district"),
                            crop=collected.get("crop"),
                            problem=prob_summary,
                            products_data=products_data_str,
                            dealer_data=dealer_data_str,
                            already_recommended=json.dumps(already_recommended_list, ensure_ascii=False)
                        )
                        
                        # Retry loop with no-invent guard
                        max_retries = 3
                        user_msg = f"Recommend for: {collected.get('crop')}, {prob_summary}"
                        for attempt in range(max_retries):
                            reply_message = await ai_provider.complete(
                                system=recommend_prompt,
                                user=user_msg
                            )
                            if not check_for_fabricated_products(reply_message, products):
                                break
                            logger.warning(f"Fabricated product name detected (attempt {attempt + 1}). Retrying...")
                            user_msg = (
                                f"Recommend for: {collected.get('crop')}, {prob_summary}. "
                                f"IMPORTANT: You generated a fabricated product name. Do NOT invent or mention any product names "
                                f"other than {', '.join([p['variety_name'] for p in products])}."
                            )

                    collected["recommended"] = True
                    collected["asked_followup"] = True
                    collected["last_recommended_ids"] = [p["variety_name"] for p in products]
                    
                    all_recs = collected.get("all_recommended_ids", [])
                    for p in products:
                        if p["variety_name"] not in all_recs:
                            all_recs.append(p["variety_name"])
                    collected["all_recommended_ids"] = all_recs
                    
                    try:
                        await save_lead_if_complete(phone, collected)
                    except Exception as save_err:
                        logger.error("Failed saving lead during recommendation", extra={"phone": phone, "error": str(save_err)})
                        
            elif current_step == "STEP_8":
                dealer_info = await tool_find_dealer(collected.get("state"), collected.get("district"))
                dealer_data_str = json.dumps(dealer_info, ensure_ascii=False)
                followup_prompt = FOLLOWUP_SYSTEM_PROMPT.format(
                    farmer_name=get_clean_farmer_name(collected.get("name")),
                    dealer_data=dealer_data_str
                )
                reply_message = await ai_provider.complete(
                    system=followup_prompt,
                    user="Continue the conversation naturally and share dealer info if available"
                )
                collected["asked_followup"] = True
                
            elif current_step == "STEP_ADVISOR":
                dealer_info = await tool_find_dealer(collected.get("state"), collected.get("district"))
                dealer_data_str = json.dumps(dealer_info, ensure_ascii=False)
                prob_summary = collected.get("problem_summary")
                if is_empty_or_placeholder_problem(prob_summary):
                    prob_summary = "समस्या"
                advisor_prompt = ADVISOR_SYSTEM_PROMPT.format(
                    farmer_name=get_clean_farmer_name(collected.get("name")),
                    dealer_data=dealer_data_str,
                    crop=collected.get("crop"),
                    problem=prob_summary,
                    already_recommended=json.dumps(collected.get("all_recommended_ids", []), ensure_ascii=False)
                )
                reply_message = await ai_provider.complete(
                    system=advisor_prompt,
                    user=user_input
                )
                
            else:
                phrasing_prompt = PHRASING_SYSTEM_PROMPT.format(
                    farmer_name=get_clean_farmer_name(collected.get("name")),
                    user_message=user_input,
                    step_instruction=step_instruction,
                    profile_context=json.dumps(collected, ensure_ascii=False),
                    last_bot_question=last_bot_q
                )
                reply_message = await ai_provider.complete(
                    system=phrasing_prompt,
                    user=user_input or "Phrase the question for the farmer."
                )

    # Hard Similarity-based No-Repeat Guard
    history_sent = collected.get("sent_messages_history", [])
    last_3_sent = history_sent[-3:] if history_sent else []
    
    def get_similarity(s1: str, s2: str) -> float:
        from difflib import SequenceMatcher
        import re
        clean1 = re.sub(r"[,\-\s\(\)\.\?।!]+", "", s1.lower())
        clean2 = re.sub(r"[,\-\s\(\)\.\?।!]+", "", s2.lower())
        if not clean1 and not clean2:
            return 1.0
        if not clean1 or not clean2:
            return 0.0
        return SequenceMatcher(None, clean1, clean2).ratio()

    def has_same_first_line(s1: str, s2: str) -> bool:
        import re
        lines1 = [re.sub(r"[,\-\s\(\)\.\?।!]+", "", l.lower()) for l in s1.split("\n") if l.strip()]
        lines2 = [re.sub(r"[,\-\s\(\)\.\?•\*_]+", "", l.lower()) for l in s2.split("\n") if l.strip()]
        if lines1 and lines2:
            return lines1[0] == lines2[0]
        return False

    def is_near_duplicate(msg: str) -> bool:
        for old in last_3_sent:
            if get_similarity(msg, old) > 0.85:
                return True
            if has_same_first_line(msg, old):
                return True
        return False

    if is_near_duplicate(reply_message):
        logger.warning(f"Near-duplicate reply detected. Attempting to generate a different response...")
        for attempt in range(2):
            try:
                # Ask LLM to generate a different response / ask clarifying question differently / move forward
                retry_prompt = f"""आप "Vigour मित्र" हैं। (Rephrase prompt)
आप पहले ही किसान भाई को ये संदेश भेज चुके हैं: {[l[:30]+'...' for l in last_3_sent]}।
आपकी वर्तमान प्रतिक्रिया '{reply_message}' पहले भेजे गए संदेशों से अत्यधिक मिलती-जुलती है।
कृपया बिल्कुल अलग प्रतिक्रिया (शब्द और संदर्भ दोनों में) ग्रामीण हिंदी में जनरेट करें।
यदि सलाह पहले ही दी जा चुकी है, तो आप फसल की सिंचाई, मिट्टी की स्थिति या हाल के मौसम के बारे में सवाल पूछ सकते हैं या बातचीत को प्यार से समाप्त कर सकते हैं।
केवल किसान को भेजे जाने वाला शुद्ध संदेश लिखें (बिना किसी markdown के)।"""
                rephrased = await ai_provider.complete(
                    system=retry_prompt,
                    user=f"Generate a different response than: {reply_message}"
                )
                if not is_near_duplicate(rephrased):
                    reply_message = rephrased
                    break
            except Exception as rephrase_err:
                logger.error("Failed to generate non-duplicate rephrased message", extra={"error": str(rephrase_err)})

    history_sent.append(reply_message)
    if len(history_sent) > 5:
        history_sent = history_sent[-5:]
    collected["sent_messages_history"] = history_sent
    collected["last_bot_question"] = reply_message

    await sessions_repo.upsert(phone, {"collected_json": collected})
    return reply_message

async def respond(phone: str, message: NormalizedMessage) -> str:
    if message.text and message.text.strip().lower() == "/reset":
        await sessions_repo.delete(phone)
        from app.db.repositories.conversations import conversations_repo
        await conversations_repo.delete(phone)
        return "बातचीत रीसेट हो गई। नमस्ते!"

    # Cheap off-topic precheck (no LLM call)
    if message.text and check_obviously_off_topic(message.text):
        logger.info("Message intercepted by cheap off-topic pre-check", extra={"phone": phone, "user_msg": message.text})
        return "माफ़ कीजिए किसान भाई, मैं सिर्फ खेती, फसल, बीज, खाद, कीड़े-बीमारी और Vigour उत्पादों से जुड़े सवालों में मदद कर सकता हूँ। आपकी फसल से जुड़ी कोई बात हो तो ज़रूर पूछिए।"

    distributor = await distributors_repo.get_active_by_phone(phone)
    if distributor:
        return await run_distributor_agent_loop(phone, message, distributor)
    elif phone.startswith("919000000"):
        return await run_farmer_state_machine(phone, message)
    else:
        return await run_agent(phone, message)

# Startup logging to verify configuration is active
try:
    first_line_prompt = AGENT_SYSTEM_PROMPT.strip().split("\n")[0]
    provider_name = getattr(ai_provider, "provider", "unknown")
    model_name = "unknown"
    if provider_name == "openai":
        from app.core.config import settings
        model_name = settings.OPENAI_MODEL or "gpt-4o-mini"
    elif provider_name == "gemini":
        model_name = "gemini-2.5-flash"
    elif provider_name == "claude":
        model_name = "claude-3-5-sonnet-latest"
        
    logger.info(
        "Conversational Agent initialized successfully",
        extra={
            "prompt_first_line": first_line_prompt,
            "provider": provider_name,
            "model": model_name
        }
    )
    print(f"[{datetime.now().isoformat()}] CONVERSATIONAL AGENT STARTUP:")
    print(f"  Prompt first line: {first_line_prompt}")
    print(f"  Provider: {provider_name}")
    print(f"  Model: {model_name}")
except Exception as startup_err:
    logger.error("Failed to log agent startup info", extra={"error": str(startup_err)})
