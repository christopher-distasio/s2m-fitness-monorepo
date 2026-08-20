/** Module-level playback so any caller can cut TTS short (e.g. Speak button). */
let currentAudio: HTMLAudioElement | null = null;
let speakEpoch = 0;
let speakInFlight = false;
const speakingListeners = new Set<(speaking: boolean) => void>();

function notifySpeaking(speaking: boolean) {
  speakInFlight = speaking;
  speakingListeners.forEach((fn) => fn(speaking));
}

/** Subscribe to TTS start/stop (for enabling the Speak interrupt button). */
export function onSpeakingChange(
  listener: (speaking: boolean) => void,
): () => void {
  speakingListeners.add(listener);
  listener(speakInFlight);
  return () => {
    speakingListeners.delete(listener);
  };
}

export function isSpeaking(): boolean {
  return speakInFlight;
}

/** Immediately end any in-progress TTS (OpenAI audio or speechSynthesis). */
export function stopSpeaking() {
  speakEpoch += 1;
  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.removeAttribute("src");
      currentAudio.load();
    } catch {
      /* ignore teardown races */
    }
    currentAudio = null;
  }
  if (typeof window !== "undefined" && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  notifySpeaking(false);
}

function waitUntilDone(
  aborted: () => boolean,
  onAbort?: () => void,
): { finish: () => void; done: Promise<void> } {
  let settled = false;
  let resolveFn: () => void = () => {};
  const done = new Promise<void>((resolve) => {
    resolveFn = resolve;
  });
  const finish = () => {
    if (settled) return;
    settled = true;
    window.clearInterval(poll);
    resolveFn();
  };
  const poll = window.setInterval(() => {
    if (aborted()) {
      onAbort?.();
      finish();
    }
  }, 50);
  return { finish, done };
}

/** Single TTS choke point — all spoken UI must go through `speak()`. */
export async function speak(
  text: string,
  {
    muted,
    selectedVoice,
    apiBase,
  }: { muted: boolean; selectedVoice: string; apiBase: string },
) {
  if (muted) return;
  // Interrupt any prior utterance without clearing the upcoming "speaking" flag
  // via stopSpeaking's notify(false) — we go straight into this utterance.
  speakEpoch += 1;
  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.removeAttribute("src");
      currentAudio.load();
    } catch {
      /* ignore */
    }
    currentAudio = null;
  }
  if (typeof window !== "undefined" && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  const epoch = speakEpoch;
  const aborted = () => epoch !== speakEpoch;
  notifySpeaking(true);

  try {
    const res = await fetch(`${apiBase}/food/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice: selectedVoice }),
    });
    if (!res.ok) throw new Error("TTS failed");
    if (aborted()) return;
    const blob = await res.blob();
    if (aborted()) return;
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    const { finish, done } = waitUntilDone(aborted);
    const cap = window.setTimeout(finish, 20000);
    const end = () => {
      window.clearTimeout(cap);
      finish();
    };
    audio.onended = end;
    audio.onerror = end;
    audio.onloadedmetadata = () => {
      const ms = Math.ceil((audio.duration || 0) * 1000) + 400;
      if (Number.isFinite(ms) && ms > 400) window.setTimeout(end, ms);
    };
    audio.play().catch(end);
    await done;
    window.clearTimeout(cap);
    if (currentAudio === audio) currentAudio = null;
    URL.revokeObjectURL(url);
  } catch {
    if (aborted()) return;
    const { finish, done } = waitUntilDone(aborted, () => {
      window.speechSynthesis.cancel();
    });
    const cap = window.setTimeout(finish, 20000);
    const end = () => {
      window.clearTimeout(cap);
      finish();
    };
    const utt = new SpeechSynthesisUtterance(text);
    utt.onend = end;
    utt.onerror = end;
    window.speechSynthesis.speak(utt);
    await done;
    window.clearTimeout(cap);
  } finally {
    if (epoch === speakEpoch) notifySpeaking(false);
  }
}
