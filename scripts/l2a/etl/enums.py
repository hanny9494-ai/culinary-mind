"""P1-13~16 Option D Hybrid: shared enums + known lists for hard-prune.

Per architect 047 + GPT 5.5 review verdict: deterministic Python tasks
(amino acid lookup / null check / brand pattern matching) belong here,
not in the LLM prompt.

`prefilter.py` reads KNOWN_* lists for hard-prune categorisation.
`post_normalizer.py` reads ISSUE_CODE_SYNONYMS to canonicalise LLM output.
"""
from __future__ import annotations

from enum import Enum


class TreeStatus(str, Enum):
    ACTIVE = "active"
    EXCLUDED = "excluded"
    NEEDS_REVIEW = "needs_review"
    IDENTITY_CONFLICT = "identity_conflict"


class FormType(str, Enum):
    SPECIES = "species"
    VARIETY = "variety"
    PART = "part"
    PROCESSED = "processed"
    COMPOSITE = "composite"
    AMBIGUOUS = "ambiguous"


class ExclusionReason(str, Enum):
    CHEMICAL = "chemical"
    DATA_INCOMPLETE = "data_incomplete"
    BRAND = "brand"
    BABYFOOD = "babyfood"
    ABSTRACT = "abstract"
    NOISE = "noise"  # cc-lead decision 4: 统一短名
    OTHER = "other"  # post_normalizer fallback when LLM emits excluded without reason


class IssueCode(str, Enum):
    """Canonical issue codes — post_normalizer maps synonyms to these."""

    # Identity / contamination
    ZH_SCI_MISMATCH = "zh_sci_mismatch"
    CUISINE_DEEP_TAXON_MISMATCH = "cuisine_deep_taxon_mismatch"
    HEAVY_CROSS_CONTAMINATION = "heavy_cross_contamination"
    L0_PRINCIPLES_TAXON_MISMATCH = "l0_principles_taxon_mismatch"
    QUALITY_INDICATORS_TAXON_MISMATCH = "quality_indicators_taxon_mismatch"
    CANONICAL_ID_AMBIGUITY = "canonical_id_ambiguity"

    # Hard-prune categories (short canonical names per cc-lead decision 4)
    CHEMICAL = "chemical"
    DATA_INCOMPLETE = "data_incomplete"
    NOISE = "noise"
    BRAND = "brand"
    BABYFOOD = "babyfood"

    # Soft signals
    SUSPECT = "suspect"
    SCIENTIFIC_NAME_CORRECTED_TO_TAXON = "scientific_name_corrected_to_taxon"
    MALFORMED_CUISINE_DEEP_NESTING_CORRECTED = "malformed_cuisine_deep_nesting_corrected"
    COMPOSITION_SUM_BELOW_90_DUE_TO_ETHANOL = "composition_sum_below_90_due_to_ethanol"
    COMPOSITION_IMPLAUSIBLE = "composition_implausible"
    CHIMERA_NODE = "chimera_node"


# Synonym mapping — post_normalizer rewrites these into canonical short names
ISSUE_CODE_SYNONYMS: dict[str, str] = {
    "noise_excluded": "noise",
    "chemical_monomer_excluded": "chemical",
    "data_incomplete_excluded": "data_incomplete",
    "brand_excluded": "brand",
    "babyfood_excluded": "babyfood",
    "ambiguous_canonical_id": "canonical_id_ambiguity",
    "structural_nesting_resolved": "malformed_cuisine_deep_nesting_corrected",
    "malformed_cuisine_deep_hierarchy_fixed": "malformed_cuisine_deep_nesting_corrected",
    "deep_cuisine_nesting_corrected": "malformed_cuisine_deep_nesting_corrected",
    "abstract_excluded": "noise",
}


