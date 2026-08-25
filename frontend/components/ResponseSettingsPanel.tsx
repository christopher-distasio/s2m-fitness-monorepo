import type { VerbosityLevel } from "../lib/responseCompose";

type Props = {
  verbosityLevel: VerbosityLevel;
  safetyModeEnabled: boolean;
  onVerbosityChange: (level: VerbosityLevel) => void;
  onSafetyModeChange: (enabled: boolean) => void;
  saving?: boolean;
  statusMessage?: string;
};

const LEVELS: Array<{ id: VerbosityLevel; label: string; hint: string }> = [
  { id: "quick", label: "Quick", hint: "Shortest routine confirmations" },
  { id: "standard", label: "Standard", hint: "Default amount of detail" },
  { id: "careful", label: "Careful", hint: "More detail on routine logs" },
];

export function ResponseSettingsPanel({
  verbosityLevel,
  safetyModeEnabled,
  onVerbosityChange,
  onSafetyModeChange,
  saving,
  statusMessage,
}: Props) {
  return (
    <div
      id="response-settings"
      className="flex flex-col gap-5"
      role="region"
      aria-label="Response settings"
    >
      <fieldset>
        <legend className="text-sm font-medium text-white mb-2">
          Verbosity
        </legend>
        <p className="text-xs text-white mb-3">
          How much the app says for routine logs and summaries. Safety
          questions and allergen read-backs are never shortened.
        </p>
        <div className="flex flex-col gap-2">
          {LEVELS.map((level) => (
            <label
              key={level.id}
              className="flex items-start gap-2 text-sm text-white"
            >
              <input
                type="radio"
                name="verbosity-level"
                value={level.id}
                checked={verbosityLevel === level.id}
                onChange={() => onVerbosityChange(level.id)}
                className="mt-1"
              />
              <span>
                <span className="font-medium">{level.label}</span>
                <span className="block text-xs text-white">{level.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-sm font-medium text-white mb-2">
          Safety Mode
        </legend>
        <p className="text-xs text-white mb-3">
          Hides calories remaining, energy-budget, and offset-exercise language.
          Logging continues. Allergen and nutrient-ceiling reports are
          unchanged.
        </p>
        <div className="flex items-center justify-between gap-3">
          <span id="safety-mode-label" className="text-sm text-white">
            Safety Mode
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={safetyModeEnabled}
            aria-labelledby="safety-mode-label"
            disabled={saving}
            onClick={() => onSafetyModeChange(!safetyModeEnabled)}
            className={`relative box-border h-5 w-9 shrink-0 cursor-pointer overflow-hidden rounded-full border p-0.5 transition-colors focus:outline-none focus:ring-2 focus:ring-white ${
              safetyModeEnabled
                ? "border-blue-300 bg-blue-500"
                : "border-white/40 bg-white/20"
            }`}
          >
            <span
              aria-hidden="true"
              className={`absolute top-1/2 size-3 -translate-y-1/2 rounded-full bg-white shadow-sm transition-[left,right] duration-200 ease-in-out ${
                safetyModeEnabled ? "right-0.5 left-auto" : "left-0.5 right-auto"
              }`}
            />
          </button>
        </div>
        <p className="mt-2 text-xs text-white" aria-live="polite">
          {safetyModeEnabled
            ? "On — calories remaining and energy-budget language is hidden."
            : "Off — calorie totals and remaining language are shown."}
        </p>
      </fieldset>
      {statusMessage ? (
        <p role="status" className="text-xs text-white">
          {statusMessage}
        </p>
      ) : null}
    </div>
  );
}
