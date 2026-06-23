# location_helper.py
# Helper module to map bare Indian cities/metros directly to their corresponding states
# without requiring the state to be explicitly typed by the farmer.

CITY_TO_STATE_MAP = {
    # Madhya Pradesh
    "bhopal": ("Madhya Pradesh", "Bhopal"),
    "भोपाल": ("Madhya Pradesh", "Bhopal"),
    "indore": ("Madhya Pradesh", "Indore"),
    "इन्दौर": ("Madhya Pradesh", "Indore"),
    "इंदौर": ("Madhya Pradesh", "Indore"),
    "ujjain": ("Madhya Pradesh", "Ujjain"),
    "उज्जैन": ("Madhya Pradesh", "Ujjain"),
    "gwalior": ("Madhya Pradesh", "Gwalior"),
    "ग्वालियर": ("Madhya Pradesh", "Gwalior"),
    "jabalpur": ("Madhya Pradesh", "Jabalpur"),
    "जबलपुर": ("Madhya Pradesh", "Jabalpur"),
    "sagar": ("Madhya Pradesh", "Sagar"),
    "सागर": ("Madhya Pradesh", "Sagar"),
    "ratlam": ("Madhya Pradesh", "Ratlam"),
    "रतलाम": ("Madhya Pradesh", "Ratlam"),
    "rewa": ("Madhya Pradesh", "Rewa"),
    "रीवा": ("Madhya Pradesh", "Rewa"),
    "satna": ("Madhya Pradesh", "Satna"),
    "सतना": ("Madhya Pradesh", "Satna"),
    "dewas": ("Madhya Pradesh", "Dewas"),
    "देवास": ("Madhya Pradesh", "Dewas"),
    "vidisha": ("Madhya Pradesh", "Vidisha"),
    "विदिशा": ("Madhya Pradesh", "Vidisha"),
    "guna": ("Madhya Pradesh", "Guna"),
    "गुना": ("Madhya Pradesh", "Guna"),
    "sehore": ("Madhya Pradesh", "Sehore"),
    "सीहोर": ("Madhya Pradesh", "Sehore"),
    "hoshangabad": ("Madhya Pradesh", "Hoshangabad"),
    "होशंगाबाद": ("Madhya Pradesh", "Hoshangabad"),
    "narmadapuram": ("Madhya Pradesh", "Hoshangabad"),
    "नर्मदापुरम": ("Madhya Pradesh", "Hoshangabad"),
    "khandwa": ("Madhya Pradesh", "Khandwa"),
    "खंडवा": ("Madhya Pradesh", "Khandwa"),
    "खण्डवा": ("Madhya Pradesh", "Khandwa"),
    "khargone": ("Madhya Pradesh", "Khargone"),
    "खरगोन": ("Madhya Pradesh", "Khargone"),
    "chhindwara": ("Madhya Pradesh", "Chhindwara"),
    "छिंदवाड़ा": ("Madhya Pradesh", "Chhindwara"),
    "छिन्दवाड़ा": ("Madhya Pradesh", "Chhindwara"),
    "betul": ("Madhya Pradesh", "Betul"),
    "बैतुल": ("Madhya Pradesh", "Betul"),
    "बैतूल": ("Madhya Pradesh", "Betul"),
    "shivpuri": ("Madhya Pradesh", "Shivpuri"),
    "शिवपुरी": ("Madhya Pradesh", "Shivpuri"),
    "morena": ("Madhya Pradesh", "Morena"),
    "मुरैना": ("Madhya Pradesh", "Morena"),
    "datia": ("Madhya Pradesh", "Datia"),
    "दतिया": ("Madhya Pradesh", "Datia"),
    "mandsaur": ("Madhya Pradesh", "Mandsaur"),
    "मंदसौर": ("Madhya Pradesh", "Mandsaur"),
    "neemuch": ("Madhya Pradesh", "Neemuch"),
    "नीमच": ("Madhya Pradesh", "Neemuch"),
    "dhar": ("Madhya Pradesh", "Dhar"),
    "धार": ("Madhya Pradesh", "Dhar"),
    "burhanpur": ("Madhya Pradesh", "Burhanpur"),
    "बुरहानपुर": ("Madhya Pradesh", "Burhanpur"),
    "katni": ("Madhya Pradesh", "Katni"),
    "कटनी": ("Madhya Pradesh", "Katni"),
    "singrauli": ("Madhya Pradesh", "Singrauli"),
    "सिंगरौली": ("Madhya Pradesh", "Singrauli"),

    # Maharashtra
    "mumbai": ("Maharashtra", "Mumbai"),
    "मुंबई": ("Maharashtra", "Mumbai"),
    "मम्बई": ("Maharashtra", "Mumbai"),
    "pune": ("Maharashtra", "Pune"),
    "पुणे": ("Maharashtra", "Pune"),
    "पुना": ("Maharashtra", "Pune"),
    "nagpur": ("Maharashtra", "Nagpur"),
    "नागपुर": ("Maharashtra", "Nagpur"),
    "नागपूर": ("Maharashtra", "Nagpur"),

    # Rajasthan
    "jaipur": ("Rajasthan", "Jaipur"),
    "जयपुर": ("Rajasthan", "Jaipur"),
    "kota": ("Rajasthan", "Kota"),
    "कोटा": ("Rajasthan", "Kota")
}

