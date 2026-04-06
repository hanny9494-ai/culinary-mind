#!/usr/bin/env python3
import argparse, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
L2A_DIR = ROOT / 'output' / 'l2a'
L2C_DIR = ROOT / 'output' / 'l2c'
INPUT_FILE = L2A_DIR / 'canonical_map_merged.json'
OUTPUT_CLEAN = L2A_DIR / 'canonical_map_clean.json'
OUTPUT_COMMERCIAL = L2C_DIR / 'commercial_ingredients.json'
OUTPUT_REPORT = L2A_DIR / 'clean_report.json'

JUNK_KEYWORDS = [
    'proximates', 'minerals', 'fatty_acids', 'niacin', 'thiamin',
    'riboflavin', 'folate', 'vitamin', 'amino_acid', 'moisture',
    'ash_content', 'nitrogen', 'measure', 'sample', 'rep_',
    'laboratory', 'calorie', 'energy',
]

BRAND_NAMES = [
    'KRAFT', 'PILLSBURY', 'OSCAR MAYER', 'HORMEL', 'CAMPBELL',
    'GERBER', 'GREAT VALUE', 'KROGER', 'SAFEWAY', 'SHOP RITE',
    'MCDONALD', 'BURGER KING', 'TYSON', 'PERDUE', 'STOUFFER',
    'LEAN CUISINE', 'HEALTHY CHOICE', 'NABISCO', 'KELLOGG',
    'GENERAL MILLS', 'QUAKER', 'HEINZ', 'BUMBLE BEE', 'DOLE',
    'BIRDS EYE', 'GREEN GIANT', 'BETTY CROCKER',
]

_junk_re = re.compile('|'.join(re.escape(k) for k in JUNK_KEYWORDS), re.IGNORECASE)
_brand_re = re.compile('|'.join(re.escape(b) for b in BRAND_NAMES), re.IGNORECASE)
MAX_VARIANTS = 50
KEEP_VARIANTS = 5


def is_junk(entry):
    return bool(_junk_re.search(entry['canonical_id']))


def is_brand_canonical(entry):
    return bool(_brand_re.search(entry['canonical_id']))


def strip_brand_variants(entry):
    variants = entry.get('raw_variants', [])
    kept = [v for v in variants if not _brand_re.search(v)]
    stripped = len(variants) - len(kept)
    if stripped > 0:
        entry['raw_variants'] = kept if kept else variants[:1]
    return stripped


def trim_variants(entry):
    variants = entry.get('raw_variants', [])
    if len(variants) <= MAX_VARIANTS:
        return 0
    original = len(variants)
    entry['raw_variants'] = sorted(variants, key=len)[:KEEP_VARIANTS]
    return original - KEEP_VARIANTS


def main():
    parser = argparse.ArgumentParser(description='Clean L2a canonical map')
    parser.add_argument('--dry-run', action='store_true', help='Only report')
    args = parser.parse_args()

    data = json.loads(INPUT_FILE.read_text())
    metadata = data['metadata']
    canonicals = data['canonicals']
    total = len(canonicals)

    clean, commercial, junk_removed = [], [], []
    trimmed_count = 0
    brand_variants_stripped = 0

    for entry in canonicals:
        if is_junk(entry):
            junk_removed.append(entry['canonical_id'])
            continue
        if is_brand_canonical(entry):
            commercial.append(entry)
            continue
        brand_variants_stripped += strip_brand_variants(entry)
        trimmed = trim_variants(entry)
        if trimmed > 0:
            trimmed_count += 1
        clean.append(entry)

    report = {
        'input_total': total,
        'junk_removed': len(junk_removed),
        'moved_to_l2c': len(commercial),
        'brand_variants_stripped': brand_variants_stripped,
        'variants_trimmed': trimmed_count,
        'clean_remaining': len(clean),
        'junk_sample': junk_removed[:20],
        'l2c_sample': [e['canonical_id'] for e in commercial[:20]],
    }

    print(f'Input:            {total}')
    print(f'Junk removed:     {len(junk_removed)}')
    print(f'Moved to L2c:     {len(commercial)}')
    print(f'Brand vars strip: {brand_variants_stripped}')
    print(f'Variants trimmed: {trimmed_count}')
    print(f'Clean remaining:  {len(clean)}')

    if args.dry_run:
        print()
        print('[DRY RUN] No files written.')
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    L2C_DIR.mkdir(parents=True, exist_ok=True)

    clean_data = {
        'metadata': {**metadata, 'total_canonical': len(clean), 'cleaned_from': total, 'junk_removed': len(junk_removed), 'moved_to_l2c': len(commercial)},
        'canonicals': clean,
    }
    OUTPUT_CLEAN.write_text(json.dumps(clean_data, indent=2, ensure_ascii=False))
    print(f'Wrote {OUTPUT_CLEAN}')

    commercial_data = {
        'metadata': {'total': len(commercial), 'source': 'l2a_clean_canonicals.py', 'from_file': str(INPUT_FILE.name)},
        'ingredients': commercial,
    }
    OUTPUT_COMMERCIAL.write_text(json.dumps(commercial_data, indent=2, ensure_ascii=False))
    print(f'Wrote {OUTPUT_COMMERCIAL}')

    OUTPUT_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f'Wrote {OUTPUT_REPORT}')


if __name__ == '__main__':
    main()
