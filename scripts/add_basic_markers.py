with open('src/filters.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '        for bi in BASIC_ITEMS_KEYWORDS:\n            if contains_whole_word(norm_title, bi):\n                return False, f"Pièce basique exclue (\'{bi}\')"'

replacement = target + '''

        basic_markers = ["basique", "basica", "básica", "basico", "básico", "simple", "semplice"]
        if any(contains_whole_word(norm_title, bm) for bm in basic_markers):
            cloth_markers = ["tshirt", "t-shirt", "tee", "top", "pull", "sweat", "jean", "jeans", "pantalon", "camicia", "chemise", "maglia", "camiseta"]
            if any(contains_whole_word(norm_title, cm) for cm in cloth_markers):
                return False, "Pièce explicitement qualifiée de basique / simple"'''

if target in text:
    text = text.replace(target, replacement)
    with open('src/filters.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Updated src/filters.py with basic_markers")
else:
    print("Target not found in src/filters.py")
