# crop_synonyms.py
# Maps any Hindi / Hinglish / English / regional crop term a farmer might type
# to the EXACT crop string used in the Supabase products table (Product_Master.crop).
#
# WHY: Farmers type "makka", "मक्का", "dhan", "mirchi", "soyabean" etc., but the products
# table stores crops in English ("Maize", "Paddy", "Hot Pepper (Chilli)", "Soybean").
# Without this bridge, find_products finds nothing and the bot wrongly says
# "कोई प्रोडक्ट उपलब्ध नहीं". This map fixes that for ALL crops, not just maize.
#
# USAGE in find_products (before querying Supabase):
#   from app.data.crop_synonyms import resolve_crop
#   canonical = resolve_crop(user_crop_text)   # -> exact products.crop value, or None
#   if canonical: query products where crop == canonical and approved_for_recommendation == 'Y'
#
# resolve_crop():
#   - lowercases, strips, removes extra spaces/punctuation
#   - matches against all known synonyms (Hindi, Hinglish, English)
#   - returns the EXACT Product_Master crop string (right-hand side) or None if unknown
#
# NOTE: The RIGHT-HAND values below are the EXACT crop strings in the products table.
# Do not change them — they must match the DB verbatim.

# canonical product-table crop string -> list of accepted synonyms (any script/spelling)
_CROP_SYNONYMS = {
    "Soybean": ["soybean", "soyabean", "soya", "soya bean", "सोयाबीन", "सोया"],
    "Maize": ["maize", "corn", "makka", "makkah", "maka", "मक्का", "मकई", "भुट्टा", "bhutta"],
    "Paddy": ["paddy", "rice", "dhan", "dhaan", "chawal", "chaval", "धान", "चावल", "धान/चावल"],
    "Wheat": ["wheat", "gehu", "gehun", "gehoo", "गेहूं", "गेहूँ"],
    "Bajra (Pearl Millet)": ["bajra", "pearl millet", "millet", "बाजरा"],
    "Sunflower": ["sunflower", "surajmukhi", "सूरजमुखी"],
    "Chickpea (Chana)": ["chickpea", "chana", "channa", "gram", "चना"],
    "Tur (Arhar)": ["tur", "arhar", "toor", "pigeon pea", "अरहर", "तुर", "तूर"],
    "Green Gram (Moong)": ["moong", "mung", "green gram", "मूंग", "मूँग"],
    "Black Gram (Urad)": ["urad", "udad", "black gram", "उड़द", "उरद"],
    "Mustard": ["mustard", "sarson", "sarso", "raai", "rai", "सरसों"],
    "Sorghum (Jowar)": ["sorghum", "jowar", "juar", "ज्वार", "जोवार"],
    "Cumin/Sesame": ["cumin", "jeera", "zeera", "जीरा", "sesame", "til", "तिल"],
    "Okra": ["okra", "bhindi", "bhendi", "lady finger", "ladyfinger", "भिंडी"],
    "Tomato": ["tomato", "tamatar", "tamaatar", "टमाटर"],
    "Hot Pepper (Chilli)": ["chilli", "chili", "chillies", "mirch", "mirchi", "hot pepper",
                            "मिर्च", "मिर्ची", "लाल मिर्च", "hari mirch", "हरी मिर्च"],
    "Brinjal": ["brinjal", "baingan", "bengan", "eggplant", "बैंगन"],
    "Bitter Gourd": ["bitter gourd", "karela", "करेला"],
    "Bottle Gourd": ["bottle gourd", "lauki", "ghiya", "लौकी"],
    "Ridge Gourd": ["ridge gourd", "turai", "tori", "तुरई", "तोरी"],
    "Sponge Gourd": ["sponge gourd", "gilki", "nenua", "गिल्की"],
    "Watermelon": ["watermelon", "tarbooj", "tarbuj", "तरबूज"],
    "Muskmelon": ["muskmelon", "kharbuja", "kharbooja", "खरबूजा", "खरबूज"],
    "Cucumber": ["cucumber", "kheera", "khira", "खीरा", "ककड़ी", "kakdi"],
    "Cauliflower": ["cauliflower", "phool gobhi", "phoolgobhi", "gobhi", "फूलगोभी", "फूल गोभी"],
    "Cabbage": ["cabbage", "patta gobhi", "pattagobhi", "बंद गोभी", "पत्ता गोभी"],
    "Pumpkin": ["pumpkin", "kaddu", "kohla", "कद्दू"],
    "Capsicum": ["capsicum", "shimla mirch", "shimla mirchi", "bell pepper", "शिमला मिर्च"],
    "Onion": ["onion", "pyaz", "pyaaz", "kanda", "प्याज", "प्याज़"],
    "Radish": ["radish", "mooli", "muli", "मूली"],
    "Beans": ["beans", "bean", "sem", "फलियां", "बीन्स", "सेम"],
    "Sweet Corn / Peas / Gawar": ["sweet corn", "sweetcorn", "meethi makka", "peas", "matar",
                                  "मटर", "gawar", "guar", "ग्वार", "मीठी मक्का"],
    "Coriander / Spinach / Methi": ["coriander", "dhania", "धनिया", "spinach", "palak", "पालक",
                                    "methi", "मेथी"],
}

# Build reverse lookup: synonym (normalized) -> canonical crop string
def _normalize(text: str) -> str:
    if not text:
        return ""
    t = str(text).strip().lower()
    # collapse whitespace and strip common punctuation
    for ch in [".", ",", "-", "_", "/", "(", ")"]:
        t = t.replace(ch, " ")
    t = " ".join(t.split())
    return t

_LOOKUP = {}
for canonical, syns in _CROP_SYNONYMS.items():
    _LOOKUP[_normalize(canonical)] = canonical
    for s in syns:
        _LOOKUP[_normalize(s)] = canonical


def resolve_crop(user_text: str):
    """Return the exact Product_Master crop string for a user's crop term, or None.

    Handles bare terms ("makka"), sentences ("meri makke ki fasal"), and light
    morphology ("makka"/"makke") via prefix matching on tokens.
    """
    norm = _normalize(user_text)
    if not norm:
        return None
    # 1) direct full-string match
    if norm in _LOOKUP:
        return _LOOKUP[norm]
    # 2) multi-word synonym appears inside the sentence
    for syn, canonical in _LOOKUP.items():
        if " " in syn and syn in norm:
            return canonical
    # 3) per-token exact match
    tokens = norm.split()
    for tok in tokens:
        if tok in _LOOKUP:
            return _LOOKUP[tok]
    # 4) per-token light morphology: token shares a 4+ char prefix with a known synonym
    #    (covers makka/makke, mirch/mirchi, tamatar/tamaatar, etc.)
    single_syns = [(s, c) for s, c in _LOOKUP.items() if " " not in s and len(s) >= 4]
    for tok in tokens:
        if len(tok) < 4:
            continue
        for syn, canonical in single_syns:
            n = min(len(tok), len(syn))
            if n >= 4 and tok[:4] == syn[:4]:
                return canonical
    return None


# Quick self-test
if __name__ == "__main__":
    tests = ["Makka", "मक्का", "makke me keede", "soyabean", "dhan", "mirchi",
             "gehu", "meri tamatar ki fasal", "sarson", "bhindi", "unknownxyz"]
    for t in tests:
        print(f"{t!r:35} -> {resolve_crop(t)}")
