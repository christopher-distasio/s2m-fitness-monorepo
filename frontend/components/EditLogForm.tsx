import { useEffect, useRef } from "react";
import type { EditLogFields } from "../lib/editLog";

type Props = {
  logId: string;
  foodName: string;
  fields: EditLogFields;
  onChange: (fields: EditLogFields) => void;
  onSave: () => void;
  onCancel: () => void;
  restrictionStatus?: string;
};

const FIELD_LABELS: Array<{ key: keyof EditLogFields; label: string }> = [
  { key: "food", label: "Food" },
  { key: "brand", label: "Brand" },
  { key: "variant", label: "Variant" },
  { key: "preparation", label: "Preparation" },
  { key: "amount", label: "Amount" },
  { key: "unit", label: "Unit" },
];

export function EditLogForm({
  logId,
  foodName,
  fields,
  onChange,
  onSave,
  onCancel,
  restrictionStatus,
}: Props) {
  const firstFieldRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    firstFieldRef.current?.focus();
  }, [logId]);

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    }
  }

  return (
    <form
      role="form"
      aria-labelledby={`edit-log-heading-${logId}`}
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
      onKeyDown={handleKeyDown}
      className="flex flex-col gap-3 text-left"
    >
      <h3
        id={`edit-log-heading-${logId}`}
        className="text-base font-semibold text-white"
      >
        Edit {foodName}
      </h3>
      {FIELD_LABELS.map(({ key, label }, index) => {
        const inputId = `edit-${key}-${logId}`;
        return (
          <div key={key} className="flex flex-col gap-1">
            <label htmlFor={inputId} className="text-sm text-white">
              {label}
            </label>
            <input
              id={inputId}
              ref={index === 0 ? firstFieldRef : undefined}
              name={key}
              value={fields[key]}
              onChange={(event) =>
                onChange({ ...fields, [key]: event.target.value })
              }
              className="min-h-11 w-full rounded-lg border border-white/30 bg-white/10 px-3 py-2 text-sm text-white placeholder-white/70 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-white"
            />
          </div>
        );
      })}
      {restrictionStatus ? (
        <p role="status" aria-live="polite" className="text-sm text-white">
          {restrictionStatus}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          className="min-h-11 min-w-11 rounded-lg bg-green-800 px-4 py-2 text-sm font-semibold text-white hover:bg-green-900 focus:outline-none focus:ring-2 focus:ring-white"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="min-h-11 min-w-11 rounded-lg bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-white"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
