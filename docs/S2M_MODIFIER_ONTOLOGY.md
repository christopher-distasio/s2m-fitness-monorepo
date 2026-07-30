# S2M Modifier Ontology
## Complete merged framework from ChatGPT + Gemini + Claude

---

## 1. COOKING METHOD
**Mutually exclusive within this category**

### Raw/Uncooked
- **Canonical:** `COOKING_RAW`
- USDA terms: raw, unheated, unprepared, from raw, sprouted
- Voice equivalents: "fresh", "uncooked", "uncooked weight", "straight from the package", "raw"
- Notes: Highest calorie relevance (no cooking loss)

### Dry Heat
- **Canonical:** `COOKING_DRY`
- USDA terms: dry heat, roasted, toasted, dry roasted, baked or broiled
- Voice equivalents: "oven roasted", "baked in the oven", "toasted"
- Mutually exclusive with: moist heat, oil/fat, oven (when oven used alone)

### Moist Heat
- **Canonical:** `COOKING_MOIST`
- USDA terms: boiled, steamed, stewed, braised, simmered, poached
- Voice equivalents: "slow cooked", "slow braised", "simmered", "boiled"
- Mutually exclusive with: dry heat, oil/fat

### Oil/Fat Heat
- **Canonical:** `COOKING_FAT`
- USDA terms: fried, pan-fried, sautéed, grilled, pan-broiled, oil roasted
- Voice equivalents: "pan fried", "deep fried", "air fried", "crispy", "skillet fried", "cooked in a pan"
- Mutually exclusive with: dry heat, moist heat

### Smoke/Slow
- **Canonical:** `COOKING_SMOKE`
- USDA terms: smoked, rotisserie
- Voice equivalents: "rotisserie chicken", "smoked"

### Oven (standalone)
- **Canonical:** `COOKING_OVEN`
- USDA terms: baked, broiled
- Voice equivalents: "broiled", "under the broiler", "baked"
- Mutually exclusive with: dry heat, oil/fat (when explicit)

### Special Methods
- **Canonical:** `COOKING_SPECIAL`
- USDA terms: microwaved
- Voice equivalents: "nuked"

---

## 2. PREP STATE (Before Cooking/Serving)
**Non-exclusive; multiple can apply**

### Fresh vs Processed
- **Canonical:** `PREP_FORM`
- Fresh: fresh, raw
- Frozen: frozen, from frozen
- Canned: canned, from canned
- Dried: dried, from dried, dry
- Bottled: bottled
- Condensed: condensed
- Powder: powder
- Voice equivalents: "frozen", "canned", "jarred", "bottled", "dehydrated", "freeze dried"

### Ready-to-Eat States
- **Canonical:** `PREP_READY`
- USDA terms: ready-to-eat, ready-to-heat, ready-to-drink, ready-to-feed
- Voice equivalents: "ready made", "heat and serve"

### Reconstitution State
- **Canonical:** `PREP_RECONSTITUTE`
- USDA terms: reconstituted, not reconstituted, instant
- Voice equivalents: "mixed with water", "mixed with milk", "reconstituted"
- Prepared with: prepared with water, prepared with equal volume water, prepared with whole milk, made with tap/bottled/baby water
- Voice equivalents: "made with water", "made with milk", "almond milk", "oat milk", "soy milk"

### Drained vs Liquid-Included
- **Canonical:** `PREP_LIQUID`
- Drained: drained, drained solids, strained
- With liquid: (implicit default for canned fruit in syrup)
- Voice equivalents: "drained", "drained well", "strain it", "liquid included"
- Notes: Critical for canned fruit — syrup = +40-60 cal per serving

---

## 3. FAT TRIM & CONTENT
**Mutually exclusive trim levels; fat reduction overlaps with added fat**

### Meat Trim Level
- **Canonical:** `FAT_TRIM`
- USDA terms: separable lean only, separable lean and fat, separable fat, trimmed to 0" fat, trimmed to 1/8" fat, trimmed to 1/4" fat
- Voice equivalents: "fat trimmed", "trimmed", "extra lean", "lean only", "fat left on"
- Notes: Direct USDA categories; use as-is for re-ranking

### Fat Reduction (Overall)
- **Canonical:** `FAT_LEVEL`
- No added fat: no added fat
- Reduced: reduced fat, low fat, light, low calorie
- Fat-free: fat-free, nonfat
- Voice equivalents: "skim", "lean", "lite", "reduced fat", "half fat", "no fat"

