import {
  ENDPOINTING_SILENCE_TIMEOUT_MS,
  MID_WORD_PAUSE_MS,
  countUtterancesFromFrames,
  shouldEndUtterance,
} from "../lib/endpointing";

test("mid-word oat...meal pause does not end the utterance", () => {
  expect(MID_WORD_PAUSE_MS).toBeLessThan(ENDPOINTING_SILENCE_TIMEOUT_MS);
  expect(shouldEndUtterance(MID_WORD_PAUSE_MS)).toBe(false);
  expect(shouldEndUtterance(ENDPOINTING_SILENCE_TIMEOUT_MS)).toBe(true);

  const utterances = countUtterancesFromFrames([
    { loud: true, durationMs: 200 },
    { loud: false, durationMs: MID_WORD_PAUSE_MS },
    { loud: true, durationMs: 200 },
  ]);
  expect(utterances).toBe(1);
});

test("a pause longer than the silence timeout starts a second capture", () => {
  const utterances = countUtterancesFromFrames([
    { loud: true, durationMs: 200 },
    { loud: false, durationMs: ENDPOINTING_SILENCE_TIMEOUT_MS },
    { loud: true, durationMs: 200 },
  ]);
  expect(utterances).toBe(2);
});
