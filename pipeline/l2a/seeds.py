#!/usr/bin/env python3
"""
L2a Ingredient Seed Extractor
Scans all stage5_results.jsonl files and extracts unique ingredient seeds.
No LLM — pure Python normalization.
Output: ~/culinary-mind/output/l2a/ingredient_seeds.json
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
# Try new path first, fall back to old
_RECIPES_DIR = Path("/Users/jeff/culinary-mind/output/recipes")
_STAGE5_DIR = Path("/Users/jeff/culinary-mind/output/stage5_batch")
STAGE5_BASE = _RECIPES_DIR if _RECIPES_DIR.exists() else _STAGE5_DIR
OUTPUT_DIR  = Path("/Users/jeff/culinary-mind/output/l2a")
OUTPUT_FILE = OUTPUT_DIR / "ingredient_seeds.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Normalization helpers ─────────────────────────────────────────────────────

# Adjective/modifier words to strip (prefix descriptors)
STRIP_WORDS = {
    # freshness / prep state
    "fresh", "freshly", "dried", "dry", "frozen", "thawed", "raw", "cooked",
    "smoked", "cured", "candied", "pickled", "marinated", "blanched",
    "roasted", "toasted", "grilled", "fried", "deep-fried", "pan-fried",
    "steamed", "poached", "boiled", "baked", "braised", "sautéed", "sauteed",
    # cut / form
    "chopped", "minced", "diced", "sliced", "grated", "shredded", "julienned",
    "crushed", "ground", "whole", "halved", "quartered", "peeled", "pitted",
    "trimmed", "cleaned", "deboned", "skinless", "boneless", "butterflied",
    "cubed", "cut", "roughly", "finely", "thinly", "coarsely",
    # temperature / state
    "cold", "hot", "warm", "room-temperature", "chilled", "melted", "softened",
    # quality descriptors
    "large", "small", "medium", "extra", "thick", "thin", "young", "old",
    "ripe", "overripe", "mature", "aged", "mild", "strong", "sharp",
    "sweet", "sour", "spicy", "hot", "mild", "bitter",
    # colour
    "red", "green", "yellow", "white", "black", "dark", "light", "pale",
    "golden", "brown", "purple", "orange", "pink",
    # packaging
    "canned", "jarred", "bottled", "packaged", "prepared", "instant",
    "store-bought", "homemade", "powdered", "concentrate",
    # misc
    "good", "quality", "best", "premium", "organic", "wild", "cultivated",
    "domestic", "imported", "chinese", "japanese", "french", "italian",
    "american", "korean", "thai", "indian", "spanish", "greek", "mexican",
    "unsalted", "salted", "low-fat", "fat-free", "reduced", "full-fat",
    "heavy", "light", "double",
}

# Synonym map — maps variant → canonical
SYNONYM_MAP = {
    # Cream
    "whipping cream":           "heavy cream",
    "double cream":             "heavy cream",
    "thickened cream":          "heavy cream",
    "single cream":             "light cream",
    # Flour
    "all purpose flour":        "all-purpose flour",
    "ap flour":                 "all-purpose flour",
    "plain flour":              "all-purpose flour",
    "bread flour":              "bread flour",
    "cake flour":               "cake flour",
    # Sugar
    "granulated sugar":         "sugar",
    "white sugar":              "sugar",
    "table sugar":              "sugar",
    "caster sugar":             "sugar",
    "castor sugar":             "sugar",
    "superfine sugar":          "sugar",
    "powdered sugar":           "confectioners sugar",
    "icing sugar":              "confectioners sugar",
    # Butter
    "unsalted butter":          "butter",
    "salted butter":            "butter",
    "sweet cream butter":       "butter",
    # Eggs
    "egg":                      "eggs",
    "large egg":                "eggs",
    "whole egg":                "eggs",
    # Garlic
    "garlic clove":             "garlic",
    "garlic cloves":            "garlic",
    # Onion variants
    "yellow onion":             "onion",
    "white onion":              "onion",
    "brown onion":              "onion",
    "sweet onion":              "onion",
    "red onion":                "red onion",
    # Oil
    "extra virgin olive oil":   "olive oil",
    "extra-virgin olive oil":   "olive oil",
    "ev olive oil":             "olive oil",
    "evoo":                     "olive oil",
    "vegetable oil":            "neutral oil",
    "canola oil":               "neutral oil",
    "sunflower oil":            "neutral oil",
    "grapeseed oil":            "neutral oil",
    # Milk
    "whole milk":               "milk",
    "full-fat milk":            "milk",
    "2% milk":                  "milk",
    "skim milk":                "milk",
    # Salt
    "kosher salt":              "salt",
    "sea salt":                 "salt",
    "table salt":               "salt",
    "fine salt":                "salt",
    "fleur de sel":             "fleur de sel",   # keep specialty
    "maldon salt":              "maldon salt",
    # Pepper
    "black pepper":             "black pepper",
    "white pepper":             "white pepper",
    "ground black pepper":      "black pepper",
    "ground white pepper":      "white pepper",
    "freshly ground pepper":    "black pepper",
    "freshly ground black pepper": "black pepper",
    # Stock / broth
    "chicken stock":            "chicken stock",
    "chicken broth":            "chicken stock",
    "beef stock":               "beef stock",
    "beef broth":               "beef stock",
    "vegetable stock":          "vegetable stock",
    "vegetable broth":          "vegetable stock",
    "fish stock":               "fish stock",
    "fish broth":               "fish stock",
    "veal stock":               "veal stock",
    "veal broth":               "veal stock",
    # Lemon
    "lemon juice":              "lemon juice",
    "fresh lemon juice":        "lemon juice",
    "lime juice":               "lime juice",
    "fresh lime juice":         "lime juice",
    # Vinegar
    "red wine vinegar":         "red wine vinegar",
    "white wine vinegar":       "white wine vinegar",
    "balsamic vinegar":         "balsamic vinegar",
    "rice vinegar":             "rice vinegar",
    "rice wine vinegar":        "rice vinegar",
    # Soy / Chinese
    "soy sauce":                "soy sauce",
    "light soy sauce":          "light soy sauce",
    "dark soy sauce":           "dark soy sauce",
    "生抽":                      "生抽",
    "老抽":                      "老抽",
    # Misc
    "heavy whipping cream":     "heavy cream",
    "scallion":                 "scallions",
    "green onion":              "scallions",
    "spring onion":             "scallions",
    "cilantro":                 "cilantro",
    "coriander leaves":         "cilantro",
    "capsicum":                 "bell pepper",
    "bell peppers":             "bell pepper",
    "jalapeño":                 "jalapeño",
    "jalapeno":                 "jalapeño",
    "chilli":                   "chili",
    "chiles":                   "chili",
    "chile":                    "chili",
    "shallot":                  "shallots",
    "tomatoes":                 "tomato",
    "potatoes":                 "potato",
    "carrots":                  "carrot",
    "mushrooms":                "mushroom",
    "zucchini":                 "zucchini",
    "courgette":                "zucchini",
    "eggplant":                 "eggplant",
    "aubergine":                "eggplant",
    "heavy cream":              "heavy cream",
}

# Category guesses — keyword-based
CATEGORY_RULES = [
    # protein
    (r"\b(chicken|beef|pork|lamb|duck|turkey|veal|rabbit|venison|quail|"
     r"bacon|ham|prosciutto|pancetta|sausage|chorizo|salami|lard|"
     r"tofu|tempeh|seitan)\b",        "protein"),
    # seafood
    (r"\b(fish|salmon|tuna|cod|halibut|sea bass|snapper|trout|"
     r"shrimp|prawn|lobster|crab|scallop|mussel|clam|oyster|squid|octopus|"
     r"anchov|sardine|mackerel|herring|tilapia|crayfish|langoustine)\b", "seafood"),
    # dairy
    (r"\b(butter|cream|milk|cheese|yogurt|yoghurt|crème|creme|"
     r"mascarpone|ricotta|parmesan|mozzarella|brie|cheddar|gouda|"
     r"gruyère|gruyere|ghee|kefir|whey|casein|lactose)\b", "dairy"),
    # egg
    (r"\b(eggs?|yolk|egg white|whole egg)\b",  "dairy"),  # group with dairy
    # grain / starch
    (r"\b(flour|bread|rice|pasta|noodle|wheat|rye|barley|oat|cornmeal|"
     r"polenta|semolina|starch|tapioca|arrowroot|quinoa|farro|spelt|"
     r"millet|buckwheat|bran|gluten)\b", "grain"),
    # vegetable
    (r"\b(onion|garlic|shallot|leek|carrot|celery|potato|tomato|"
     r"spinach|lettuce|cabbage|kale|broccoli|cauliflower|asparagus|"
     r"artichoke|beet|turnip|parsnip|fennel|zucchini|eggplant|pepper|"
     r"cucumber|radish|daikon|bok choy|scallion|chive|corn|peas?|"
     r"bean|lentil|chickpea|edamame|mushroom|truffle|kohlrabi|"
     r"celeriac|endive|watercress|arugula|radicchio)\b", "vegetable"),
    # fruit
    (r"\b(apple|pear|lemon|lime|orange|grapefruit|berry|strawberry|"
     r"raspberry|blueberry|blackberry|cherry|grape|plum|peach|nectarine|"
     r"mango|pineapple|papaya|banana|coconut|avocado|fig|date|pomegranate|"
     r"passion fruit|passionfruit|kiwi|melon|watermelon|apricot|"
     r"quince|persimmon|lychee|longan)\b", "fruit"),
    # fat / oil
    (r"\b(oil|fat|lard|shortening|dripping|suet|tallow|margarine)\b", "fat_oil"),
    # seasoning / condiment
    (r"\b(salt|pepper|sugar|vinegar|soy sauce|fish sauce|oyster sauce|"
     r"miso|tamari|worcestershire|tabasco|sriracha|hoisin|ketchup|mustard|"
     r"mayo|mayonnaise|stock|broth|wine|sake|mirin|sherry|brandy|"
     r"rum|vodka|gin|whisky|whiskey|beer|vermouth|liqueur|"
     r"honey|maple syrup|molasses|corn syrup|agave)\b", "seasoning"),
    # herbs / spice
    (r"\b(herb|spice|basil|oregano|thyme|rosemary|sage|parsley|dill|"
     r"tarragon|mint|bay leaf|coriander|cumin|paprika|turmeric|saffron|"
     r"cinnamon|clove|nutmeg|cardamom|star anise|fennel seed|caraway|"
     r"allspice|chili flake|cayenne|ginger|galangal|lemongrass|"
     r"vanilla|sumac|za'atar|ras el hanout|five.spice)\b", "herb_spice"),
    # nuts / seeds
    (r"\b(almond|walnut|pecan|pistachio|hazelnut|cashew|peanut|macadamia|"
     r"pine nut|sesame|sunflower seed|pumpkin seed|flaxseed|chia|poppy)\b", "nut_seed"),
    # baking
    (r"\b(yeast|baking powder|baking soda|gelatin|gelatine|agar|pectin|"
     r"lecithin|cocoa|chocolate|cacao|malt|dextrose|glucose|fructose|"
     r"xanthan|guar gum|carrageenan)\b", "baking"),
]

COMPILED_RULES = [(re.compile(pat, re.IGNORECASE), cat) for pat, cat in CATEGORY_RULES]


def is_chinese(text: str) -> bool:
    """Return True if string contains any CJK characters."""
    return bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))


def guess_category(item: str) -> str:
    for pat, cat in COMPILED_RULES:
        if pat.search(item):
            return cat
    return "other"


def normalize_item(raw: str) -> str:
    """Normalise an ingredient string to a canonical form."""
    s = raw.strip()
    if not s:
        return ""

    # Don't aggressively normalise Chinese text — just strip whitespace
    if is_chinese(s):
        return s.strip()

    s = s.lower()

    # Remove parenthetical notes: "cream (heavy)" → "cream"
    s = re.sub(r'\(.*?\)', '', s)

    # Remove trailing punctuation / numbers
    s = re.sub(r'[,;:.!?*]+$', '', s)

    # Replace hyphens used as separators with space (but keep compound words)
    # e.g. "all-purpose" should stay, "fresh-chopped" → "fresh chopped"
    # Heuristic: hyphen between known modifier and word → space
    s = re.sub(r'\b(freshly|roughly|finely|thinly|coarsely|lightly|well|tightly)-', r'\1 ', s)

    # Tokenize and strip leading modifier words
    tokens = s.split()
    # Strip leading strip-words (up to last 2 tokens — always keep at least 1)
    while len(tokens) > 1 and tokens[0] in STRIP_WORDS:
        tokens = tokens[1:]

    s = " ".join(tokens).strip()

    # Final cleanup
    s = re.sub(r'\s{2,}', ' ', s)
    s = s.strip(" ,;:")

    # Apply synonym map
    s = SYNONYM_MAP.get(s, s)

    return s


# ── Main extraction ───────────────────────────────────────────────────────────

def extract_all():
    # ingredient → {count, books_set}
    freq: dict[str, int] = defaultdict(int)
    books_map: dict[str, set] = defaultdict(set)
    # raw_to_normalized cache
    norm_cache: dict[str, str] = {}

    total_recipes = 0
    total_mentions_raw = 0
    books_processed = []
    books_with_jsonl = []

    jsonl_files = sorted(STAGE5_BASE.glob("*/stage5_results.jsonl"))
    print(f"Found {len(jsonl_files)} stage5_results.jsonl files")

    for jsonl_path in jsonl_files:
        book_id = jsonl_path.parent.name
        books_with_jsonl.append(book_id)
        book_recipes = 0
        book_mentions = 0

        with open(jsonl_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                for recipe in obj.get("recipes") or []:
                    has_ingredients = False
                    for ing in recipe.get("ingredients") or []:
                        raw_item = ing.get("item") or ""
                        if not raw_item.strip():
                            continue
                        total_mentions_raw += 1
                        book_mentions += 1
                        has_ingredients = True

                        if raw_item not in norm_cache:
                            norm_cache[raw_item] = normalize_item(raw_item)
                        normalized = norm_cache[raw_item]
                        if not normalized:
                            continue

                        freq[normalized] += 1
                        books_map[normalized].add(book_id)

                    if has_ingredients or recipe.get("name"):
                        total_recipes += 1
                        book_recipes += 1

        if book_recipes > 0:
            books_processed.append(book_id)
        print(f"  {book_id}: {book_recipes} recipes, {book_mentions} ingredient mentions")

    print(f"\nTotal: {total_recipes} recipes, {total_mentions_raw} raw mentions, "
          f"{len(freq)} unique normalized ingredients")

    # Sort by frequency desc
    sorted_items = sorted(freq.items(), key=lambda x: x[1], reverse=True)

    # Build output
    ingredients_list = []
    for item, count in sorted_items:
        ingredients_list.append({
            "item": item,
            "item_zh": item if is_chinese(item) else None,
            "frequency": count,
            "category_guess": guess_category(item),
            "books": sorted(books_map[item]),
        })

    # Top 50 log
    print("\n── Top 50 ingredients ──")
    for i, entry in enumerate(ingredients_list[:50], 1):
        print(f"  {i:3}. {entry['item']:<35} {entry['frequency']:>5}  [{entry['category_guess']}]")

    # Category summary
    cat_count: dict[str, int] = defaultdict(int)
    for entry in ingredients_list:
        cat_count[entry["category_guess"]] += 1
    print("\n── Category distribution ──")
    for cat, cnt in sorted(cat_count.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat:<20} {cnt}")

    output = {
        "total_unique": len(freq),
        "total_mentions": total_mentions_raw,
        "extracted_from_books": len(books_with_jsonl),
        "extracted_from_recipes": total_recipes,
        "category_summary": dict(sorted(cat_count.items(), key=lambda x: x[1], reverse=True)),
        "ingredients": ingredients_list,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        json.dump(output, out, ensure_ascii=False, indent=2)

    print(f"\nOutput written to: {OUTPUT_FILE}")
    print(f"File size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")

    return output


if __name__ == "__main__":
    extract_all()
