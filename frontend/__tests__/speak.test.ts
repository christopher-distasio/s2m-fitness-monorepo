import { speak } from "../lib/speak";

const defaultArgs = {
  muted: false,
  selectedVoice: "alloy",
  apiBase: "http://localhost:8000",
};

const mockPlay = jest.fn();

beforeEach(() => {
  jest.resetAllMocks();

  global.fetch = jest.fn();
  global.URL.createObjectURL = jest.fn().mockReturnValue("blob:fake-url");
  global.Audio = jest.fn().mockImplementation(() => ({ play: mockPlay }));
  global.window.speechSynthesis = { speak: jest.fn() } as any;
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
  expect(mockPlay).toHaveBeenCalled();
});

test("falls back to speechSynthesis when res.ok is false", async () => {
  (fetch as jest.Mock).mockResolvedValueOnce({ ok: false });

  await speak("hello", defaultArgs);

  expect(window.speechSynthesis.speak).toHaveBeenCalledWith(
    expect.objectContaining({ text: "hello" }),
  );
  expect(mockPlay).not.toHaveBeenCalled();
});

test("falls back to speechSynthesis when fetch throws", async () => {
  (fetch as jest.Mock).mockRejectedValueOnce(new Error("network error"));

  await speak("hello", defaultArgs);

  expect(window.speechSynthesis.speak).toHaveBeenCalledWith(
    expect.objectContaining({ text: "hello" }),
  );
  expect(mockPlay).not.toHaveBeenCalled();
});