# Canonical id → exclusion (deterministic, never goes through LLM)
KNOWN_AMINO_ACIDS: frozenset[str] = frozenset({
    # 20 standard
    "alanine", "arginine", "asparagine", "aspartic_acid", "cysteine",
    "glutamic_acid", "glutamine", "glycine", "histidine", "isoleucine",
    "leucine", "lysine", "methionine", "phenylalanine", "proline",
    "serine", "threonine", "tryptophan", "tyrosine", "valine",
    # selenoproteinogenic / pyrrolysine / non-proteinogenic but commonly listed
    "selenocysteine", "pyrrolysine", "ornithine", "taurine", "citrulline",
    # related amino-derivatives sometimes leaking into food atoms
    "creatine", "carnitine", "carnosine", "anserine",
    "glucosamine", "n_acetyl_glucosamine", "n-acetyl-glucosamine",
})

KNOWN_PURE_CHEMICALS: frozenset[str] = frozenset({
    # Organic acids
    "ascorbic_acid", "citric_acid", "lactic_acid", "acetic_acid", "oxalic_acid",
    "tartaric_acid", "malic_acid", "fumaric_acid", "succinic_acid", "phytic_acid",
    "benzoic_acid", "sorbic_acid", "propionic_acid", "butyric_acid",
    # Sugars / sugar alcohols
    "fructose", "glucose", "sucrose", "lactose", "maltose", "galactose",
    "mannose", "xylose", "ribose", "arabinose", "trehalose",
    "sorbitol", "mannitol", "xylitol", "erythritol",
    # Vitamins (single chemicals, not food sources)
    "vitamin_a", "vitamin_b1", "vitamin_b2", "vitamin_b6", "vitamin_b12",
    "vitamin_c", "vitamin_d", "vitamin_d2", "vitamin_d3", "vitamin_e",
    "vitamin_k", "vitamin_k1", "vitamin_k2",
    "thiamin", "riboflavin", "niacin", "biotin", "folate", "folic_acid",
    "pantothenic_acid", "pyridoxine", "cobalamin",
    # Single fatty acids when present as canonical_id
    "oleic_acid", "linoleic_acid", "linolenic_acid", "palmitic_acid",
    "stearic_acid", "arachidonic_acid", "eicosapentaenoic_acid", "docosahexaenoic_acid",
})


# Slug regex patterns (each list item is a Python regex applied to canonical_id.lower())
KNOWN_BRAND_PATTERNS: list[str] = [
    # architect 048 narrow — leading digit only matches known brand formats,
    # not generic descriptive numbers (e.g. 100_percent_chocolate).
    r"^\d+_grand(_bar)?$",   # 100_grand, 100_grand_bar
    r"^\d_musketeers",       # 3_musketeers, 3_musketeers_bar
    r"^\dth_avenue",         # 5th_avenue_candy_bar
    r"^\d+up$",              # 7up
    r"_candy_bar$",          # foo_candy_bar (typical brand suffix)
    r"_chocolate_bar$",      # foo_chocolate_bar
    r"_grand$",              # _grand
    r"_brand$",              # x_brand (anchored: avoids brandy / brandaris)
    r"^after_eight",         # after_eight (mint chocolate)
    r"_kit_kat",             # kit kat
    r"^kit_kat",
    r"^lay'?s_",             # lay's chips
    r"^doritos",
    r"^pringles",
    r"^cheez_it",
    r"^oreo(s|_|$)",         # oreo, oreos, oreo_ (NOT oreochromis_*)
    r"^pop_tart",
]

KNOWN_TIME_PERIOD_PATTERNS: list[str] = [
    r"_century$",
    r"^\d+(st|nd|rd|th)_century",
    r"^\d{4}s$",             # 1990s
    r"_period$",
    r"_era$",
    r"^modern_",
    r"^medieval_",
    r"^ancient_",
]

KNOWN_BABYFOOD_PATTERNS: list[str] = [
    r"^babyfood_",
    r"_baby_food$",
    r"_infant_",
    r"^infant_",
    r"^toddler_",
    r"_toddler_",
]


# Cultivars where scientific_name MAY include a cultivar suffix
# (post_normalizer / prompt should not strip these)
KNOWN_CULTIVAR_EXCEPTIONS: frozenset[str] = frozenset({
    "bresse_chicken",
    "russet_potato",
    "fuji_apple",
    "honeycrisp_apple",
    "kobe_beef",
    "wagyu_beef",
    "iberico_pork",
    "bordeaux_grape",
})