### Added Fat During Cooking
- **Canonical:** `FAT_ADDED`
- None: no added fat, dry cooked
- Oil: cooked with oil, made with oil, oil roasted
- Butter: cooked with butter or margarine, made with butter, made with margarine
- Voice equivalents: "cooked in oil", "sautéed in butter", "olive oil", "vegetable oil", "canola oil", "buttered", "air fried"

---

## 4. SKIN & COATING
**Mutually exclusive**

### Skin Inclusion
- **Canonical:** `SKIN_STATUS`

#### Skin ON
- USDA terms: meat and skin, skin eaten, skin / coating eaten
- Voice equivalents: "with skin", "skin on", "ate the skin", "crispy skin"

#### Skin OFF
- USDA terms: meat only, skin not eaten, skin / coating not eaten, skin and breading removed
- Voice equivalents: "skinless", "no skin", "took the skin off", "peeled the skin", "without skin"

### Breading/Coating
- **Canonical:** `COATING_STATUS`
- Breaded: breaded, coated
- Unbreaded: skin and breading removed
- Voice equivalents: "battered", "breaded", "crispy coating", "batter fried"

---

## 5. SALT & SODIUM
**Mutually exclusive**

- **Canonical:** `SODIUM_LEVEL`

### No Added Salt
- USDA terms: no salt added, without salt, without salt added, unsalted
- Voice equivalents: "unsalted", "no salt", "didn't add salt"

### Added Salt
- USDA terms: with salt, with salt added, salted
- Voice equivalents: "salted", "added salt", "seasoned with salt"

### Reduced Sodium
- USDA terms: reduced sodium, low sodium
- Voice equivalents: "less salt", "lower sodium", "low sodium"

---

## 6. SUGAR & SWEETENING
**Mutually exclusive**

- **Canonical:** `SWEETNESS_LEVEL`

### No Added Sugar
- USDA terms: unsweetened, sugar-free, no sugar added, reduced sugar, diet
- Voice equivalents: "sugar free", "no sugar", "lightly sweetened", "diet", "zero sugar", "black" (for coffee/tea)

### Added Sweetener
- USDA terms: sweet, sweetened, flavored
- Voice equivalents: "sweetened", "with sugar"

### Sweetener Type (Missing but user-relevant)
- Examples: honey, maple syrup, artificial sweetener, stevia
- Voice equivalents: "honey sweetened", "maple syrup", "stevia"

---

## 7. GRAIN TYPE
**Mutually exclusive**

- **Canonical:** `GRAIN_TYPE`

### Whole Grain
- USDA terms: whole, whole grain, whole wheat, multigrain
- Voice equivalents: "wheat", "whole wheat", "whole grain"

### Refined (implicit default)
- USDA terms: (no explicit marker in data)
- Voice equivalents: "white flour", "white bread"

### Gluten-Free
- USDA terms: gluten-free, gluten free
- Voice equivalents: "gluten free", "GF"

---

## 8. SAUCE / LIQUID / BINDING
**Non-exclusive; multiple can apply**

- **Canonical:** `SAUCE_PROFILE`

### No Sauce/Dressing
- USDA terms: plain, no sauce, no dressing
- Voice equivalents: "dry", "sauce on the side", "plain", "no toppings"

### With Sauce/Gravy
- USDA terms: gravy, with gravy, tomato-based sauce, with tomato sauce, with cream sauce, soy-based sauce, with high vitamin c
- Voice equivalents: "smothered in", "drenched in", "with sauce", "brown gravy", "white gravy", "alfredo", "marinara", "soy sauce", "teriyaki", "barbecue sauce"

### With Toppings/Add-ins
- USDA terms: with meat, meatless, with vegetables, with beans, with fruit, with raisins, with carrots, cheese-filled, cream, whipped cream
- Voice equivalents: "veggie", "vegetarian", "meat lovers", "extra cheese", "raisins", "fruit", "carrots"

### Liquid for Cooking/Preparation
- **Canonical:** `LIQUID_MEDIUM`
- Water: cooked with water, prepared with water, prepared with equal volume water, made with tap water, made with bottled water, made with baby water
- Milk: prepared with whole milk, made with milk, made with non-dairy milk
- Oil/fat: cooked with oil, cooked with butter or margarine, made with oil, made with butter, made with margarine
- Voice equivalents: "cooked in oil", "made with water", "made with milk", "almond milk", "oat milk", "soy milk"

---

## 9. FORM / TEXTURE
**Mutually exclusive**

