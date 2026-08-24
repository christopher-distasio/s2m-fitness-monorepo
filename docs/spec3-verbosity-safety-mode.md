# Spec 3 — Verbosity Setting + Safety Mode

Two separate settings. Verbosity is response *length* (a floor, not a
ceiling). Safety Mode is whether calorie/energy *content exists at all*.

| Field | Default | Notes |
|---|---|---|
| `verbosity_level` | `"standard"` | `"quick"` / `"standard"` / `"careful"` |
| `safety_mode_enabled` | `false` | Opt-in blind logging |

Routine copy lives in `backend/services/response_compose.py`
(`VERBOSITY_TABLE`). Spec 0 safety, Spec 2 ASK, allergen read-back, and
restriction verdicts are not in that table and ignore both settings.

Safety Mode suppresses calorie-remaining, energy-budget, and
compensatory-exercise language only. `evaluate_restrictions()` verdicts
and nutrient ceilings are never suppressed (D3). Logging still stores
calories.

Voice-only allergen/negation read-back: `backend/services/allergen_readback.py`.
Runs after Spec 2. Typed input does not use this gate.

Settings UI: `frontend/components/ResponseSettingsPanel.tsx` (account
Settings, not paywalled). All spoken copy still goes through `speak()`.

See `docs/scope-decisions-d1-d5.md` (D3, D5).
