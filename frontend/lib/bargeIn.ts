/**
 * Speak while listening for barge-in: when the user starts talking, cut TTS
 * and return their recorded clip as WAV (PCM).
 *
 * MediaRecorder/WebM after a mid-stream restart often confuses Whisper on short
 * clips ("two" → garbage → "didn't catch a number"). Capturing PCM from the
 * barge moment and encoding WAV is much more reliable.
 */
import { speak, stopSpeaking, isSpeaking } from "./speak";

export type SpeakOptions = {
  muted: boolean;
  selectedVoice: string;
  apiBase: string;
};

export type BargeInResult =
  | { bargedIn: false }
  | { bargedIn: true; blob: Blob; mimeType: string };

const IGNORE_MS = 1000;
const SPEECH_HOLD_MS = 120;
const SILENCE_END_MS = 1000;
const MAX_AFTER_BARGE_MS = 5000;
const RMS_FLOOR = 0.03;
const BARGE_OVER_BASELINE = 2.4;
const LATE_BARGE_MS = 1200;
/** ~250ms of PCM kept before barge so the start of "two" isn't clipped. */
const PRE_ROLL_SAMPLES = 4000;
const MIN_WAV_BYTES = 1000;

const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};

function rms(analyser: AnalyserNode, buf: Float32Array): number {
  analyser.getFloatTimeDomainData(buf as unknown as Float32Array);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  return Math.sqrt(sum / buf.length);
}

