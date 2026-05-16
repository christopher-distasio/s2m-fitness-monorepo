export async function speak(
  text: string,
  {
    muted,
    selectedVoice,
    apiBase,
  }: { muted: boolean; selectedVoice: string; apiBase: string },
) {
  if (muted) return;
  try {
    const res = await fetch(`${apiBase}/food/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice: selectedVoice }),
    });
    if (!res.ok) throw new Error("TTS failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    await new Promise<void>((resolve) => {
      audio.onended = () => resolve();
      audio.play();
    });
  } catch {
    await new Promise<void>((resolve) => {
      const utt = new SpeechSynthesisUtterance(text);
      utt.onend = () => resolve();
      window.speechSynthesis.speak(utt);
    });
  }
}