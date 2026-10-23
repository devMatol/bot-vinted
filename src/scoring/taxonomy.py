import re
import unicodedata
import functools
from typing import Dict, Any, Tuple, Optional, List

def normalize_text(text: str) -> str:
    """Minuscule et suppression des accents (NFKD) pour comparaison uniforme."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(text).lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()

@functools.lru_cache(maxsize=8192)
def _cached_normalize_kw(kw: str) -> str:
    return normalize_text(kw)

@functools.lru_cache(maxsize=8192)
def _get_word_pattern(norm_kw: str):
    return re.compile(rf'(?<!\w){re.escape(norm_kw)}(?!\w)')

def contains_whole_word(text: str, keyword: str, text_is_normalized: bool = False) -> bool:
    """Vérifie si le mot-clé apparaît sous forme de mot entier dans le texte."""
    if not text or not keyword:
        return False
    norm_text = text if text_is_normalized else normalize_text(text)
    norm_kw = _cached_normalize_kw(keyword)
    if not norm_kw or norm_kw not in norm_text:
        return False
    return bool(_get_word_pattern(norm_kw).search(norm_text))

# Catégories cibles normalisées (ordonnées par priorité de détection spécifique)
NORMALIZED_CATEGORIES = [
    "manteau_fourrure",  # Spécifique avant manteau
    "manteau",
    "blazer",            # Spécifique avant veste
    "veste",
    "escarpins",         # Spécifique avant chaussures
    "bottes",            # Spécifique avant chaussures
    "chaussures",
    "sweat",             # Spécifique avant pull_maille
    "pull_maille",
    "tshirt",            # Spécifique avant top
    "top",
    "chemise_blouse",
    "robe",
    "jupe",
    "jean",
    "short",
    "combinaison",
    "pantalon",
    "sac",
    "accessoire",
    "objet"
]

TAXONOMY_KEYWORDS: Dict[str, List[str]] = {
    "manteau_fourrure": [
        "fourrure", "manteau fourrure", "veste fourrure", "fausse fourrure", "fourrure vintage",
        "vison", "renard", "astrakan", "mouton retourne", "shearling", "pelisse", "castor",
        "pelliccia", "pellicciotto", "cappotto pelliccia", "montone",
        "abrigo piel", "abrigo pelo", "chaqueta pelo", "pelaje", "borrego",
        "pelz", "pelzmantel", "pelzjacke", "kunstpelz", "felljacke", "lammfell",
        "fur coat", "fur jacket", "faux fur", "real fur", "mink", "fox fur", "shearling coat"
    ],
    "manteau": [
        "manteau", "manteaux", "trench", "trenchcoat", "trench-coat", "doudoune", "doudounes", "parka", "parkas",
        "caban", "cabans", "pardessus", "anorak", "cape", "capes", "poncho", "ponchos", "mackintosh",
        "cappotto", "cappotti", "piumino", "piumini", "giaccone", "giacconi",
        "abrigo", "abrigos", "plumas", "gabardina", "gabardinas",
        "mantel", "maentel", "daunenjacke", "wintermantel", "winterjas",
        "coat", "overcoat", "down coat", "puffer"
    ],
    "blazer": [
        "blazer", "blazers", "tailleur", "tailleurs", "veste tailleur", "veste de tailleur",
        "giacca tailleur", "completo giacca",
        "traje chaqueta", "chaqueta sastre",
        "sakko", "sakkos", "anzugjacke"
    ],
    "veste": [
        "veste", "vestes", "blouson", "blousons", "perfecto", "perfectos", "bomber", "bombers",
        "teddy", "veste en jean", "veste cuir", "blouson cuir",
        "giacca", "giacche", "giubbotto", "giubbi", "giubbino", "cacciatora",
        "chaqueta", "chaquetas", "cazadora", "cazadoras", "chaqueton",
        "jacke", "jacken", "lederjacke", "jeansjacke", "bomberjacke",
        "jasje", "spijkerjasje",
        "jacket", "jackets", "leather jacket", "denim jacket"
    ],
    "escarpins": [
        "escarpin", "escarpins", "talons", "chaussures a talons", "chaussures à talons",
        "stiletto", "stilettos", "salome", "kitten heel", "kitten heels",
        "decollete", "décolleté", "decolletes", "décolletés", "scarpe col tacco", "tacchi",
        "tacones", "zapatos de tacon", "zapatos de tacón",
        "pumps", "high heels", "stoeckelschuhe", "stöckelschuhe",
        "heels"
    ],
    "bottes": [
        "botte", "bottes", "bottine", "bottines", "cuissarde", "cuissardes", "boots", "santiag", "santiags",
        "stivale", "stivali", "stivaletto", "stivaletti", "anfibi", "tronchetto", "tronchetti",
        "bota", "botas", "botin", "botines", "camperas",
        "stiefel", "stiefelette", "stiefeletten", "cowboystiefel",
        "laars", "laarzen", "laarsje", "laarsjes",
        "boot", "ankle boots", "knee high boots", "cowboy boots", "chelsea boots", "booties"
    ],
    "chaussures": [
        "chaussure", "chaussures", "basket", "baskets", "sneaker", "sneakers", "tennis",
        "mocassin", "mocassins", "derbie", "derbies", "richelieu", "ballerine", "ballerines",
        "sandale", "sandales", "mule", "mules", "claquette", "claquettes", "sabot", "sabots",
        "scarpa", "scarpe", "sandalo", "sandali", "mocassino", "mocassini", "ballerina", "ballerine", "ciabatta", "ciabatte",
        "zapato", "zapatos", "zapatilla", "zapatillas", "sandalia", "sandalias", "mocasin", "mocasines", "bailarinas",
        "schuh", "schuhe", "turnschuh", "turnschuhe", "sandalen", "halbschuh", "halbschuhe",
        "schoen", "schoenen",
        "shoe", "shoes", "loafers", "trainers", "sandals", "flats", "oxfords"
    ],
    "sweat": [
        "sweat", "sweats", "sweatshirt", "sweat-shirt", "hoodie", "hoodies", "crewneck",
        "felpa", "felpe",
        "sudadera", "sudaderas",
        "kapuzenpullover", "kapuzenpulli"
    ],
    "pull_maille": [
        "pull", "pulls", "maille", "mailles", "gilet", "gilets", "cardigan", "cardigans",
        "tricot", "col roule", "col roulé", "cachemire", "mohair", "alpaga", "laine",
        "maglione", "maglioni", "maglia", "maglie", "dolcevita", "lupetto", "golfino",
        "jersey", "jerseys", "sueter", "suéter", "rebeca", "punto",
        "pullover", "pulli", "strickjacke", "strickpullover", "rollkragenpullover", "strick",
        "trui", "truien", "vest",
        "sweater", "sweaters", "jumper", "jumpers", "knitwear", "knit", "turtleneck"
    ],
    "tshirt": [
        "t-shirt", "tshirt", "t-shirts", "tshirts", "tee", "tee-shirt", "tee shirt", "tees",
        "maglietta", "magliette",
        "camiseta", "camisetas"
    ],
    "top": [
        "top", "tops", "debardeur", "débardeur", "debardeurs", "caraco", "caracos",
        "bustier", "bustiers", "corset", "corsets", "crop top", "crop-top", "dos nu", "brassiere",
        "canotta", "canotte", "canottiera", "canottiere", "corsetto", "bustino",
        "camiseta de tirantes", "tirantes",
        "tank top", "tanktop", "oberteil", "oberteile", "sommertop", "korsett",
        "tank", "camisole", "cami", "halter"
    ],
    "chemise_blouse": [
        "chemise", "chemises", "chemisier", "chemisiers", "blouse", "blouses", "chemisette", "tunique", "tuniques",
        "camicia", "camicie", "camicetta", "camicette", "blusa", "bluse",
        "camisa", "camisas",
        "hemd", "hemden",
        "shirt", "shirts", "button up", "button down"
    ],
    "robe": [
        "robe", "robes",
        "abito", "abiti", "vestito", "vestiti",
        "vestido", "vestidos",
        "kleid", "kleider",
        "jurk", "jurken",
        "dress", "dresses", "gown"
    ],
    "jupe": [
        "jupe", "jupes", "minijupe", "mini-jupe",
        "gonna", "gonne", "minigonna",
        "falda", "faldas", "minifalda",
        "rock", "röcke", "minirock",
        "rok", "rokken",
        "skirt", "skirts", "miniskirt"
    ],
    "jean": [
        "jean", "jeans", "denim", "vaquero", "vaqueros", "tejanos", "spijkerbroek"
    ],
    "short": [
        "short", "shorts", "bermuda", "bermudas", "cycliste",
        "pantaloncini",
        "pantalones cortos",
        "kurze hose"
    ],
    "combinaison": [
        "combinaison", "combinaisons", "combi", "combishort", "salopette", "salopettes",
        "tuta", "jumpsuit",
        "mono", "peto",
        "overall", "latzhose",
        "romper", "dungarees", "playsuit"
    ],
    "pantalon": [
        "pantalon", "pantalons", "pantacourt", "cargo", "treillis", "jogging", "joggings",
        "legging", "leggings", "survetement", "survêtement",
        "pantalone", "pantaloni", "pantaloni della tuta",
        "pantalones", "pantalon de chandal",
        "hose", "hosen", "cargohose", "jogginghose",
        "broek", "broeken", "calca", "calcas", "calças",
        "pants", "trousers", "slacks", "chinos", "joggers", "sweatpants"
    ],
    "sac": [
        "sac", "sacs", "sacoche", "sacoches", "pochette", "pochettes", "cabas", "besace", "banane",
        "portefeuille", "porte-monnaie", "porte monnaie", "tote bag",
        "borsa", "borse", "borsetta", "borsette", "borsello", "zaino",
        "bolso", "bolsos", "bolsa", "bolsas", "mochila", "cartera",
        "tasche", "taschen", "handtasche", "rucksack",
        "tas", "tasje", "rugzak",
        "bag", "bags", "handbag", "handbags", "purse", "tote", "clutch", "backpack"
    ],
    "accessoire": [
        "ceinture", "ceintures", "echarpe", "écharpe", "echarpes", "foulard", "foulards",
        "chale", "châle", "gants", "bonnet", "bonnets", "casquette", "casquettes", "chapeau", "chapeaux",
        "lunettes", "lunettes de soleil", "cravate", "cravates", "noeud papillon",
        "bijou", "bijoux", "collier", "colliers", "bague", "bagues", "bracelet", "bracelets",
        "cintura", "cinture", "sciarpa", "sciarpe", "cappello", "cappelli", "guanti", "occhiali", "cravatta", "collana",
        "cinturon", "cinturón", "bufanda", "panuelo", "gorro", "sombrero", "gafas", "collar",
        "gürtel", "gurtel", "schal", "tuch", "mütze", "mutze", "hut", "brille", "krawatte",
        "belt", "scarf", "hat", "cap", "beanie", "gloves", "sunglasses", "tie", "necklace",
        # ajouts 23/10 (vus dans le backtest)
        "sjaal", "schaal", "stola", "portaocchiali", "etui", "étui", "astuccio", "custodia", "funda",
        "portafoglio", "portefeuille", "porte-monnaie", "wallet", "portacarte",
        "reggiseno", "soutien-gorge", "sujetador", "lingerie", "culotte", "mutande", "intimo",
        "calze", "chaussettes", "socks", "calzini"
    ],
    "objet": [
        "stoffa", "stoffe", "tessuto", "tissu", "coupon de tissu", "fabric",
        "coupe a fruits", "coupe à fruits", "cintre", "cintres", "gruccia", "grucce", "appendino", "appendini",
        "percha", "perchas", "kleiderbugel", "kleiderbügel", "hanger", "hangers",
        "boite", "boîte", "boites", "boîtes", "scatola", "scatole", "caja", "cajas", "box", "boxes", "kiste",
        "livre", "livres", "bouquin", "libro", "libri", "buch", "bücher", "bucher", "book", "books",
        "parfum", "parfums", "profumo", "profumi", "perfume", "perfumes", "fragrance", "flacon",
        "pochette beaute", "pochette beauté", "pochette parfum", "trousse beaute", "trousse beauté",
        "beauty pouch", "beauty bag", "toilet tasje", "toilettas",
        "application", "socle", "stand", "support",
        "vaisselle", "plat", "plats", "assiette", "assiettes", "piatto", "piatti", "plato", "teller", "dish",
        "verre", "verres", "bicchiere", "bicchieri", "vaso", "glas", "gläser",
        "tasse", "tasses", "mug", "mugs", "tazza", "tazze", "cup",
        "bougie", "bougies", "candela", "candele", "vela", "kerze", "candle",
        "affiche", "poster", "cadre", "cadres", "quadro", "quadri", "marco", "rahmen", "frame",
        "figurine", "bibelot", "statue", "statuette", "sculpture",
        "coussin", "coussins", "oreiller", "plaid", "couverture", "cuscino", "cojin", "kissen", "pillow",
        "tableau", "peinture", "peluche", "peluches", "jouet", "jouets", "jeu", "jeux", "toy", "toys",
        "porte-cles", "porte-cle", "porte cles", "porte cle", "portachiavi", "llavero", "keychain", "keyring",
        "coque", "housse telephone", "phone case", "cendrier", "aschenbecher", "ashtray"
    ]
}

def detect_category(title: str, description: str = "") -> str:
    """
    Détecte la catégorie normalisée à partir du titre et de la description.
    Le titre est prioritaire. L'ordre de NORMALIZED_CATEGORIES garantit la priorité
    aux mots les plus spécifiques (ex: escarpins avant chaussures, manteau_fourrure avant manteau).
    """
    clean_title = normalize_text(title or "")
    clean_desc = normalize_text(description or "")

    # 1. Vérification dans le titre d'abord
    for cat in NORMALIZED_CATEGORIES:
        keywords = TAXONOMY_KEYWORDS.get(cat, [])
        for kw in keywords:
            if contains_whole_word(clean_title, kw, text_is_normalized=True):
                return cat

    # 2. Vérification dans la description en second recours
    if clean_desc:
        for cat in NORMALIZED_CATEGORIES:
            keywords = TAXONOMY_KEYWORDS.get(cat, [])
            for kw in keywords:
                if contains_whole_word(clean_desc, kw, text_is_normalized=True):
                    return cat

    return "inconnu"

# Normalisation des marques vers une marque canonique, ligne et palier
# Structure : canonical_brand -> { "aliases": [...], "line": "principale"|"diffusion", "tier": float }
BRAND_REGISTRY: List[Dict[str, Any]] = [
    # Roberto Cavalli
    {
        "canonical": "Roberto Cavalli",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["just cavalli", "class roberto cavalli", "cavalli class", "roberto cavalli class", "roberto cavalli sport"]
    },
    {
        "canonical": "Roberto Cavalli",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["roberto cavalli", "cavalli"]
    },
    # Dolce & Gabbana
    {
        "canonical": "Dolce & Gabbana",
        "line": "diffusion",
        "tier": 1.5,
        "aliases": ["d&g", "d & g", "d and g", "d&g dolce & gabbana"]
    },
    {
        "canonical": "Dolce & Gabbana",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["dolce & gabbana", "dolce gabbana", "dolce&gabbana", "dolce e gabbana"]
    },
    # Max Mara
    {
        "canonical": "Max Mara",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": [
            "weekend max mara", "max mara weekend", "sportmax", "sport max",
            "max & co", "max and co", "max&co", "marella", "pennyblack", "iblues", "persona by marina rinaldi"
        ]
    },
    {
        "canonical": "Max Mara",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["max mara", "maxmara", "marina rinaldi"]
    },
    # Versace
    {
        "canonical": "Versace",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": [
            "versace jeans", "versace jeans couture", "versus", "versus versace",
            "versace classic", "versace collection", "versace sport"
        ]
    },
    {
        "canonical": "Versace",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["versace", "gianni versace"]
    },
    # Moschino
    {
        "canonical": "Moschino",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["love moschino", "moschino jeans", "cheap and chic", "moschino cheap and chic", "boutique moschino"]
    },
    {
        "canonical": "Moschino",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["moschino"]
    },
    # Yves Saint Laurent
    {
        "canonical": "Yves Saint Laurent",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["ysl", "yves saint laurent", "saint laurent", "rive gauche", "saint laurent paris"]
    },
    # Gucci
    {
        "canonical": "Gucci",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["gucci"]
    },
    # Prada
    {
        "canonical": "Prada",
        "line": "diffusion",
        "tier": 3.0,
        "aliases": ["prada linea rossa", "prada sport"]
    },
    {
        "canonical": "Prada",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["prada"]
    },
    # Miu Miu
    {
        "canonical": "Miu Miu",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["miu miu", "miumiu"]
    },
    # Armani
    {
        "canonical": "Armani",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": [
            "armani jeans", "emporio armani", "armani exchange", "ea7",
            "armani collezioni", "aj armani jeans"
        ]
    },
    {
        "canonical": "Armani",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["giorgio armani", "armani"]
    },
    # Kenzo
    {
        "canonical": "Kenzo",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["kenzo"]
    },
    # Mugler
    {
        "canonical": "Mugler",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["mugler", "thierry mugler"]
    },
    # Jean Paul Gaultier
    {
        "canonical": "Jean Paul Gaultier",
        "line": "diffusion",
        "tier": 1.5,
        "aliases": ["gaultier junior", "jean's paul gaultier", "maille jean paul gaultier"]
    },
    {
        "canonical": "Jean Paul Gaultier",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["jean paul gaultier", "jpg"]
    },
    # Diffusion et marques courantes
    {
        "canonical": "Diesel",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["diesel", "diesel black gold"]
    },
    {
        "canonical": "Guess",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["guess", "guess jeans", "marciano guess"]
    },
    {
        "canonical": "Liu Jo",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["liu jo", "liu.jo", "liujo"]
    },
    {
        "canonical": "Patrizia Pepe",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["patrizia pepe"]
    },
    {
        "canonical": "Pinko",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["pinko"]
    },
    {
        "canonical": "Twinset",
        "line": "diffusion",
        "tier": 1.0,
        "aliases": ["twinset", "twin set", "twin-set"]
    },
    {
        "canonical": "Burberry",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["burberry", "burberrys", "burberry prorsum", "burberry london", "burberry brit"]
    },
    {
        "canonical": "Fendi",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["fendi"]
    },
    {
        "canonical": "Dior",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["dior", "christian dior"]
    },
    {
        "canonical": "Chanel",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["chanel"]
    }
]

def normalize_brand(brand_title: str, item_title: str = "") -> Tuple[str, str, float]:
    """
    Normalise la marque vers (marque_canonique, ligne ['principale'|'diffusion'], palier [1.0, 1.5, 3.0]).
    Teste d'abord les lignes de diffusion pour éviter qu'une sous-ligne (ex: Armani Jeans)
    soit capturée à tort par la marque mère (Armani).
    """
    text_to_check = normalize_text(f"{brand_title or ''} {item_title or ''}")
    if not text_to_check:
        return "Sans marque", "diffusion", 1.0

    # Rejet explicite BB Cavalli / B. Cavalli (ne pas attribuer à Roberto Cavalli)
    if any(bb in text_to_check for bb in ["bb cavalli", "b cavalli", "b. cavalli", "b.cavalli"]):
        return "Sans marque", "diffusion", 0.5

    # 1. Tester les aliases les plus longs / spécifiques d'abord
    # Tri par longueur d'alias décroissante
    sorted_registry = sorted(
        BRAND_REGISTRY,
        key=lambda entry: max(len(a) for a in entry["aliases"]),
        reverse=True
    )

    for entry in sorted_registry:
        for alias in entry["aliases"]:
            if contains_whole_word(text_to_check, alias):
                return entry["canonical"], entry["line"], float(entry["tier"])

    clean_brand = (brand_title or "").strip()
    if clean_brand and clean_brand.lower() not in {"sans marque", "vintage", "autre", "other", "inconnu", "unbranded"}:
        return clean_brand.title(), "diffusion", 1.0

    return "Sans marque", "diffusion", 1.0

def normalize_size(raw_size: str, category: str = "") -> str:
    """
    Normalise la taille vers une échelle commune :
    - Vêtements : XS, S, M, L, XL+, TU
    - Pointures (chaussures, bottes, escarpins) : nombre flottant normalisé (ex: '38.0', '39.0')
    - Enfants : 'ENFANT' pour rejet immédiat
    """
    if not raw_size:
        return "NC"
    
    clean = normalize_text(str(raw_size)).strip()
    if not clean:
        return "NC"

    # 0. Détection stricte des tailles enfants (âge, stature cm, mois)
    # Ex: 2 ans, 14 ans, 16A, 12Y, 152 cm, 164 cm, 6 mois, 24 mesi, 12 anni...
    if re.search(
        r'\b(?:'
        r'\d{1,2}\s*(?:ans?|anni|anos|años|jahre|monate|years?|yo|mois|mesi|meses|months?)\b|'
        r'\b\d{1,2}\s*(?:a|y)\b|'
        r'\b(?:enfant|bambin|kid|junior|garcon|fille|baby|bebe|infantil)\b|'
        r'\b(?:50|56|62|68|74|80|86|92|98|104|110|116|122|128|134|140|146|152|158|164|170|176)\s*(?:cm)?\b'
        r')',
        clean,
        re.IGNORECASE
    ):
        return "ENFANT"

    # Pointures enfants (< 34)
    is_footwear = category in {"chaussures", "bottes", "escarpins"}
    if is_footwear:
        m_small_foot = re.search(r'\b(1[6-9]|2\d|3[0-3])(?:\.5| 1/2)?\b', clean)
        if m_small_foot:
            return "ENFANT"

    # Vérification taille unique
    if clean in {"taille unique", "unique", "one size", "onesize", "tu", "os", "u"}:
        return "TU"

    # Pointures (chaussures, bottes, escarpins)
    is_footwear = category in {"chaussures", "bottes", "escarpins"}
    m_foot = re.search(r'\b(3[4-9]|4[0-6])(?:\.5| 1/2)?\b', clean)
    if is_footwear and m_foot:
        val = float(m_foot.group(1))
        if ".5" in clean or "1/2" in clean:
            val += 0.5
        return f"{val:.1f}"

    # Tailles italiennes prioritaires si préfixe IT (IT 38 = FR 34/XS, IT 40 = FR 36/S, IT 42 = FR 38/M, IT 44 = FR 40/M, IT 46 = FR 42/L)
    m_it = re.search(r'\b(?:it|it\.)\s*(\d{2})\b', clean)
    if m_it:
        it_val = int(m_it.group(1))
        if it_val <= 38:
            return "XS"
        elif it_val <= 40:
            return "S"
        elif it_val <= 44:
            return "M"
        elif it_val <= 48:
            return "L"
        else:
            return "XL+"

    # Tailles de vêtements explicites lettre
    if re.search(r'\b(?:xxs|xs)\b', clean):
        return "XS"
    if re.search(r'\bs\b', clean):
        return "S"
    if re.search(r'\bm\b', clean):
        return "M"
    if re.search(r'\bl\b', clean):
        return "L"
    if re.search(r'\b(?:xl|xxl|xxxl)\b', clean):
        return "XL+"

    # Numériques simples (FR par défaut)
    m_num = re.search(r'\b(\d{2})\b', clean)
    if m_num:
        num_val = int(m_num.group(1))
        if is_footwear:
            if 34 <= num_val <= 46:
                return f"{float(num_val):.1f}"
        if num_val <= 34:
            return "XS"
        elif num_val == 36:
            return "S"
        elif num_val in (38, 40):
            return "M"
        elif num_val in (42, 44):
            return "L"
        elif num_val >= 46:
            return "XL+"

    # Fallback majuscule
    return raw_size.strip().upper()
