# S2M Frontend Standards — Accessibility Requirements

Hand to Cursor alongside Spec 1. Every component built from here follows these by default. These are not suggestions; they are the accessibility floor for an app whose entire positioning is accessibility-as-interaction-model.

Context: S2M is Next.js + Tailwind, wrapped in Capacitor. Components are custom-designed rather than template-derived. That is fine — custom UI is fully compatible with accessibility — but only if these practices are adopted from the start. Retrofitting them across a built codebase is genuinely miserable work, which is why they belong in the first commit rather than a later cleanup pass.

---

## 1. Typography: never fixed pixels for text

**Rule: all font sizes in `rem`. No exceptions for body text, labels, buttons, or numbers.**

Fixed `px` font sizes ignore browser and OS font-scaling settings entirely. Font scaling is the single most-used low-vision accommodation — more used than screen readers by a wide margin, because it serves the far larger population with partial vision loss, presbyopia, and age-related decline. Hardcoding `px` breaks it completely and silently.

In Tailwind: the default type scale (`text-sm`, `text-base`, `text-lg`) is already rem-based — use it. Never override with arbitrary pixel values (`text-[14px]`).

Line height and spacing around text should also scale — use relative units or Tailwind's scale rather than fixed pixel gaps that will collide when text grows.

**Test:** set browser font size to 200%. Every screen must remain usable — no clipped text, no overlapping elements, no horizontal scrolling of body content.

## 2. Semantic HTML, always

`<button>` for actions. `<a>` for navigation. `<input>` with an associated `<label>`. `<nav>`, `<main>`, `<h1>`-`<h6>` in correct order.

Never `<div onClick={...}>`. A div with a click handler is invisible to screen readers, unreachable by keyboard, and has no focus behavior. This is the most common accessibility failure in custom-built UI and it's entirely avoidable.

If a custom component must wrap a native element, wrap it — don't replace it.

## 3. Color: CSS custom properties, never hardcoded

All colors defined as CSS variables (Tailwind theme tokens are fine). No hex values inline in components.

This is what makes a high-contrast theme possible later without touching every component. Given the target population includes low-vision users, a high-contrast mode is a near-certain future requirement — and the cost of enabling it now is approximately zero.

**Contrast minimums (WCAG AA):** 4.5:1 for normal text, 3:1 for large text (18pt+/14pt+ bold) and for UI component boundaries. Verify with a contrast checker during design, not after.

**Never convey information by color alone.** A red border indicating an allergen warning must also have text or an icon. Color-blind users and screen-reader users get nothing from color.

## 4. Respect OS accessibility preferences

Implement these media queries from the start:

```css
@media (prefers-reduced-motion: reduce) { /* disable animation/transitions */ }
@media (prefers-contrast: more) { /* higher-contrast token values */ }
@media (prefers-color-scheme: dark) { /* dark theme */ }
```

`prefers-reduced-motion` matters beyond preference — motion can trigger nausea and vestibular symptoms. Any animation must have a no-motion path.

## 5. Touch targets: 44×44px minimum

WCAG 2.5.5. Non-negotiable for tremor, Parkinson's, limited dexterity, and one-handed use — a substantial share of the OT-referred population.

This constrains layout, so decide it before designing screens rather than discovering it during an audit. Spacing between adjacent targets matters too: tightly packed 44px targets are still hard to hit accurately.

## 6. Focus indicators: always visible

Never `outline: none` without an equally visible replacement. Keyboard and switch-access users navigate entirely by focus; an invisible focus ring makes the app unusable for them.

Focus order must follow visual order. Test by tabbing through every screen.

## 7. ARIA where semantics aren't self-evident

- `aria-label` on icon-only buttons
- `aria-live="polite"` on regions that update dynamically (a log confirming, a total updating) so screen readers announce the change
- `aria-live="assertive"` reserved for genuinely urgent content — allergen warnings, safety messages
- `aria-describedby` linking inputs to help text and error messages
- `role="alert"` on error states

Do not add ARIA where semantic HTML already conveys meaning. Redundant ARIA is worse than none.

## 8. Screen-reader-specific requirements for this app

- **Every clarification question must be announced**, not just visually presented. If the app is asking something, a VoiceOver/TalkBack user must hear it without hunting.
- **Confidence and uncertainty states must be conveyed non-visually.** "Unsure" as a visual badge alone is invisible to a blind user — it needs to be in the announced text.
- **The candidate list must be navigable and ordinally addressable.** "The second one" needs to work by voice *and* the list needs to be screen-reader traversable.
- **Never rely on a visual-only "tap to dismiss."** Everything dismissible must be dismissible by keyboard, switch, and voice.

## 9. Modality parity (Spec 1 hard rule 8, restated as a frontend requirement)

Every flow must be completable by voice alone AND by touch alone AND by keyboard alone. Clarification, correction, partial recapture, and confirmation all included.

Concretely: never make a camera the only path to anything. Never make a fine-grained gesture (drag, pinch, swipe-to-reveal) the only way to perform an action. Never require reading a label to answer a question the app asks.

## 10. Testing requirements before any UI ships

1. VoiceOver (iOS) full-flow test — log a food, answer a clarification, correct an entry
2. TalkBack (Android) same
3. Keyboard-only navigation, no mouse
4. 200% browser font scaling
5. High-contrast mode
6. `prefers-reduced-motion` enabled
7. Switch Access (Android) or Switch Control (iOS) for at least the core logging flow

Automated tooling (axe DevTools, Lighthouse) catches maybe a third of real issues — useful as a first pass, not sufficient. The manual screen-reader walkthrough is the one that matters.

## 11. Apple Accessibility Nutrition Labels

Apple's App Store Accessibility Nutrition Labels (announced May 2025, on new/updated submissions from Sept 2025) surface accessibility support at the point of download — the exact discovery surface these users check.

**Complete it fully and accurately at launch.** It is free differentiation, it makes the accessibility claim independently verifiable rather than marketing copy, and no comprehensive list of nutrition apps that have completed it appears to exist yet.

Requirement: whatever gets claimed on that label must actually be true and tested. An overclaimed label is worse than no label for a trust-positioned product.
