/** Module-level playback so any caller can cut TTS short (e.g. text submit). */
let currentAudio: HTMLAudioElement | null = null;
let speakEpoch = 0;

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

export async function speak(
  text: string,
  {
    muted,
    selectedVoice,
    apiBase,
  }: { muted: boolean; selectedVoice: string; apiBase: string },
) {
  if (muted) return;
  stopSpeaking();
  const epoch = speakEpoch;
  const aborted = () => epoch !== speakEpoch;

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
    audio.onended = finish;
    audio.onerror = finish;
    audio.play().catch(finish);
    await done;
    if (currentAudio === audio) currentAudio = null;
    URL.revokeObjectURL(url);
  } catch {
    if (aborted()) return;
    const { finish, done } = waitUntilDone(aborted, () => {
      window.speechSynthesis.cancel();
    });
    const utt = new SpeechSynthesisUtterance(text);
    utt.onend = finish;
    utt.onerror = finish;
    window.speechSynthesis.speak(utt);
    await done;
  }
}
