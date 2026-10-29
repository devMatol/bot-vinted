import sys
sys.path.insert(0, '.')
from scripts.add_brands_celine_fendi_coach_longchamp import COACH_BENCHMARKS, LONGCHAMP_BENCHMARKS

path = 'src/scoring/resale_knowledge.py'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

if '"Coach": {' not in c:
    add_lines = []
    for brand_name, benchmarks in [('Coach', COACH_BENCHMARKS), ('Longchamp', LONGCHAMP_BENCHMARKS)]:
        add_lines.append(f'    "{brand_name}": {{')
        for cat, vals in benchmarks.items():
            min_f, target, max_h, desc = vals
            add_lines.append(f'        "{cat}": ({min_f}, {target}, {max_h}, "{desc}"),')
        add_lines.append('    },')

    addition = '\n'.join(add_lines) + '\n\n'
    target = '    # ==========================================\n    # TIER 1 : DIFFUSION & CONTEMPORARY PREMIUM'
    c = c.replace(target, addition + target)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(c)
    print('Updated CURATED_RESALE_BENCHMARKS in src/scoring/resale_knowledge.py')
else:
    print('Coach already present in src/scoring/resale_knowledge.py')
