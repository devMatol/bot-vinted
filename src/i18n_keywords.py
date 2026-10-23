"""
Mots-clés multilingues (FR / IT / DE / ES / NL / PT / EN) pour le filtrage Vinted.
Phase 3.6 : exclusion d'articles non désirés, faux, genres et états.
"""

import re

CHILD_KEYWORDS = [
    # Français
    "enfant", "enfants", "kids", "junior", "garçon", "fille", "fillette", "fillettes", "garçonnet", "bébé", "baby",
    "10 ans", "12 ans", "14 ans", "16 ans", "18 ans", "6 mois", "9 mois", "12 mois", "18 mois", "24 mois", "36 mois",
    "1 an", "2 ans", "3 ans", "4 ans", "5 ans", "6 ans", "7 ans", "8 ans", "9 ans",
    "taille enfant", "rayon enfant", "section enfant", "pour enfant", "pour fille", "pour garçon",
    # Italien
    "bambino", "bambina", "bambini", "bambine", "neonato", "neonata", "bimbo", "bimba", "ragazzo", "ragazza", "ragazzino", "ragazzina",
    "10 anni", "12 anni", "14 anni", "16 anni", "6 mesi", "9 mesi", "12 mesi", "18 mesi", "24 mesi",
    "2 anni", "3 anni", "4 anni", "5 anni", "6 anni", "8 anni",
    # Allemand
    "kind", "kinder", "junge", "mädchen", "kleinkind",
    "10 jahre", "12 jahre", "14 jahre", "16 jahre", "6 monate", "9 monate", "12 monate", "18 monate", "24 monate",
    "2 jahre", "3 jahre", "4 jahre", "5 jahre", "6 jahre", "8 jahre",
    # Espagnol
    "niño", "niña", "niños", "niñas", "bebe", "bebé", "chico", "chica", "infantil",
    "10 años", "12 años", "14 años", "16 años", "6 meses", "9 meses", "12 meses", "18 meses", "24 meses",
    "2 años", "3 años", "4 años", "5 años", "6 años", "8 años",
    # Néerlandais
    "kinderen", "jongen", "meisje", "peuter",
    "10 jaar", "12 jaar", "14 jaar", "16 jaar", "6 maanden", "9 maanden", "12 maanden",
    "2 jaar", "3 jaar", "4 jaar", "5 jaar", "6 jaar", "8 jaar",
    # Portugais
    "criança", "crianças", "menino", "menina",
    "10 anos", "12 anos", "14 anos", "16 anos", "6 meses", "9 meses", "12 meses", "18 meses", "24 meses",
    "2 anos", "3 anos", "4 anos", "5 anos", "6 anos", "8 anos",
    # Anglais commun
    "toddler", "infant", "youth", "teen", "teenager", "adolescent", "adolescente"
]

CHILD_BRANDS = [
    "armani junior", "gucci kids", "kenzo kids", "baby dior", "dior baby", "cavalli junior",
    "roberto cavalli junior", "burberry children", "burberry kids", "moschino kids", "fendi kids",
    "versace young", "dg junior", "d&g junior", "dolce gabbana junior", "dolce & gabbana junior",
    "guess kids", "diesel kid", "diesel junior", "monnalisa", "bonpoint", "jacadi", "petit bateau",
    "tartine et chocolat", "catimini", "mayoral", "okaidi", "obaibi", "tape a l oeil", "sergent major",
    "zara kids", "mango kids", "h&m kids"
]

CHILD_SIZE_REGEX = re.compile(
    r'\b(?:'
    r'\d{1,2}\s*(?:ans?|anni|anos|años|jahre|monate|years?|yo|mois|mesi|meses|months?)\b|'
    r'\b\d{1,2}\s*(?:a|y)\b|'
    r'\b(?:50|56|62|68|74|80|86|92|98|104|110|116|122|128|134|140|146|152|158|164|170|176)\s*(?:cm)?\b'
    r')',
    re.IGNORECASE
)

