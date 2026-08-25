type Props = {
  prompt: string;
  capturedFood?: string;
  modalitySwitch?: boolean;
  onTypeInstead: () => void;
  onDismiss: () => void;
};

export function RecapturePanel({
  prompt,
  capturedFood,
  modalitySwitch,
  onTypeInstead,
  onDismiss,
}: Props) {
  return (
    <section
      id="recapture-panel"
      role="region"
      aria-labelledby="recapture-heading"
      className="w-full max-w-md text-left border border-amber-300/50 bg-amber-950/40 rounded-xl p-4 sm:p-6"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <h2
          id="recapture-heading"
          className="text-lg font-semibold text-white"
        >
          Let&apos;s fill that in
        </h2>
        <button
          type="button"
          onClick={onDismiss}
          className="flex flex-col items-center shrink-0 text-white hover:text-white focus:outline-none focus:ring-2 focus:ring-white rounded px-1.5 py-0.5 -mt-1 -mr-1"
          aria-label="Dismiss recapture"
        >
          <span aria-hidden="true" className="text-lg leading-none">
            ×
          </span>
          <span className="text-[10px] leading-tight">Tap to dismiss</span>
        </button>
      </div>
      {capturedFood ? (
        <p className="text-sm text-white mb-2">
          Caught so far: <strong>{capturedFood}</strong>
        </p>
      ) : null}
      <p className="text-sm text-white" data-testid="recapture-prompt">
        {prompt}
      </p>
      {modalitySwitch ? (
        <button
          type="button"
          onClick={onTypeInstead}
          className="mt-4 w-full px-4 py-2.5 bg-white text-blue-800 font-semibold rounded-lg text-sm hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700"
        >
          Type instead
        </button>
      ) : null}
    </section>
  );
}