- **Canonical:** `PHYSICAL_FORM`

### Whole/Intact
- USDA terms: whole
- Voice equivalents: "whole"

### Divided
- USDA terms: ground, chopped, mashed, scrambled, strained
- Voice equivalents: "minced", "chopped", "powdered", "mashed", "puree", "sliced deli meat"

### Beverage Texture
- USDA terms: liquid, brewed, iced, hot
- Voice equivalents: "iced coffee", "hot coffee", "brewed"

---

## 10. SOURCE / ORIGIN
**Mutually exclusive; affects macro/micro assumptions**

- **Canonical:** `SOURCE_TYPE`

### Commercial
- USDA terms: from fast food, from restaurant, from fast food / restaurant, from school lunch
- Voice equivalents: "restaurant", "takeout", "drive-thru", "deli", "cafeteria", "school lunch"

### Home-Cooked
- USDA terms: home recipe, prepared from recipe, prepared-from-recipe
- Voice equivalents: "homemade", "homemade recipe", "made up", "prepared"

### Pre-Made/Preserved
- USDA terms: from fresh, from frozen, from canned, from dried, from raw
- Voice equivalents: "from the store", "pre-made"

### Enriched/Fortified
- USDA terms: enriched
- Notes: Matters for micronutrient tracking (especially cereals)

---

## 11. TEMPERATURE
**Non-exclusive; beverage-specific but affects satiation**

- **Canonical:** `TEMPERATURE`
- Hot: hot
- Cold: iced
- Room temperature: (implicit default)
- Voice equivalents: "hot coffee", "iced coffee", "cold brew"
- Notes: Affects perceived portion size for beverages; cold versions may be consumed slower

---

## MISSING CATEGORIES (User-Relevant but Rare in USDA Data)
**Worth adding; users will ask for these via voice**

### Sourcing/Quality
- Examples: organic, grass-fed, pasture-raised, wild-caught, farm-raised, hormone-free, antibiotic-free
- Canonical: `SOURCE_QUALITY`
- Voice equivalents: "organic", "grass-fed", "wild caught"

### Meat Cut/Part (Beyond Skin)
- Examples: dark meat, white meat, ground meat, whole cut, thigh, breast, wing
- Canonical: `MEAT_PART`
- Voice equivalents: "breast", "thigh", "wing", "dark meat", "white meat"
- Notes: Your data has "dark meat" at frequency 36 (SR Legacy); add "white meat" explicitly

### Doneness (Edge Case)
- Examples: rare, medium-rare, medium, medium-well, well-done
- Canonical: `DONENESS`
- Voice equivalents: "rare", "medium rare", "well done"
- Notes: User speech common; calorie impact minimal except for very rare/raw, where treated as `COOKING_RAW`

### Cooking Oil/Fat Type (Edge Case)
- Examples: olive oil, avocado oil, beef tallow, bacon grease, coconut oil
- Canonical: `FAT_TYPE`
- Voice equivalents: "olive oil", "avocado oil", "coconut oil", "bacon grease"
- Notes: Macro profile affects tracking; defer to Phase 2

### Portion/Slice Thickness (Edge Case)
- Examples: thin sliced, thick sliced, diced, chunked, minced, shredded, julienned
- Canonical: `THICKNESS`
- Voice equivalents: "thick cut", "thin slice", "extra large", "jumbo", "bite-sized", "double portion"
- Notes: Affects logging precision; consider for Phase 2

---

## NOISE TO REMOVE (Not True Modifiers)
**Do NOT include in re-ranking dictionary**

| Term | Reason |
|------|--------|
| rib eye steak | Specific cut name, not a modifier |
| lip off / lip-on | Too specific to mollusk prep; niche |
| flat half | Cut/form specification, too specific |
| luncheon meat | Product category, not a modifier |
| latte | Product/beverage name, not a modifier |
| frozen coffee drink | Product name, not a modifier |
| soft serve | Product name, not a modifier |
| roll | Serving vehicle, not food modifier |
| on wheat bun / on white bun | Serving vehicle, not food modifier |
| on wheat bread / on white bread | Serving vehicle, not food modifier |
| diet frozen meal | Product category, not a modifier |
| as ingredient | Context tag, not a modifier |

**Keep these (nutrition-relevant):**
- meatless — affects macro profile
- cheese-filled — affects macro profile

---

## VOICE INPUT → CANONICAL MAPPING TABLE
**For embedding → canonical value resolution**

