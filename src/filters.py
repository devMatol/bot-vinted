import logging
import re
import unicodedata
from typing import Dict, Any, Tuple, List, Optional

from src.i18n_keywords import (
    CHILD_KEYWORDS,
    CHILD_BRANDS,
    CHILD_SIZE_REGEX,
    JUNK_KEYWORDS,
    TOILETRY_KEYWORDS,
    BOUTIQUE_PACKAGING_KEYWORDS,
    BASIC_ITEMS_KEYWORDS,
    FAKE_MARKERS,
    SATISFACTORY_STATUS_MARKERS,
    GENDER_KEYWORDS_MEN,
    GENDER_KEYWORDS_WOMEN,
    FEMALE_ONLY_PIECES
)

logger = logging.getLogger("VintedBot.Filters")

FAST_FASHION_BRANDS = {
    "zara", "h&m", "hm", "shein", "bershka", "stradivarius", "primark", "mango", "mng",
    "pull&bear", "pull and bear", "boohoo", "asos", "kiabi", "jennyfer", "pimkie", "c&a",
    "promod", "cache cache", "armand thiery", "armand thierry", "celio", "jules", "brice",
    "devred", "undiz", "etam", "naf naf", "morgan", "camaieu", "mim", "la halle", "gémo",
    "gemo", "in extenso", "tex", "bizzbee", "bonobo", "kaporal", "prettylittlething",
    "missguided", "forever 21", "nasty gal", "monki", "weekday", "new look", "daniel hechter",
    "cerruti", "cerruti 1881", "geox", "gap", "levi's", "levis"
}

ACCESSORY_TITLE_KEYWORDS = [
    # FR
    "sac", "sacs", "sac a dos", "sacoche", "pochette", "cabas", "besace", "banane", "portefeuille",
    "porte-monnaie", "porte monnaie", "porte-cartes", "ceinture", "ceintures", "cravate", "cravates",
    "noeud papillon", "lunettes", "echarpe", "echarpes", "etole", "chale", "casquette", "bob", "chapeau",
    "beret", "gants", "bijou", "bijoux", "collier", "bracelet", "bague", "boucles d'oreilles", "broche",
    "montre", "porte-cle", "porte-cles", "pochon", "dustbag", "dust bag", "trousse",
    # IT
    "borsa", "borse", "borsetta", "borsello", "zaino", "portafoglio", "cravatta", "cravatte", "occhiali",
    "occhiale", "sciarpa", "cappello", "berretto", "guanti", "collana", "bracciale", "anello", "orecchini",
    "sacchetto", "cinture",
    # ES
    "bolso", "bolsos", "bolsa", "mochila", "cartera", "cinturon", "corbata", "gafas", "bufanda", "panuelo",
    "gorra", "sombrero", "collar", "pulsera", "anillo", "pendientes", "rinonera",
    # DE
    "tasche", "handtasche", "rucksack", "geldborse", "portemonnaie", "gurtel", "guertel", "krawatte",
    "brille", "sonnenbrille", "schal", "mutze", "halskette", "armband",
    # NL
    "tas", "tasje", "rugzak", "portemonnee", "riem", "stropdas", "bril", "zonnebril", "sjaal", "hoed", "ketting",
    # PT
    "carteira", "cinto", "gravata", "oculos", "cachecol", "lenco", "chapeu", "colar", "pulseira", "brincos",
    # EN
    "bag", "handbag", "backpack", "wallet", "purse", "belt", "sunglasses", "glasses", "scarf", "hat",
    "beanie", "necklace", "earrings", "keychain", "clutch", "tote",
    # Petits objets validés à tort la nuit du 19/10
    "pouch", "housse", "chouchou", "fermacoda", "elastico capelli", "calze", "chaussettes", "socks",
    "calcetines", "socken", "orologio", "reloj", "uhr", "watch", "porte monnaie", "cravatte",
]

# Sacs : réautorisés par "allow_bags": true dans une recherche (les pochons, trousses et housses restent exclus)
BAG_TITLE_KEYWORDS = {
    "sac", "sacs", "sac a dos", "sacoche", "pochette", "cabas", "besace", "banane",
    "borsa", "borse", "borsetta", "borsello", "zaino", "bolso", "bolsos", "bolsa", "mochila",
    "tasche", "handtasche", "rucksack", "tas", "tasje", "rugzak",
    "bag", "handbag", "backpack", "purse", "clutch", "tote",
}

# Si le titre nomme un vêtement ("jupe à ceinture", "robe avec foulard"), on n'applique pas l'exclusion accessoire
CLOTHING_TITLE_KEYWORDS = [
    "jupe", "robe", "jeans", "pantalon", "top", "chemise", "chemisier", "blouse", "veste", "blazer",
    "manteau", "pull", "gilet", "t-shirt", "tee", "debardeur", "short", "combinaison", "body", "corset", "sweat",
    "gonna", "abito", "vestito", "pantaloni", "camicia", "giacca", "maglia", "maglione", "felpa", "cappotto",
    "falda", "vestido", "camisa", "chaqueta", "abrigo", "jersey", "camiseta",
    "rock", "kleid", "hose", "jacke", "mantel", "pullover", "bluse", "hemd",
    "rok", "jurk", "broek", "jas", "trui",
    "skirt", "dress", "pants", "trousers", "shirt", "jacket", "coat", "sweater", "jumper", "hoodie",
]

