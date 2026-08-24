/**
 * Spec 4 — end-of-utterance silence timeout.
 *
 * This is the single endpointing decision used by barge-in VAD. It is
 * intentionally longer than a typical fast-speech default so floor-holding
 * pauses (including mid-word "oat... meal") are not split into two captures.
 * Per-user adjustment is future work; this default is accessibility-critical.
 */
export const ENDPOINTING_SILENCE_TIMEOUT_MS = 2800;

/** Mid-word pause used in tests: shorter than the shipped silence timeout. */
export const MID_WORD_PAUSE_MS = 800;

export function shouldEndUtterance(
  silenceMs: number,
  timeoutMs: number = ENDPOINTING_SILENCE_TIMEOUT_MS,
): boolean {
  return silenceMs >= timeoutMs;
}

/**
 * Walk a sequence of (loud, durationMs) frames. Returns how many separate
 * utterances would be committed. A pause shorter than the timeout must not
 * start a second capture.
 */
export function countUtterancesFromFrames(
  frames: Array<{ loud: boolean; durationMs: number }>,
  timeoutMs: number = ENDPOINTING_SILENCE_TIMEOUT_MS,
): number {
  let utterances = 0;
  let inSpeech = false;
  let silenceMs = 0;
  for (const frame of frames) {
    if (frame.loud) {
      if (!inSpeech) {
        inSpeech = true;
        utterances += 1;
      }
      silenceMs = 0;
    } else if (inSpeech) {
      silenceMs += frame.durationMs;
      if (shouldEndUtterance(silenceMs, timeoutMs)) {
        inSpeech = false;
        silenceMs = 0;
      }
    }
  }
  return utterances;
}
