import type { RefObject } from "react";
import {
  ALLERGEN_LABELS,
  FDA_ALLERGENS,
  OPTIONAL_OPTIONS,
  TIER1_DIET_OPTIONS,
  TIER2_OPTIONS,
  type AllergySeverity,
  type DietaryPreferences,
  type FdaAllergen,
  type OptionalPreferences,
  type Tier1Preferences,
  type Tier2Preferences,
} from "../lib/dietaryPreferences";

function PrefSwitch({
  id,
  label,
  checked,
  onChange,
  disabled,
  hint,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const labelId = `${id}-label`;
  return (
    <div
      className={`flex items-start justify-between gap-3 py-2 ${
        disabled ? "opacity-50" : ""
      }`}
    >
      <div className="min-w-0">
        <span id={labelId} className="text-sm text-white">
          {label}
        </span>
        {hint ? (
          <p className="mt-0.5 text-[11px] leading-snug text-white/55">{hint}</p>
        ) : null}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative box-border h-5 w-9 shrink-0 overflow-hidden rounded-full border p-0.5 transition-colors focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-0 ${
          disabled ? "cursor-not-allowed" : "cursor-pointer"
        } ${
          checked
            ? "border-blue-300 bg-blue-500"
            : "border-white/40 bg-white/20"
        }`}
      >
        <span
          aria-hidden="true"
          className={`absolute top-1/2 size-3 -translate-y-1/2 rounded-full bg-white shadow-sm transition-[left,right] duration-200 ease-in-out ${
            checked ? "right-0.5 left-auto" : "left-0.5 right-auto"
          }`}
        />
      </button>
    </div>
  );
}

export function DietaryPreferencesPanel({
  value,
  onChange,
  onSave,
  saving,
  statusMessage,
  headingRef,
}: {
  value: DietaryPreferences;
  onChange: (next: DietaryPreferences) => void;
  onSave: () => void;
  saving?: boolean;
  statusMessage?: string;
  headingRef?: RefObject<HTMLHeadingElement>;
}) {
  function setAllergen(
    key: FdaAllergen,
    patch: Partial<{ enabled: boolean; severity: AllergySeverity }>,
  ) {
    const current = value.tier_1.allergens[key];
    onChange({
      ...value,
      tier_1: {
        ...value.tier_1,
        allergens: {
          ...value.tier_1.allergens,
          [key]: { ...current, ...patch },
        },
      },
    });
  }

  function setTier1Bool(key: keyof Omit<Tier1Preferences, "allergens">, checked: boolean) {
    onChange({
      ...value,
      tier_1: { ...value.tier_1, [key]: checked },
    });
  }

  function setTier2Bool(key: keyof Tier2Preferences, checked: boolean) {
    onChange({
      ...value,
      tier_2: { ...value.tier_2, [key]: checked },
    });
  }

  function setOptionalBool(key: keyof OptionalPreferences, checked: boolean) {
    onChange({
      ...value,
      optional: { ...value.optional, [key]: checked },
    });
  }

  return (
    <fieldset className="min-w-0">
      <legend className="sr-only">Dietary preferences</legend>
      <h3
        ref={headingRef}
        id="dietary-preferences-heading"
        tabIndex={-1}
        className="mb-1 text-sm font-medium text-white outline-none"
      >
        Dietary preferences
      </h3>
      <p className="mb-3 text-[11px] leading-snug text-white/60">
        Allergies and diet restrictions filter what you can log. Soft preferences
        rank matching foods higher when possible.
      </p>

      {/* Allergies */}
      <div className="mb-4">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/50">
          Allergies
        </p>
        <p className="mb-2 text-[11px] leading-snug text-white/55">
          Severe blocks unsafe foods. Moderate allows them with a warning.
        </p>
        <ul className="divide-y divide-white/10">
          {FDA_ALLERGENS.map((key) => {
            const row = value.tier_1.allergens[key];
            return (
              <li key={key} className="py-2">
                <PrefSwitch
                  id={`allergy-${key}`}
                  label={ALLERGEN_LABELS[key]}
                  checked={row.enabled}
                  onChange={(enabled) => setAllergen(key, { enabled })}
                />
                {row.enabled ? (
                  <div
                    className="mt-1 flex flex-wrap gap-2 pl-0 sm:pl-1"
                    role="radiogroup"
                    aria-label={`${ALLERGEN_LABELS[key]} severity`}
                  >
                    {(["severe", "moderate"] as AllergySeverity[]).map((sev) => {
                      const selected = row.severity === sev;
                      return (
                        <button
                          key={sev}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          onClick={() => setAllergen(key, { severity: sev })}
                          className={`rounded-md border px-2.5 py-1 text-[11px] font-medium capitalize transition-colors focus:outline-none focus:ring-2 focus:ring-white ${
                            selected
                              ? "border-white bg-white text-blue-800"
                              : "border-white/30 bg-white/10 text-white hover:bg-white/15"
                          }`}
                        >
                          {sev}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </div>

      {/* Diet restrictions */}
      <div className="mb-4 border-t border-white/15 pt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/50">
          Diet restrictions
        </p>
        <div className="divide-y divide-white/10">
          {TIER1_DIET_OPTIONS.map(({ key, label, disabled, hint }) => (
            <PrefSwitch
              key={key}
              id={`diet-${key}`}
              label={label}
              checked={Boolean(value.tier_1[key])}
              onChange={(checked) => setTier1Bool(key, checked)}
              disabled={disabled}
              hint={hint}
            />
          ))}
        </div>
      </div>

      {/* Soft preferences */}
      <div className="mb-4 border-t border-white/15 pt-4">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/50">
          Preferences
        </p>
        <p className="mb-2 text-[11px] leading-snug text-white/55">
          Preferred when available — not required.
        </p>
        <div className="divide-y divide-white/10">
          {TIER2_OPTIONS.map(({ key, label }) => (
            <PrefSwitch
              key={key}
              id={`pref-${key}`}
              label={label}
              checked={Boolean(value.tier_2[key])}
              onChange={(checked) => setTier2Bool(key, checked)}
            />
          ))}
        </div>
      </div>

      {/* More options */}
      <details className="mb-4 border-t border-white/15 pt-3">
        <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-wide text-white/50 hover:text-white/70">
          More options
        </summary>
        <p className="mt-2 mb-2 text-[11px] leading-snug text-white/55">
          Niche medical filters. Stored for your profile; search support may
          expand over time.
        </p>
        <div className="divide-y divide-white/10">
          {OPTIONAL_OPTIONS.map(({ key, label }) => (
            <PrefSwitch
              key={key}
              id={`optional-${key}`}
              label={label}
              checked={Boolean(value.optional[key])}
              onChange={(checked) => setOptionalBool(key, checked)}
            />
          ))}
        </div>
      </details>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="px-4 py-2 bg-white text-blue-700 font-semibold rounded-lg text-sm hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors disabled:opacity-60"
          aria-label="Save dietary preferences"
        >
          {saving ? "Saving…" : "Save preferences"}
        </button>
        {statusMessage ? (
          <p className="text-xs text-white/80" role="status" aria-live="polite">
            {statusMessage}
          </p>
        ) : null}
      </div>
    </fieldset>
  );
}