/** 16-bit mono WAV from Float32 samples in [-1, 1]. */
function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const numSamples = samples.length;
  const buffer = new ArrayBuffer(44 + numSamples * 2);
  const view = new DataView(buffer);

  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + numSamples * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, numSamples * 2, true);

  let offset = 44;
  for (let i = 0; i < numSamples; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function concatFloat32(chunks: Float32Array[]): Float32Array {
  let total = 0;
  for (const c of chunks) total += c.length;
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

export async function speakWithBargeIn(
  text: string,
  speakOpts: SpeakOptions,
  hooks?: {
    onMicReady?: () => void;
    onBargeIn?: () => void;
    shouldCancel?: () => boolean;
  },
): Promise<BargeInResult> {
  if (speakOpts.muted) {
    await speak(text, speakOpts);
    return { bargedIn: false };
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
  } catch {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      await speak(text, speakOpts);
      return { bargedIn: false };
    }
  }

  const AudioContextCtor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext;
  const audioCtx = new AudioContextCtor();
  await audioCtx.resume().catch(() => {});
  const sampleRate = audioCtx.sampleRate;
  const source = audioCtx.createMediaStreamSource(stream);
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 2048;
  source.connect(analyser);
  const timeBuf = new Float32Array(analyser.fftSize);

  // Ring buffer before barge + capture after. ScriptProcessor is deprecated but
  // widely available; gain=0 avoids speaker feedback.
  const preRoll: Float32Array[] = [];
  let preRollSamples = 0;
  const captureChunks: Float32Array[] = [];
  let capturing = false;

  const processor = audioCtx.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);
    const copy = new Float32Array(input);
    if (capturing) {
      captureChunks.push(copy);
      return;
    }
    preRoll.push(copy);
    preRollSamples += copy.length;
    while (preRollSamples > PRE_ROLL_SAMPLES && preRoll.length > 1) {
      const dropped = preRoll.shift();
      if (dropped) preRollSamples -= dropped.length;
    }
  };
  const silent = audioCtx.createGain();
  silent.gain.value = 0;
  source.connect(processor);
  processor.connect(silent);
  silent.connect(audioCtx.destination);

  let bargedIn = false;
  let cancelled = false;
  let bargeStartedAt = 0;
  let lastLoudAt = 0;
  let speechHoldStartedAt: number | null = null;
  let baseline = RMS_FLOOR;
  let vadTimer: ReturnType<typeof setInterval> | null = null;
  const startedAt = performance.now();

  let resolveRecordingDone: (() => void) | null = null;
  const recordingDone = new Promise<void>((resolve) => {
    resolveRecordingDone = resolve;
  });

  const stopVad = () => {
    if (vadTimer != null) {
      clearInterval(vadTimer);
      vadTimer = null;
    }
  };

  const finishRecording = () => {
    stopVad();
    capturing = false;
    resolveRecordingDone?.();
  };

  const discardMic = () => {
    stopVad();
    capturing = false;
    try {
      processor.disconnect();
      silent.disconnect();
      source.disconnect();
    } catch {
      /* ignore */
    }
    stream.getTracks().forEach((t) => t.stop());
    void audioCtx.close().catch(() => {});
    resolveRecordingDone?.();
  };

  const beginBarge = (now: number) => {
    if (bargedIn) return;
    bargedIn = true;
    bargeStartedAt = now;
    lastLoudAt = now;
    // Seed capture with pre-roll so short words aren't clipped.
    captureChunks.push(...preRoll);
    preRoll.length = 0;
    preRollSamples = 0;
    capturing = true;
    hooks?.onBargeIn?.();
    stopSpeaking();
  };

  hooks?.onMicReady?.();

  vadTimer = setInterval(() => {
    if (hooks?.shouldCancel?.()) {
      cancelled = true;
      stopSpeaking();
      finishRecording();
      return;
    }
    const now = performance.now();
    const level = rms(analyser, timeBuf);

    if (!bargedIn) {
      baseline = baseline * 0.92 + level * 0.08;
    }

    if (now - startedAt < IGNORE_MS) return;

    const bargeThreshold = Math.max(RMS_FLOOR, baseline * BARGE_OVER_BASELINE);
    const loud = level >= bargeThreshold;

    if (!bargedIn) {
      if (!isSpeaking()) return;
      if (loud) {
        lastLoudAt = now;
        if (speechHoldStartedAt == null) speechHoldStartedAt = now;
        else if (now - speechHoldStartedAt >= SPEECH_HOLD_MS) {
          console.log("[barge-in] triggered", {
            level: Number(level.toFixed(4)),
            baseline: Number(baseline.toFixed(4)),
            threshold: Number(bargeThreshold.toFixed(4)),
          });
          beginBarge(now);
        }
      } else {
        speechHoldStartedAt = null;
      }
      return;
    }

    if (loud) lastLoudAt = now;
    if (
      now - lastLoudAt >= SILENCE_END_MS ||
      now - bargeStartedAt >= MAX_AFTER_BARGE_MS
    ) {
      finishRecording();
    }
  }, 40);

  await speak(text, speakOpts);

  if (cancelled || hooks?.shouldCancel?.()) {
    discardMic();
    return { bargedIn: false };
  }

  if (!bargedIn) {
    const now = performance.now();
    const recentlyLoud =
      lastLoudAt > 0 && now - lastLoudAt <= LATE_BARGE_MS;
    const heldSpeech =
      speechHoldStartedAt != null &&
      now - speechHoldStartedAt >= SPEECH_HOLD_MS;
    if (recentlyLoud || heldSpeech) {
      beginBarge(now);
      finishRecording();
    }
  }

  if (!bargedIn) {
    discardMic();
    return { bargedIn: false };
  }

  // Wait until silence end (unless late-barge already finished).
  if (capturing) {
    await recordingDone;
  }

  const samples = concatFloat32(captureChunks);
  try {
    processor.disconnect();
    silent.disconnect();
    source.disconnect();
  } catch {
    /* ignore */
  }
  stream.getTracks().forEach((t) => t.stop());
  void audioCtx.close().catch(() => {});

  if (cancelled || hooks?.shouldCancel?.()) {
    return { bargedIn: false };
  }

  const blob = encodeWav(samples, sampleRate);
  if (blob.size < MIN_WAV_BYTES || samples.length < sampleRate * 0.15) {
    console.log("[barge-in] clip too small, ignoring", {
      bytes: blob.size,
      samples: samples.length,
    });
    return { bargedIn: false };
  }
  console.log("[barge-in] sending clip", {
    bytes: blob.size,
    mimeType: "audio/wav",
    samples: samples.length,
    ms: Math.round((samples.length / sampleRate) * 1000),
  });
  return { bargedIn: true, blob, mimeType: "audio/wav" };
}
