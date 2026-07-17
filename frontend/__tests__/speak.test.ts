import { speak, stopSpeaking } from "../lib/speak";

const defaultArgs = {
  muted: false,
  selectedVoice: "alloy",
  apiBase: "http://localhost:8000",
};

beforeEach(() => {
  jest.resetAllMocks();
  stopSpeaking();

  global.fetch = jest.fn();
  global.URL.createObjectURL = jest.fn().mockReturnValue("blob:fake-url");
  global.URL.revokeObjectURL = jest.fn();
  global.Audio = jest.fn().mockImplementation(() => {
    const audio: any = {
      play: jest.fn().mockImplementation(() => {
        queueMicrotask(() => audio.onended?.());
        return Promise.resolve();
      }),
      pause: jest.fn(),
      removeAttribute: jest.fn(),
      load: jest.fn(),
    };
    return audio;
  });
  global.window.speechSynthesis = {
    speak: jest.fn(),
    cancel: jest.fn(),
  } as any;
  global.SpeechSynthesisUtterance = jest
    .fn()
    .mockImplementation((text) => ({ text })) as any;
});

test("returns early without calling fetch when muted", async () => {
  await speak("hello", { ...defaultArgs, muted: true });
  expect(fetch).not.toHaveBeenCalled();
});

test("calls fetch with correct endpoint, method, and body", async () => {
  (fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    blob: jest.fn().mockResolvedValueOnce(new Blob()),
  });

  await speak("hello", defaultArgs);

  expect(fetch).toHaveBeenCalledWith("http://localhost:8000/food/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: "hello", voice: "alloy" }),
  });
});

test("plays audio via Audio when TTS succeeds", async () => {
  (fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    blob: jest.fn().mockResolvedValueOnce(new Blob()),
  });

  await speak("hello", defaultArgs);

  expect(URL.createObjectURL).toHaveBeenCalled();
  expect(Audio).toHaveBeenCalledWith("blob:fake-url");
});

test("falls back to speechSynthesis when res.ok is false", async () => {
  (fetch as jest.Mock).mockResolvedValueOnce({ ok: false });

  // Resolve speechSynthesis via onend on next tick
  (window.speechSynthesis.speak as jest.Mock).mockImplementation((utt: any) => {
    queueMicrotask(() => utt.onend?.());
  });

  await speak("hello", defaultArgs);

  expect(window.speechSynthesis.speak).toHaveBeenCalledWith(
    expect.objectContaining({ text: "hello" }),
  );
});

test("falls back to speechSynthesis when fetch throws", async () => {
  (fetch as jest.Mock).mockRejectedValueOnce(new Error("network error"));
  (window.speechSynthesis.speak as jest.Mock).mockImplementation((utt: any) => {
    queueMicrotask(() => utt.onend?.());
  });

  await speak("hello", defaultArgs);

  expect(window.speechSynthesis.speak).toHaveBeenCalledWith(
    expect.objectContaining({ text: "hello" }),
  );
});

test("stopSpeaking cancels in-progress speechSynthesis fallback", async () => {
  (fetch as jest.Mock).mockResolvedValueOnce({ ok: false });
  let uttRef: any;
  (window.speechSynthesis.speak as jest.Mock).mockImplementation((utt: any) => {
    uttRef = utt;
    // never ends on its own
  });

  const p = speak("hello", defaultArgs);
  await Promise.resolve();
  stopSpeaking();
  await p;

  expect(window.speechSynthesis.cancel).toHaveBeenCalled();
  expect(uttRef).toBeTruthy();
});