def resolve_bare_city(text: str) -> tuple[str, str, str] | None:
    """Check if the text contains a bare city name and resolve its state/district.
    Returns (state, district_normalized, district_raw) or None.
    """
    if not text:
        return None
    
    cleaned = text.lower().strip()
    
    # collapse spaces/punctuation
    for ch in [".", ",", "-", "_", "/", "(", ")", "।"]:
        cleaned = cleaned.replace(ch, " ")
        
    words = cleaned.split()
    matched = None
    matched_word = None
    for w in words:
        if w in CITY_TO_STATE_MAP:
            matched = CITY_TO_STATE_MAP[w]
            matched_word = w
            break
            
    if matched:
        state, district = matched
        
        # Check if the input mentions any OTHER state name to avoid false positives
        state_names = {
            "madhya pradesh": ["madhya pradesh", "madhyapradesh", "mp", "मप्र", "मध्य प्रदेश", "मध्यप्रदेश"],
            "maharashtra": ["maharashtra", "mh", "महाराष्ट्र"],
            "rajasthan": ["rajasthan", "rj", "राजस्थान"],
            "gujarat": ["gujarat", "gj", "गुजरात"],
            "uttar pradesh": ["uttar pradesh", "up", "उत्तर प्रदेश", "उत्तरप्रदेश"],
            "chhattisgarh": ["chhattisgarh", "cg", "छत्तीसगढ़", "छत्तीसगढ"],
            "karnataka": ["karnataka", "कर्नाटक"],
            "andhra pradesh": ["andhra pradesh", "ap", "आंध्र प्रदेश", "आंध्रप्रदेश"],
            "telangana": ["telangana", "तेलंगाना"],
            "bihar": ["bihar", "बिहार"],
            "odisha": ["odisha", "orissa", "ओडिशा", "उड़ीसा"],
            "punjab": ["punjab", "pb", "पंजाब"],
            "haryana": ["haryana", "hr", "हरियाणा"],
            "tamil nadu": ["tamil nadu", "tn", "तमिलनाडु"],
            "west bengal": ["west bengal", "wb", "पश्चिम बंगाल", "पश्चिमबंगाल"]
        }
        
        for other_state, synonyms in state_names.items():
            if other_state != state.lower():
                for syn in synonyms:
                    if syn in cleaned:
                        # Conflict! User explicitly mentioned another state
                        return None
                        
        return state, district, matched_word
        
    return None