| User Says | Maps To | Category |
|-----------|---------|----------|
| "no skin" | SKIN_OFF | Skin & Coating |
| "with skin" / "skin on" | SKIN_ON | Skin & Coating |
| "crispy" | COOKING_FAT or COOKING_DRY (context) | Cooking Method |
| "grilled" | COOKING_FAT | Cooking Method |
| "slow-cooked" / "tender" | COOKING_MOIST | Cooking Method |
| "raw" / "fresh" | COOKING_RAW | Cooking Method |
| "no oil" / "dry" | FAT_ADDED.NONE or COOKING_DRY | Fat Added |
| "buttered" / "oily" | FAT_ADDED.BUTTER or FAT_ADDED.OIL | Fat Added |
| "low-sodium" / "no salt" | SODIUM_LEVEL.REDUCED or SODIUM_LEVEL.NONE | Salt & Sodium |
| "sweet" / "sweetened" | SWEETNESS_LEVEL.ADDED | Sugar & Sweetening |
| "unsweetened" / "black" (coffee) | SWEETNESS_LEVEL.NONE | Sugar & Sweetening |
| "lite" / "light" | FAT_LEVEL.REDUCED | Fat Content |
| "frozen" | PREP_FORM.FROZEN | Prep State |
| "canned" | PREP_FORM.CANNED | Prep State |
| "homemade" | SOURCE_TYPE.HOME | Source/Origin |
| "restaurant" / "takeout" | SOURCE_TYPE.COMMERCIAL | Source/Origin |
| "fried" / "deep fried" / "air fried" | COOKING_FAT | Cooking Method |
| "breaded" / "battered" | COATING_STATUS.BREADED | Skin & Coating |
| "oven roasted" | COOKING_DRY | Cooking Method |
| "thin crust" / "deep dish" | PREP_FORM or specific dimension (Phase 2) | Prep State |
| "whole wheat" | GRAIN_TYPE.WHOLE | Grain Type |
| "smothered in" / "drenched in" | SAUCE_PROFILE.WITH | Sauce/Liquid |
| "organic" | SOURCE_QUALITY.ORGANIC | Sourcing/Quality |
| "grass-fed" | SOURCE_QUALITY.GRASSFED | Sourcing/Quality |

---

## IMPLEMENTATION NOTES

### Re-ranking Logic
1. **Embeddings retrieve** candidate foods (soft search via RAG)
2. **Modifier layer enforces** exact matches on canonical values (hard constraints)
3. **Override rules:**
   - `SODIUM_LEVEL.NONE` + `SODIUM_LEVEL.ADDED` = filter to NONE (user specificity wins)
   - `FAT_ADDED.NONE` overrides `FAT_ADDED.OIL` or `FAT_ADDED.BUTTER`
   - `SKIN_OFF` overrides `SKIN_ON`

### Phase 1 Implementation
Use these **11 main categories** as re-ranking constraints:
1. Cooking Method
2. Prep State
3. Fat Trim & Content
4. Skin & Coating
5. Salt & Sodium
6. Sugar & Sweetening
7. Grain Type
8. Sauce / Liquid / Binding
9. Form / Texture
10. Source / Origin
11. Temperature

### Phase 2 (Future)
- Add sourcing/quality (organic, grass-fed)
- Add meat part taxonomy (thigh, breast, wing)
- Add fat type (olive oil, coconut oil)
- Add portion/thickness parsing

### Mutual Exclusivity Rules
- Within Cooking Method: only one value
- Within Prep State: Fresh/Frozen/Canned mutually exclusive; Reconstitution/Drained can add to either
- Within Skin & Coating: Skin ON or OFF, never both
- Within Salt: one primary level (None / Added / Reduced)
- Within Sugar: one primary level (None / Added)
- Within Grain Type: one primary (Whole / Refined / Gluten-Free)
- Within Source: one primary type (Commercial / Home / Pre-Made)
- Within Temperature: one primary (Hot / Cold / Room-temp)

---

## Notes for Parsing
- Voice ambiguity resolution: "crispy" needs context (fried + no-sauce = likely fried; fried + sauce = likely coated)
- Plural/count parsing: "two dannon yogurts" → 2x [yogurt with SOURCE_COMMERCIAL]
- Prep chain: "grilled chicken breast no skin" → COOKING_FAT + MEAT_PART.BREAST + SKIN_OFF
- Negation: "no sauce" = explicit SAUCE_PROFILE.NONE (stronger than default/implicit)