JUNK_KEYWORDS = [
    # Boîtes, emballages, étuis, vide
    "boite", "boîte", "vide", "vuoto", "vuota", "scatola", "caja", "vacia", "vacía", "empty", "box",
    "schachtel", "karton", "leer", "leere", "doos", "leeg", "lege",
    "étui", "etui", "astuccio", "funda", "coque", "cover", "case", "hülle", "hoesje", "estojo", "capa",
    "dustbag", "dust bag", "dust-bag", "sacoche vide", "pochette vide", "sac papier", "bolsa vacia", "sacchetto vuoto",
    "hanger", "cintre", "gruccia", "kleiderbügel", "percha", "kledinghanger", "cabide",
    # Parfums, cosmétiques, échantillons
    "parfum", "profumo", "fragrance", "duft", "parfüm", "muestra", "amostra", "staaltje", "probe",
    "tester", "sample", "échantillon", "campione",
    # Porte-clés
    "porte-clé", "porte-clef", "portachiavi", "keychain", "schlüsselanhänger", "llavero", "sleutelhanger", "porta-chaves",
    # Sous-vêtements & chaussettes
    "chaussettes", "calzini", "socks", "socken", "calcetines", "meias",
    "caleçon", "boxer", "slip", "underpants", "underwear", "mutande", "unterhose", "boxershorts", "calzoncillos", "cuecas", "onderbroek",
    # Lunettes & accessoires optiques
    "lunettes", "occhiali", "gafas", "glasses", "sunglasses", "brille", "sonnenbrille", "zonnebril", "óculos", "oculos",
    # Casquettes, bonnets
    "casquette", "cap", "cappello", "gorra", "bonnet", "berretto", "bob", "mütze", "kappe", "basecap", "pet", "muts", "boné", "bone", "beanie",
    # Bijoux fantaisie & accessoires
    "bague", "collier", "bracelet", "boucles d'oreilles", "boucle d'oreille", "pendentif", "bijou", "bijoux", "piercing",
    "anello", "collana", "bracciale", "orecchini", "ciondolo", "gioiello", "gioielli",
    "ring", "halskette", "armband", "ohrringe", "anhänger", "schmuck",
    "collar", "pulsera", "pendientes", "colgante", "joya", "joyas",
    "ketting", "oorbellen", "sieraad", "sieraden",
    "pulseira", "brincos", "pingente", "joia", "joias"
]

FAKE_MARKERS = [
    # Français
    "style ", "façon ", "facon ", "genre ", "look ", "inspiré ", "inspire ", "dupe ", "copie ", "fausse ", "faux ", "imitation ", "réplique ", "replique ",
    # Italien
    "stile ", "tipo ", "ispirato ", "ispirata ", "copia ", "falso ", "falsa ", "imitazione ", "replica ",
    # Allemand
    "stil ", "inspiriert ", "kopie ", "fälschung ", "faelschung ", "imitat ", "replik ",
    # Espagnol
    "estilo ", "inspirado ", "inspirada ", "copia ", "falso ", "falsa ", "imitacion ", "imitación ", "replica ", "réplica ",
    # Néerlandais
    "stijl ", "geïnspireerd ", "geinspireerd ", "kopie ", "nep ", "imitatie ",
    # Portugais
    "estilo ", "inspirado ", "inspirada ", "cópia ", "copia ", "falso ", "falsa ", "imitação ", "imitacao ",
    # Anglais
    "inspired ", "lookalike ", "copy ", "fake ", "replica "
]

SATISFACTORY_STATUS_MARKERS = [
    # Français
    "satisfaisant",
    # Anglais
    "satisfactory",
    # Italien
    "abbastanza buono", "condizioni discrete", "discreto",
    # Allemand
    "zufriedenstellend", "akzeptabel",
    # Espagnol
    "satisfactorio", "en buen estado con defectos", "aceptable",
    # Néerlandais
    "bevredigend", "redelijk",
    # Portugais
    "satisfatório", "satisfatorio"
]

GENDER_KEYWORDS_MEN = [
    "homme", "hommes",
    "men", "mens", "man",
    "uomo", "uomini",
    "herren", "herrenmode", "mann", "männer",
    "hombre", "hombres", "caballero",
    "heren", "mannen",
    "homem", "homens"
]

GENDER_KEYWORDS_WOMEN = [
    "femme", "femmes",
    "women", "womens", "woman",
    "donna", "donne",
    "damen", "damenmode", "frau", "frauen",
    "mujer", "mujeres", "dama", "señora",
    "dames", "vrouwen",
    "mulher", "mulheres"
]

FEMALE_ONLY_PIECES = [
    "robe", "jupe", "skirt", "soutien-gorge", "bra", "talons", "escarpins",
    "abito", "vestito", "gonna", "reggiseno", "tacchi",
    "kleid", "rock", "bh", "high heels", "pumps",
    "vestido", "falda", "sujetador", "tacones",
    "jurk", "rok", "beha", "hakken",
    "saia", "sutiã", "saltos"
]