BEAUTY_TITLE_KEYWORDS = [
    "parfum", "parfums", "perfume", "profumo", "fragrance", "eau de toilette", "eau de parfum", "edt", "edp",
    "coffret", "make-up", "makeup", "maquillage", "rouge a levres", "vernis", "cosmetique", "beauty",
    "duftwasser", "lipstick",
]

GENERIC_BRANDS = {"sans marque", "vintage", "autre", "other", "inconnu", "unbranded", ""}

VINTAGE_SIGNALS = [
    "vintage", "retro", "rétro", "90s", "80s", "70s", "00s", "y2k",
    "90's", "80's", "70's", "anni 90", "anni 80", "anni 70",
    "old school", "oldschool", "old money", "oldmoney", "archive",
    "burberrys", "made in usa", "made in italy", "made in france",
    "années 90", "annees 90", "années 80", "annees 80"
]

def normalize_text(text: str) -> str:
    """Minuscule et suppression des accents (NFKD)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def contains_whole_word(text: str, keyword: str) -> bool:
    """
    Vérifie si le mot-clé apparaît sous forme de mot entier dans le texte.
    Insensible à la casse et aux accents (Phase 2.3).
    Ex: 'cap' ne matchera JAMAIS 'cape' ou 'capuche'.
    'box' ne matchera JAMAIS 'boxy'.
    'cover' ne matchera JAMAIS 'discover'.
    """
    if not text or not keyword:
        return False
    norm_text = normalize_text(text)
    norm_kw = normalize_text(keyword).strip()
    if not norm_kw:
        return False

    pattern = rf'(?<!\w){re.escape(norm_kw)}(?!\w)'
    return bool(re.search(pattern, norm_text))

# Objets, déco, boîtes, cintres, etc. exclus d'office avant tout appel Gemini (Point 2)
NON_CLOTHING_KEYWORDS = [
    # Déco, maison, objets
    "coupe a fruits", "coupe à fruits", "cintre", "cintres", "gruccia", "grucce", "appendino", "appendini",
    "percha", "perchas", "kleiderbugel", "kleiderbügel", "hanger", "hangers",
    "boite", "boîte", "boites", "boîtes", "scatola", "scatole", "caja", "cajas", "box", "boxes", "kiste",
    "livre", "livres", "bouquin", "libro", "libri", "buch", "bücher", "bucher", "book", "books",
    "parfum", "parfums", "profumo", "profumi", "perfume", "perfumes", "fragrance", "flacon",
    "pochette beaute", "pochette beauté", "pochette parfum", "trousse beaute", "trousse beauté",
    "beauty pouch", "beauty bag", "toilet tasje", "toilettas",
    "application", "socle", "stand", "support",
    "vaisselle", "plat", "plats", "assiette", "assiettes", "piatto", "piatti", "plato", "platos", "teller", "plate", "dish",
    "verre", "verres", "bicchiere", "bicchieri", "vaso", "vasos", "glas", "gläser",
    "tasse", "tasses", "mug", "mugs", "tazza", "tazze", "cup", "cups",
    "bougie", "bougies", "candela", "candele", "vela", "velas", "kerze", "kerzen", "candle", "candles",
    "affiche", "poster", "cadre", "cadres", "quadro", "quadri", "marco", "marcos", "rahmen", "frame",
    "figurine", "bibelot", "statue", "statuette", "sculpture",
    "coussin", "coussins", "oreiller", "plaid", "couverture", "cuscino", "cojin", "kissen", "pillow", "blanket",
    "tableau", "peinture", "art",
    "peluche", "peluches", "jouet", "jouets", "jeu", "jeux", "toy", "toys", "giocattolo", "juguete", "stofftier",
    "porte-cles", "porte-cle", "porte cles", "porte cle", "porte-clef", "porte-clefs", "portachiavi", "llavero", "keychain", "keyring",
    "coque", "housse telephone", "phone case", "cendrier", "aschenbecher", "ashtray"
]

CATEGORY_KEYWORDS_MAP = {
    # 1. Bottes (vérifié avant chaussures)
    "bottes": [
        "bottes", "botte", "bottines", "bottine", "cuissardes", "cuissarde",
        "stivali", "stivale", "stivaletti", "stivaletto",
        "botas", "bota", "botines", "botin",
        "stiefel", "stiefeletten", "boots", "boot", "ankle boots", "laarzen", "laarsjes"
    ],
    # 2. Chaussures
    "chaussures": [
        "chaussures", "chaussure", "baskets", "basket", "sneakers", "sneaker", "tennis",
        "mocassins", "mocassin", "escarpins", "escarpin", "sandales", "sandale", "mules", "mule",
        "ballerines", "ballerine", "derbies", "richelieu", "claquettes", "tongs", "talons",
        "scarpe", "scarpa", "sandali", "mocassini", "decollete", "ciabatte",
        "zapatos", "zapato", "zapatillas", "zapatilla", "sandalias", "mocasines", "tacones",
        "schuhe", "schuh", "turnschuhe", "sandalen", "pumps", "loafers", "trainers", "flats",
        "schoenen"
    ],
    # 3. Manteau (vérifié avant veste)
    "manteau": [
        "manteau", "manteaux", "trench", "trenchcoat", "doudoune", "parka", "caban", "pardessus", "anorak",
        "cape", "capes", "poncho", "ponchos",
        "cappotto", "piumino", "giaccone",
        "abrigo", "plumas", "gabardina",
        "mantel", "daunenjacke", "wintermantel", "winterjas",
        "coat", "overcoat", "down jacket", "puffer"
    ],
    # 4. Veste / Blazer
    "veste/blazer": [
        "veste", "vestes", "blazer", "blazers", "blouson", "blousons", "perfecto", "bomber", "tailleur",
        "giacca", "giacche",
        "chaqueta", "chaquetas", "cazadora",
        "jacke", "jacken", "sakko",
        "jasje",
        "jacket", "jackets"
    ],
    # 5. Robe
    "robe": [
        "robe", "robes", "abito", "abiti", "vestito", "vestiti",
        "vestido", "vestidos", "kleid", "kleider", "jurk", "jurken", "dress", "dresses"
    ],
    # 6. Jupe
    "jupe": [
        "jupe", "jupes", "gonna", "gonne", "falda", "faldas",
        "rock", "röcke", "rok", "rokken", "skirt", "skirts"
    ],
    # 7. Jean / Pantalon / Short
    "jean/pantalon/short": [
        "jean", "jeans", "pantalon", "pantalons", "short", "shorts", "bermuda", "bermudas",
        "pantacourt", "cargo", "treillis", "jogging", "joggings", "legging", "leggings",
        "survetement", "survêtement",
        "pantaloni", "pantalone", "calca", "calças", "calcas",
        "pantalones", "vaqueros", "tejanos",
        "hose", "hosen", "broek", "broeken",
        "pants", "trousers", "slacks", "chinos", "joggers", "sweatpants"
    ],
    # 8. Pull / Sweat / Maille
    "pull/sweat/maille": [
        "pull", "pulls", "sweat", "sweats", "sweatshirt", "sweat-shirt", "hoodie", "hoodies",
        "maille", "mailles", "gilet", "gilets", "cardigan", "cardigans", "tricot",
        "maglione", "maglioni", "maglia", "maglie", "felpa", "felpe",
        "jersey", "jerseys", "sudadera", "sudaderas", "sueter",
        "pullover", "pulli", "strickjacke", "strickpullover",
        "trui", "truien", "vest",
        "sweater", "sweaters", "jumper", "jumpers", "knitwear", "knit"
    ],
    # 9. T-shirt / Top / Débardeur (vérifié avant chemise)
    "tshirt/top/debardeur": [
        "t-shirt", "tshirt", "t-shirts", "tshirts", "tee", "tee shirt", "tee-shirt", "tees",
        "top", "tops", "crop top", "crop-top", "debardeur", "débardeur", "debardeurs", "débardeurs",
        "caraco", "camisole",
        "maglietta", "magliette", "canotta", "canotte", "canottiera",
        "camiseta", "camisetas",
        "oberteil", "oberteile", "sommertop", "tanktop", "tank top",
        "tank"
    ],
    # 10. Chemise / Blouse
    "chemise/blouse": [
        "chemise", "chemises", "chemisier", "chemisiers", "blouse", "blouses", "chemisette", "tunique",
        "camicia", "camicie", "camicetta",
        "camisa", "camisas", "blusa", "blusas",
        "hemd", "hemden", "bluse", "blusen",
        "shirt", "shirts", "button up", "button-down"
    ],
    # 11. Sac
    "sac": [
        "sac", "sacs", "sacoche", "sacoches", "pochette", "pochettes", "cabas", "besace", "banane",
        "borsa", "borse", "borsetta", "borsette", "borsello", "zaino",
        "bolso", "bolsos", "bolsa", "bolsas", "mochila",
        "tasche", "taschen", "handtasche", "rucksack",
        "tas", "tasje", "rugzak",
        "bag", "bags", "handbag", "handbags", "purse", "tote", "clutch", "backpack"
    ]
}

DEFAULT_RESALE_CAPS = {
    "tshirt/top/debardeur": 18.0,
    "chemise/blouse": 20.0,
    "pull/sweat/maille": 22.0,
    "robe": 25.0,
    "jupe": 22.0,
    "jean/pantalon/short": 22.0,
    "veste/blazer": 40.0,
    "manteau": 45.0,
    "chaussures": 40.0,
    "bottes": 50.0,
    "sac": 40.0
}

def detect_item_category(title: str) -> Optional[str]:
    """
    Détecte la catégorie de vêtement/accessoire à partir des mots du titre (multilingue).
    Retourne la clé de catégorie normalisée (ex: 'pull/sweat/maille', 'jupe') ou None.
    """
    if not title:
        return None
    for cat_name, keywords in CATEGORY_KEYWORDS_MAP.items():
        for kw in keywords:
            if contains_whole_word(title, kw):
                return cat_name
    return None

def is_clothing_shoes_or_bag(title: str) -> Tuple[bool, str, Optional[str]]:
    """
    Garde-fou indépendant de l'IA (Point 2) :
    1. Rejette les objets non vêtements, déco, boîtes, cintres, livres, parfums, etc.
    2. Vérifie que le titre correspond à une catégorie acceptée (vêtement, chaussures, sac).
    Retourne (est_valide, raison/message, categorie_detectee).
    """
    if not title:
        return False, "Titre vide", None

    # 1. Vérification des objets non vêtements exclus
    for nck in NON_CLOTHING_KEYWORDS:
        if contains_whole_word(title, nck):
            return False, f"Objet non vêtement exclu : '{nck}'", None

    # 2. Détection de catégorie
    cat = detect_item_category(title)
    if not cat:
        return False, "Article non reconnu comme vêtement, chaussures ou sac", None

    return True, f"Catégorie détectée : {cat}", cat

def get_category_cap_and_multiplier(
    title: str,
    brand: str,
    config: Dict[str, Any],
    score: int = 0,
    distinctive_features: Optional[List[str]] = None
) -> Tuple[float, float, float, str]:
    """
    Calcule le plafond de revente et le multiplicateur selon la catégorie et la marque (Point 2) :
    - base_cap : selon config['resale_caps_eur']
    - brand_mult : x1 pour lignes diffusion, x1.5 pour D&G/Mugler/etc., x3 pour Gucci/Prada/etc.
    - score_mult : bonus si distinctive_features non vide et score élevé (x4 si >= 90, x2.5 si >= 75)
    - effective_cap = base_cap * brand_mult * score_mult
    Retourne (base_cap, brand_mult, effective_cap, category).
    """
    cat = detect_item_category(title) or "tshirt/top/debardeur"
    
    # 1. Plafond catégorie
    caps_config = config.get("resale_caps_eur", DEFAULT_RESALE_CAPS)
    base_cap = caps_config.get(cat)
    if base_cap is None:
        for key, val in caps_config.items():
            if cat in key or key in cat:
                base_cap = val
                break
    if base_cap is None:
        base_cap = 20.0

    # 2. Multiplicateur de marque
    norm_brand = normalize_text(f"{brand} {title}").strip()
    brand_tiers = config.get("brand_tiers", {})
    
    tier_3_brands = brand_tiers.get("tier_3", {}).get("brands", [
        "gucci", "prada", "miu miu", "ysl", "saint laurent", "yves saint laurent", "dior", "christian dior", "chanel", "fendi"
    ])
    tier_1_5_brands = brand_tiers.get("tier_1_5", {}).get("brands", [
        "kenzo", "max mara", "mugler", "thierry mugler", "moschino", "d&g",
        "dolce & gabbana", "dolce gabbana", "versace", "roberto cavalli", "cavalli", "burberry", "jean paul gaultier"
    ])
    tier_1_brands = brand_tiers.get("tier_1", {}).get("brands", [
        "armani jeans", "emporio armani", "armani exchange", "ea7",
        "versace jeans", "versace jeans couture", "versus",
        "love moschino", "moschino jeans", "diesel", "guess",
        "weekend max mara", "max mara weekend", "just cavalli",
        "cavalli class", "class roberto cavalli", "roberto cavalli sport"
    ])

    brand_mult = 1.0
    if any(contains_whole_word(norm_brand, b) for b in tier_3_brands):
        brand_mult = float(brand_tiers.get("tier_3", {}).get("multiplier", 3.5))
    elif any(contains_whole_word(norm_brand, b) for b in tier_1_5_brands):
        brand_mult = float(brand_tiers.get("tier_1_5", {}).get("multiplier", 1.8))
    elif any(contains_whole_word(norm_brand, b) for b in tier_1_brands):
        brand_mult = float(brand_tiers.get("tier_1", {}).get("multiplier", 1.0))
    else:
        brand_mult = 1.0

    # 3. Facteur pièce distinctive / exceptionnelle
    features = distinctive_features or []
    if features and len(features) > 0:
        if score >= 90:
            score_mult = 4.0
        elif score >= 75:
            score_mult = 2.5
        else:
            score_mult = 1.0
    else:
        score_mult = 1.0

    effective_cap = base_cap * brand_mult * score_mult
    return base_cap, brand_mult, effective_cap, cat

class DealEvaluator:
    """
    Évalue si un article correspond précisément aux critères d'une bonne affaire.
    Phase 2.2 : Séparé en deux passes :
    1. prefilter() : titre, prix, mots exclus (avant l'enrichissement réseau)
    2. full_filter() : marque, état, note vendeur, favoris, fast-fashion (après enrichissement)
    """

    @staticmethod
    def _extract_item_price(item: Dict[str, Any]) -> float:
        price_obj = item.get("price")
        if isinstance(price_obj, dict):
            try:
                return float(price_obj.get("amount", 0.0))
            except (ValueError, TypeError):
                return 0.0
        elif isinstance(price_obj, (int, float, str)):
            try:
                return float(price_obj)
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    @staticmethod
    def is_child_item(item: Dict[str, Any]) -> Tuple[bool, str]:
        """Détecte de manière exhaustive si une annonce concerne un article enfant/bébé/junior."""
        title = str(item.get("title") or "")
        raw_title = str(item.get("raw_title") or "")
        description = str(item.get("description") or "")
        brand_title = str(item.get("brand_title") or item.get("brand") or "")
        size_title = str(item.get("size_title") or item.get("size") or "")
        category = str(item.get("category") or item.get("category_normalized") or "")
        url = str(item.get("url") or "")

        full_text = f"{title} {raw_title} {brand_title} {size_title} {description} {category} {url}".lower()

        # 1. Marques et lignes enfants spécifiques (Armani Junior, Kenzo Kids, etc.)
        for cb in CHILD_BRANDS:
            if cb in full_text:
                return True, f"Ligne/marque enfant détectée ('{cb}')"

        # 2. Tailles et statures enfants (âge, cm, mois)
        size_check_text = f"{size_title} {title} {raw_title}"
        m_size = CHILD_SIZE_REGEX.search(size_check_text)
        if m_size:
            return True, f"Taille enfant détectée ('{m_size.group(0)}')"

        # 3. Chaussures pointures enfants (< 34)
        is_foot = any(k in full_text for k in ["chaussure", "baskets", "sneakers", "bottes", "escarpins", "sandales"])
        if is_foot and size_title:
            m_small_foot = re.search(r'\b(1[6-9]|2\d|3[0-3])(?:\.5| 1/2)?\b', size_title)
            if m_small_foot:
                return True, f"Pointure enfant détectée ('{m_small_foot.group(0)}')"

        # 4. Mots-clés enfants multilingues
        for ck in CHILD_KEYWORDS:
            if contains_whole_word(full_text, ck):
                return True, f"Mot-clé enfant détecté ('{ck}')"

        # 5. Mots de contexte enfant
        child_context = ["mon fils", "ma fille", "pour mon fils", "pour ma fille", "pour fille", "pour garçon", "garconnet", "fillette", "fillettes"]
        for cc in child_context:
            if cc in full_text:
                return True, f"Contexte enfant ('{cc}')"

        return False, ""

    @staticmethod
    def prefilter(item: Dict[str, Any], search_config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Passe 1 (Avant enrichissement) :
        Vérifie le prix, les articles enfants, les mots exclus (mot entier), les marqueurs de faux dans le titre,
        la cohérence de genre et de pertinence produit.
        """
        # 0. Exclusion stricte et immédiate des articles enfants (titre, taille, marque)
        is_child, child_reason = DealEvaluator.is_child_item(item)
        if is_child:
            return False, f"Article enfant exclu : {child_reason}"

        title = item.get("title") or ""
        raw_title = item.get("raw_title") or ""
        description = item.get("description") or ""
        check_text = f"{title} {raw_title}".strip()

        # 1. Vérification du prix
        min_price = search_config.get("min_price", 10.0)
        max_price = search_config.get("max_price")
        item_price = DealEvaluator._extract_item_price(item)

        if min_price and item_price < float(min_price):
            return False, f"Prix ({item_price}€) inférieur au minimum anti-poubelle ({min_price}€)"

        if max_price and item_price > float(max_price):
            return False, f"Prix ({item_price}€) supérieur au maximum autorisé ({max_price}€)"

        # 2. Vérification des mots-clés indésirables (mot entier, insensible casse/accents)
        exclude_keywords = search_config.get("exclude_keywords", [])
        all_excludes = exclude_keywords + CHILD_KEYWORDS + JUNK_KEYWORDS

        for kw in all_excludes:
            if contains_whole_word(check_text, kw):
                return False, f"Contient le mot-clé exclu : '{kw}'"

        # 2a. Marque fast-fashion lisible dans le titre catalogue ("..., marque: Zara, ...") : rejet avant d'ouvrir la page
        m_brand = re.search(r'(?:marque|brand|marca|marke|merk)\s*:\s*([^,]+)', raw_title, re.IGNORECASE)
        if m_brand:
            cat_brand = normalize_text(m_brand.group(1).strip())
            if cat_brand in FAST_FASHION_BRANDS:
                return False, f"Marque fast-fashion (catalogue) : '{m_brand.group(1).strip()}'"

        # 2b. Accessoires exclus (titre uniquement, pour ne pas rejeter un jean dont la description parle de ceinture)
        if search_config.get("exclude_accessories"):
            is_clothing = any(contains_whole_word(check_text, cw) for cw in CLOTHING_TITLE_KEYWORDS)
            acc = ACCESSORY_TITLE_KEYWORDS
            if search_config.get("allow_bags"):
                acc = [k for k in acc if k not in BAG_TITLE_KEYWORDS]
            kws = BEAUTY_TITLE_KEYWORDS if is_clothing else acc + BEAUTY_TITLE_KEYWORDS
            for kw in kws:
                if contains_whole_word(check_text, kw):
                    return False, f"Accessoire ou beauté exclu (titre) : '{kw}'"

        # 2c. Garde-fou catégorie / non-vêtements (Point 2) :
        # Doit être un vêtement, des chaussures ou un sac (rejet objets, déco, boîte, cintre, livre, parfum, etc.)
        is_cloth_or_bag, cloth_reason, detected_cat = is_clothing_shoes_or_bag(check_text)
        if not is_cloth_or_bag:
            return False, f"Article exclu : {cloth_reason}"
        if detected_cat:
            item["detected_category"] = detected_cat

        # 3. Protection Anti-Imitation / Faux / "Style X" dans le titre
        norm_title = normalize_text(title)
        for fm in FAKE_MARKERS:
            norm_fm = normalize_text(fm)
            if norm_fm in norm_title:
                return False, f"Article écarté (mention '{fm.strip()}' dans le titre)"

        # 3b. Exclusion stricte BB Cavalli / B. Cavalli
        norm_raw_brand = normalize_text(item.get("brand_title") or "")
        if any(bb in norm_title or bb in norm_raw_brand for bb in ["bb cavalli", "b cavalli", "b. cavalli", "b.cavalli"]):
            return False, "Marque BB Cavalli / B. Cavalli exclue"

        # 3c. Exclusion des hauts Kenzo avec tête de tigre / lion
        if "kenzo" in norm_title or "kenzo" in norm_raw_brand:
            feline_kws = ["tigre", "tiger", "tigers", "tigres", "lion", "lions", "leone", "leoni", "tigerhead", "tiger head", "tete de tigre", "tete de lion"]
            if any(contains_whole_word(norm_title, fk) for fk in feline_kws):
                top_kws = ["sweat", "pull", "tshirt", "t-shirt", "tee", "top", "hoodie", "cardigan", "gilet", "chemise", "debardeur", "maglia", "sudadera", "camiseta", "haut"]
                detected_c = item.get("detected_category") or ""
                if detected_c in {"tshirt", "top", "chemise_blouse", "sweat", "pull_maille"} or any(contains_whole_word(norm_title, tk) for tk in top_kws):
                    return False, "Haut Kenzo tête de tigre / lion exclu"

        
        # 3d. Exclusion stricte des trousses de toilette, vanity, pochettes beauté / cosmétique
        for tk in TOILETRY_KEYWORDS:
            if contains_whole_word(norm_title, tk):
                return False, f"Article exclu (trousse de toilette / cosmétique : '{tk}')"

        # 3e. Exclusion des sacs de boutique, sacs papier, emballages, dustbags
        for bk in BOUTIQUE_PACKAGING_KEYWORDS:
            if contains_whole_word(norm_title, bk):
                return False, f"Article exclu (sac de boutique / packaging : '{bk}')"

        # 3f. Exclusion des pièces basiques (t-shirts simples / unis, jeans bleus classiques)
        for bi in BASIC_ITEMS_KEYWORDS:
            if contains_whole_word(norm_title, bi):
                return False, f"Pièce basique exclue ('{bi}')"

        # 4. Gestion du Genre : Homme vs Femme vs Unisexe
        search_name = (search_config.get("name") or "").lower()
        raw_search = (search_config.get("search_text") or "").lower()
        is_men_search = any(contains_whole_word(search_name, mk) or contains_whole_word(raw_search, mk) for mk in GENDER_KEYWORDS_MEN)
        is_women_search = any(contains_whole_word(search_name, wk) or contains_whole_word(raw_search, wk) for wk in GENDER_KEYWORDS_WOMEN)

        url_text = (item.get("url") or "").lower()
        clean_text_check = f" {title} {description} {url_text} "
        clean_text_check = re.sub(r'[\-_/\.,;\:]', ' ', clean_text_check)

        if is_men_search and not is_women_search:
            for wkw in FEMALE_ONLY_PIECES:
                if contains_whole_word(clean_text_check, wkw):
                    return False, f"Article féminin exclu de la recherche Homme ('{wkw}')"
        elif is_women_search and not is_men_search:
            for mkw in GENDER_KEYWORDS_MEN:
                if contains_whole_word(clean_text_check, mkw):
                    return False, f"Article Homme exclu de la recherche Femme ('{mkw}')"

        # 5. Pertinence Produit : Au moins un mot-clé substantiel dans le titre ou raw_title
        # Exception majeure : Si la recherche cible une marque (b_*) et que la marque de l'article (brand_title)
        # correspond déjà à la marque ciblée, le vendeur n'a pas besoin de répéter le nom de la marque dans son titre
        # (ex: Titre: 'Jupe hiver', Marque Vinted: 'Versace' -> 100% pertinent !).
        brand_target = (search_config.get("brand") or "").lower()
        brand_variants = [v.lower() for v in (search_config.get("brand_variants") or [])]
        if brand_target and brand_target not in brand_variants:
            brand_variants.append(brand_target)

        item_brand = (item.get("brand_title") or "").strip().lower()
        norm_brand = normalize_text(item_brand)
        is_brand_search = bool(
            search_config.get("id", "").startswith("b_") or
            search_config.get("brand_ids") or
            brand_variants
        )
        brand_matched = any(
            normalize_text(v) in norm_brand or norm_brand in normalize_text(v)
            for v in brand_variants
        ) if brand_variants else False

        if not (is_brand_search and brand_matched):
            substantive_words = [
                w for w in re.findall(r'\b[a-zA-ZÀ-ÿ]{3,}\b', raw_search)
                if normalize_text(w) not in {
                    "les", "des", "pour", "avec", "sans", "tout", "tous", "dans", "sur",
                    "une", "par", "vintage", "homme", "femme", "ancien", "della", "delle",
                    "fur", "von", "mit", "und", "del", "con", "para"
                }
            ]
            if substantive_words:
                matched_words = [w for w in substantive_words if contains_whole_word(check_text, w)]
                if not matched_words:
                    return False, f"Article non pertinent : aucun terme de '{raw_search}' trouvé dans le titre"

        # 6. Filtre Strict "Que du Vintage" (si la recherche cible le vintage)
        is_vintage_search = "vintage" in search_name or "vintage" in raw_search
        if is_vintage_search:
            has_vintage_signal = any(contains_whole_word(check_text, vs) for vs in VINTAGE_SIGNALS)
            # Si le signal vintage n'est pas dans le titre mais qu'on a une description disponible
            if not has_vintage_signal and description:
                has_vintage_signal = any(contains_whole_word(description, vs) for vs in VINTAGE_SIGNALS)
            if not has_vintage_signal and not description:
                # Si pas de description (juste catalogue), on vérifie le titre
                # S'il n'y a pas de signal dans le titre, on ne rejette pas encore si la marque est déjà ultra-vintage,
                # mais si 'vintage' est expressément cherché, on demande au moins une trace
                if not any(contains_whole_word(check_text, vs) for vs in VINTAGE_SIGNALS):
                    return False, "Article écarté : non-vintage (aucun mot-clé vintage détecté dans le titre)"

        return True, "Préfiltrage validé"

    @staticmethod
    def full_filter(item: Dict[str, Any], search_config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Passe 2 (Après enrichissement avec fetch_item_details) :
        Vérifie la marque, l'état (pas de 'Satisfaisant'), la note du vendeur,
        les favoris, l'exclusion fast-fashion et re-teste la description complète.
        """
        title = item.get("title") or ""
        raw_title = item.get("raw_title") or ""
        description = item.get("description") or ""
        full_text = f"{title} {raw_title} {description}".strip()

        # -1. Re-vérification stricte des articles enfants sur les détails complets (description, marque, etc.)
        is_child, child_reason = DealEvaluator.is_child_item(item)
        if is_child:
            return False, f"Article enfant exclu : {child_reason}"

        # 0. Re-vérification stricte du prix enrichi (Correction 4 : prix validé via JSON-LD)
        min_price = search_config.get("min_price", 10.0)
        max_price = search_config.get("max_price")
        certified_price = DealEvaluator._extract_item_price(item)

        if min_price and certified_price < float(min_price):
            return False, f"Prix enrichi ({certified_price}€) inférieur au minimum anti-poubelle ({min_price}€)"

        if max_price and certified_price > float(max_price):
            return False, f"Prix enrichi ({certified_price}€) supérieur au maximum autorisé ({max_price}€)"

        # 1. Re-vérification des mots-clés exclus sur la description intégrale
        exclude_keywords = search_config.get("exclude_keywords", [])
        all_excludes = exclude_keywords  # description : uniquement les exclusions propres à la recherche (JUNK sur description rejetait "fur collar", "pet"...)
        if description:
            for kw in all_excludes:
                if contains_whole_word(description, kw):
                    return False, f"Description contient le mot-clé exclu : '{kw}'"

        # 2. Vérification de l'état (Exclure les articles en état 'Satisfaisant' ou équivalent multilingue)
        status = (item.get("status") or "").lower()
        norm_status = normalize_text(status)
        for sat_marker in SATISFACTORY_STATUS_MARKERS:
            if normalize_text(sat_marker) in norm_status:
                return False, f"État de l'article '{item.get('status')}' exclu (pas de 'Satisfaisant')"

        # 3. Exclusion stricte des marques Fast-Fashion et bas de gamme
        item_brand = (item.get("brand_title") or "").strip().lower()
        norm_brand = normalize_text(item_brand)
        if norm_brand in FAST_FASHION_BRANDS or item_brand in FAST_FASHION_BRANDS:
            return False, f"Marque Fast-fashion / bas de gamme rejetée : '{item.get('brand_title')}'"

        # 3b. Exclusion formelle BB Cavalli / B. Cavalli
        if any(bb in normalize_text(title) or bb in norm_brand for bb in ["bb cavalli", "b cavalli", "b. cavalli", "b.cavalli"]):
            return False, "Marque BB Cavalli / B. Cavalli exclue"

        # 3c. Exclusion des hauts Kenzo tête de tigre / lion (sur description et texte complet)
        if "kenzo" in normalize_text(title) or "kenzo" in norm_brand:
            feline_kws = ["tigre", "tiger", "tigers", "tigres", "lion", "lions", "leone", "leoni", "tigerhead", "tiger head", "tete de tigre", "tete de lion"]
            norm_full = normalize_text(full_text)
            if any(contains_whole_word(norm_full, fk) for fk in feline_kws):
                top_kws = ["sweat", "pull", "tshirt", "t-shirt", "tee", "top", "hoodie", "cardigan", "gilet", "chemise", "debardeur", "maglia", "sudadera", "camiseta", "haut"]
                detected_c = item.get("detected_category") or ""
                if detected_c in {"tshirt", "top", "chemise_blouse", "sweat", "pull_maille"} or any(contains_whole_word(norm_full, tk) for tk in top_kws):
                    return False, "Haut Kenzo tête de tigre / lion exclu"

        # 4. Validation Stricte de la Marque Cible
        brand_target = search_config.get("brand")
        brand_variants = search_config.get("brand_variants") or []
        if not brand_variants and brand_target:
            brand_variants = [brand_target.lower()]

        if brand_variants:
            brand_matched = any(normalize_text(v) in norm_brand for v in brand_variants)
            title_matched = any(contains_whole_word(title, v) or normalize_text(v) in normalize_text(title) for v in brand_variants)

            # Si une marque spécifique autre est indiquée, refus immédiat
            if norm_brand and norm_brand not in GENERIC_BRANDS:
                if not brand_matched:
                    return False, f"Marque '{item.get('brand_title')}' non conforme (attendu: '{brand_target}')"
            else:
                # Si marque Vinted vide ou générique, le titre doit obligatoirement comporter la marque
                if not title_matched:
                    return False, f"Marque '{brand_target}' absente du titre (marque Vinted: '{item.get('brand_title')}')"

        # 5. Note du vendeur (optionnel)
        min_seller_rating = search_config.get("min_seller_rating")
        user = item.get("user") or {}
        feedback_reputation = user.get("feedback_reputation")
        feedback_count = user.get("feedback_count", 0)

        if min_seller_rating and feedback_reputation is not None and feedback_count > 3:
            try:
                rep_val = float(feedback_reputation)
                rating_stars = rep_val * 5.0 if rep_val <= 1.0 else rep_val
                if rating_stars < float(min_seller_rating):
                    return False, f"Note du vendeur ({rating_stars:.1f}★) inférieure à la note minimale ({min_seller_rating}★)"
            except (ValueError, TypeError):
                pass

        # 6. Vérification du nombre minimum de favoris (In-Demand)
        min_favourites = search_config.get("min_favourites", 0)
        fav_count = item.get("favourite_count", item.get("favourited_count", 0))
        if min_favourites > 0 and fav_count < min_favourites:
            return False, f"Seulement {fav_count} ❤️ (Minimum requis : {min_favourites} ❤️)"

        # 7. Filtre Strict "Que du Vintage" sur la description si non trouvé dans le titre
        search_name = (search_config.get("name") or "").lower()
        raw_search = (search_config.get("search_text") or "").lower()
        is_vintage_search = "vintage" in search_name or "vintage" in raw_search
        if is_vintage_search:
            has_vintage_signal = any(contains_whole_word(full_text, vs) for vs in VINTAGE_SIGNALS)
            if not has_vintage_signal:
                return False, "Article écarté : non-vintage (aucun mot-clé vintage détecté)"

        return True, "Article validé - Bonne Affaire !"

    @staticmethod
    def evaluate(item: Dict[str, Any], search_config: Dict[str, Any]) -> Tuple[bool, str]:
        """Évaluation globale combinant prefilter et full_filter pour compatibilité."""
        is_ok, reason = DealEvaluator.prefilter(item, search_config)
        if not is_ok:
            return False, reason
        return DealEvaluator.full_filter(item, search_config)
