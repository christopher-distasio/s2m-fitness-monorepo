"""
Shared Vitamin A / Folate / Vitamin D provenance rules for USDA processors.

Applied after raw nutrient IDs are loaded into a food dict. Mutates in place.
"""

VITAMIN_D_IU_TO_MCG = 40.0  # FDA example: 800 IU → 20 mcg


def apply_micronutrient_provenance(food: dict) -> None:
    """
    Tag preferred micronutrient fields with provenance and apply allowed
    fallbacks/conversions.

    Vitamin A: never convert IU→RAE (FDA factors vary by source; USDA does
    not indicate source). Prefer measured RAE; otherwise leave RAE null.

    Folate: prefer DFE; if only Total is present, copy Total into
    folate_dfe_mcg and tag as fallback.

    Vitamin D: prefer mcg; if only IU is present, convert IU/40 → mcg.
    """
    # --- Vitamin A ---
    rae = food.get("vitamin_a_rae_mcg")
    iu = food.get("vitamin_a_iu")
    if rae is not None:
        food["vitamin_a_source"] = "measured_rae"
    elif iu is not None:
        food["vitamin_a_rae_mcg"] = None
        food["vitamin_a_source"] = "unsupported_conversion"
    else:
        food["vitamin_a_rae_mcg"] = None
        food["vitamin_a_source"] = "no_data"

    # --- Folate ---
    dfe = food.get("folate_dfe_mcg")
    total = food.get("folate")
    if dfe is not None:
        food["folate_source"] = "measured_dfe"
    elif total is not None:
        food["folate_dfe_mcg"] = total
        food["folate_source"] = "fallback_from_total"
    else:
        food["folate_dfe_mcg"] = None
        food["folate_source"] = "no_data"

    # --- Vitamin D ---
    mcg = food.get("vitamin_d_mcg")
    vit_d_iu = food.get("vitamin_d_iu")
    if mcg is not None:
        food["vitamin_d_source"] = "measured_mcg"
    elif vit_d_iu is not None:
        food["vitamin_d_mcg"] = round(float(vit_d_iu) / VITAMIN_D_IU_TO_MCG, 2)
        food["vitamin_d_source"] = "converted_from_iu"
    else:
        food["vitamin_d_mcg"] = None
        food["vitamin_d_source"] = "no_data"
