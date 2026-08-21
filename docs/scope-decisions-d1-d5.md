# Scope Decisions D1-D5 (Locked Aug 18) — Context for Spec 1 Implementation

These five decisions constrain implementation choices throughout Spec 1 and later specs. Read alongside cursor-spec1-food-event-confidence-model.md.

## D1 — Hands-free / smart-speaker support is core, not deferred

Wake-word/ambient listening is a core feature, not an add-on — matters most for exactly the motor-impairment population S2M targets, where a required button press can itself be a barrier. `activation` field on UtteranceResult supports "push_to_talk" | "text" | "wake_word" | "ambient".

Wake-word detection and basic addressedness filtering (distinguishing directed speech from TV/background noise) are a REQUIRED v1 build item — not a safety feature, a functionality one. Ambient listening without it just produces false-positive logs from any nearby audio.

Privacy/bystander-exposure (who can hear a log, who can trigger one on a shared device) is handled by user-facing disclaimer, not by restricting the feature or building speaker attribution now. Multi-account speaker attribution is genuinely deferred — don't build it, but keep `subject_user_id` explicit everywhere (never an ambient "current user" shortcut) so it can be added later without a refactor.

**Wake-word listening is user-toggleable, off by default.** Explicit account setting `wake_word_enabled`, default OFF, opt-in during onboarding alongside the privacy disclaimer. Push-to-talk and text stay available regardless of this setting. The privacy disclaimer only makes sense if listening is something the user actively chose — an always-on mic with no way to disable it undermines the disclosure it depends on.

## D2 — Report, never assert safety

The app states what a record shows and what is unknown. It never says a food "is safe" for a given allergen or restriction — no positive safety assertions anywhere, in code-generated text or UI copy. This governs `evidence_basis` field usage (see Spec 1 hard rule 7): reporting the basis for a claim is not the same as asserting safety, and the distinction must hold in every user-facing string.

## D3 — No medical-diet support, but the quantitative shape is in scope, narrowly

Support user-set numeric ceilings (sodium, potassium, caffeine, etc.) with neutral reporting only: "that's 640mg; you've set 2,000mg." Zero suitability advice — never "you can/can't have this."

Keep two things separable in the data model, not one "goals" concept: **nutrient ceilings** (sodium/potassium — clinically benign to display) vs. **calorie/energy budgets** (the documented eating-disorder risk surface). This separation must exist so Safety Mode (future Spec 3) can suppress energy-budget language without touching nutrient-ceiling display.

## D4 — Strict domain boundary

S2M is a food-logging app, not a general assistant. Off-domain requests get a brief, consistent decline — do not attempt to answer general knowledge, weather, timers, etc.

One absolute exception: a safety-relevant utterance (distress, self-harm, eating-disorder signals, medical emergency) is NEVER treated as off-domain, regardless of how far it strays from food logging. Safety routing takes priority over domain-boundary logic.

## D5 — Pricing (context only, not implementation-relevant)

$7/mo stays; an annual tier at $54-60 will be added. Standing commitment: accessibility, safety responses, and restriction/allergen handling are never paywalled — relevant if/when any paywall-gating logic is implemented, to make sure these stay on the free tier.
