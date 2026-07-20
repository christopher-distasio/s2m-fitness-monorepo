import Head from "next/head";
import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { supabase } from "../lib/supabaseClient";
import { speak as _speak, stopSpeaking, onSpeakingChange, isSpeaking } from "../lib/speak";
import { speakWithBargeIn } from "../lib/bargeIn";
import { formatBrandedName } from "../lib/foodName";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"] as const;

const STORAGE_KEYS = {
  summaryOnOpen: "speak2me_summary_on_open",
  autoListen: "speak2me_auto_listen",
  greetOnOpen: "speak2me_greet",
  mode: "speak2me_mode",
} as const;

/** Clears when the tab closes; survives refresh within the same session. */
const SESSION_GREETED_KEY = "speak2me_greeted_this_session";
const SESSION_VOICE_SETUP_STARTED = "speak2me_voice_setup_started";
const SESSION_VOICE_SETUP_COMPLETE = "speak2me_voice_setup_complete";
const SESSION_VOICE_SETUP_DISMISSED = "speak2me_voice_setup_dismissed";

const CONTINUE_VOICE_MESSAGE =
  "Welcome didn't finish, but we'll continue with voice.";

function hasGreetedThisSession(): boolean {
  if (typeof window === "undefined") return false;
  return sessionStorage.getItem(SESSION_GREETED_KEY) === "1";
}

function markGreetedThisSession(): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SESSION_GREETED_KEY, "1");
}

function markVoiceSetupStarted(): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SESSION_VOICE_SETUP_STARTED, "1");
  sessionStorage.removeItem(SESSION_VOICE_SETUP_COMPLETE);
  sessionStorage.removeItem(SESSION_VOICE_SETUP_DISMISSED);
}

function markVoiceSetupComplete(): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SESSION_VOICE_SETUP_COMPLETE, "1");
}

function isVoiceSetupIncomplete(): boolean {
  if (typeof window === "undefined") return false;
  return (
    sessionStorage.getItem(SESSION_VOICE_SETUP_STARTED) === "1" &&
    sessionStorage.getItem(SESSION_VOICE_SETUP_COMPLETE) !== "1"
  );
}

function isVoiceSetupRecoveryDismissed(): boolean {
  if (typeof window === "undefined") return false;
  return sessionStorage.getItem(SESSION_VOICE_SETUP_DISMISSED) === "1";
}

function dismissVoiceSetupRecovery(): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SESSION_VOICE_SETUP_DISMISSED, "1");
}

function clearVoiceSessionKeys(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(SESSION_GREETED_KEY);
  sessionStorage.removeItem(SESSION_VOICE_SETUP_STARTED);
  sessionStorage.removeItem(SESSION_VOICE_SETUP_COMPLETE);
  sessionStorage.removeItem(SESSION_VOICE_SETUP_DISMISSED);
}

function turnOffVoiceOnOpenPrefs(
  setters: {
    setGreetOnOpen: (v: boolean) => void;
    setSummaryOnOpen: (v: boolean) => void;
    setAutoListen: (v: boolean) => void;
  },
) {
  setters.setGreetOnOpen(false);
  setters.setSummaryOnOpen(false);
  setters.setAutoListen(false);
  persistBoolean(STORAGE_KEYS.greetOnOpen, false);
  persistBoolean(STORAGE_KEYS.summaryOnOpen, false);
  persistBoolean(STORAGE_KEYS.autoListen, false);
  markVoiceSetupComplete();
}

type AppMode = "see" | "speak";

const GREET_ON_OPEN_MESSAGE =
  "Welcome back. Say what you ate, ask for your total, or say delete my last entry.";

const HOW_IT_WORKS_TEXT =
  "In Speak mode, just talk. Say what you ate, ask for your total, or say delete my last entry. I will ask follow-up questions one at a time if I need more detail. In See mode, use the buttons. Switch modes anytime with the toggle at the top.";

const RECORDING_TIMEOUT_MS = 8000;
const MIN_RECORDING_BYTES = 8000;
// After any 8s mic silence (clarification, greet, manual speak), ask this —
// yes → listen another 8s; no → stop. Not the old "say that again / be more specific".
const MORE_TIME_MESSAGE = "Do you need more time?";
const SAY_NUMBER_OR_WORD = "Say the number or the word.";

function readStoredBoolean(key: string, defaultValue: boolean) {
  if (typeof window === "undefined") return defaultValue;
  const stored = localStorage.getItem(key);
  return stored === null ? defaultValue : stored === "true";
}

function persistBoolean(key: string, value: boolean) {
  localStorage.setItem(key, String(value));
}

function readStoredMode(defaultMode: AppMode = "see"): AppMode {
  if (typeof window === "undefined") return defaultMode;
  const stored = localStorage.getItem(STORAGE_KEYS.mode);
  return stored === "see" || stored === "speak" ? stored : defaultMode;
}

function persistMode(mode: AppMode) {
  localStorage.setItem(STORAGE_KEYS.mode, mode);
}

type SummarySnapshot = {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
};

function buildTodaysSummaryMessage(s: SummarySnapshot, goal: number) {
  const pct = Math.min(100, Math.round((s.calories / goal) * 100));
  return `Today you've had ${s.calories} calories. Protein: ${Number(s.protein).toFixed(1)} grams. Carbs: ${Number(s.carbs).toFixed(1)} grams. Fat: ${Number(s.fat).toFixed(1)} grams. You're at ${pct}% of your daily goal.`;
}

function VoiceSetupRecoveryPanel({
  onContinue,
  onDismiss,
  continuing,
}: {
  onContinue: () => void;
  onDismiss: () => void;
  continuing: boolean;
}) {
  return (
    <div
      role="region"
      aria-label="Continue voice setup"
      className="w-full max-w-sm rounded-lg border border-amber-400/40 bg-amber-950/50 px-4 py-3 text-left"
    >
      <p className="text-sm text-amber-100 mb-2">Welcome didn&apos;t finish.</p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onContinue}
          disabled={continuing}
          className="px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-60 text-blue-950 text-sm font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
        >
          {continuing ? "Continuing…" : "Continue with voice"}
        </button>
        <button
          type="button"
          onClick={onDismiss}
          disabled={continuing}
          className="px-3 py-2 text-amber-100/90 hover:text-white text-sm font-medium rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

function MenuSwitch({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const labelId = `${id}-label`;

  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2.5 hover:bg-white/5">
      <span id={labelId} className="text-xs font-medium text-white/90">
        {label}
      </span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        onClick={() => onChange(!checked)}
        className={`relative box-border h-5 w-9 shrink-0 cursor-pointer overflow-hidden rounded-full border p-0.5 transition-colors focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-0 ${
          checked
            ? "border-blue-300 bg-blue-500"
            : "border-white/40 bg-white/20"
        }`}
      >
        <span
          aria-hidden="true"
          className={`absolute top-1/2 size-3 -translate-y-1/2 rounded-full bg-white shadow-sm transition-[left,right] duration-200 ease-in-out ${
            checked ? "right-0.5 left-auto" : "left-0.5 right-auto"
          }`}
        />
      </button>
    </div>
  );
}

interface FoodLog {
  _id: string;
  food_name: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  quantity: string;
  raw_input: string;
  logged_at: string;
  confidence?: "high" | "medium" | "low";
  reasoning?: string;
  alternatives?: string[];
}

interface FoodCandidate {
  fdc_id: string;
  name: string;
  brand?: string;
  serving_label?: string;
  serving_size_g?: number;
  serving_source?: string;
  serving_note?: string | null;
  score?: number;
  source?: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
}

interface PortionOption {
  label: string;
  gram_weight: number;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
}

interface ParsedResult {
  food: string;
  calories: number;
  serving_size?: string;
  brand?: string | null;
  serving_label?: string;
  serving_note?: string | null;
  macronutrients?: {
    carbohydrates: number;
    protein: number;
    fats: number;
    sugar: number;
  };
  confidence?: "high" | "medium" | "low";
  reasoning?: string;
  alternatives?: string[];
  candidates?: FoodCandidate[];
  portion_options?: PortionOption[];
  notes?: string;
  resolution?: {
    status?: "resolved" | "needs_clarification" | "needs_brand_choice";
    axis?: string | null;
    reason?: string;
    question?: string;
  };
}

// The upfront brand-vs-generic question. Kept identical for text and voice so
// the two flows can't drift (same lesson as the spoken-message bug).
const BRAND_CHOICE_QUESTION =
  "Are you looking for a specific brand, or a general item?";
const BRAND_CHOICE_SPEECH = `${SAY_NUMBER_OR_WORD} ${BRAND_CHOICE_QUESTION} Number 1: general. Number 2: specific.`;

function isBrandChoice(parsed: ParsedResult): boolean {
  return parsed.resolution?.status === "needs_brand_choice";
}

// Trim limits for the clarification list. The visual card can show a bit more
// since it's scannable at a glance; the spoken voice list is deliberately
// shorter (a long read-aloud is tiring) but "more" still reveals the full list.
const MAX_VOICE_OPTIONS = 3;

interface ClarifyOption {
  key: string;
  kind: "candidate" | "portion";
  speech: string;
  title: string;
  subtitle?: string;
  calories: number;
  pick: {
    food_name: string;
    calories: number;
    protein?: number;
    carbs?: number;
    fat?: number;
    quantity?: string;
    raw_input: string;
  };
}

/**
 * The grounded candidate foods to offer as "did you mean?" — everything the
 * retrieval returned except the one already chosen as the primary. This is the
 * SINGLE source used for BOTH the visual candidate buttons and the spoken
 * clarification, so the two can never drift apart (the bug where voice dropped
 * "Bananas, raw" happened because they were built separately).
 */
function clarificationCandidates(parsed: ParsedResult): FoodCandidate[] {
  const chosen = (parsed.food || "").trim().toLowerCase();
  return (parsed.candidates || []).filter(
    (c) => (c.name || "").trim().toLowerCase() !== chosen,
  );
}

function speakCandidate(c: FoodCandidate): string {
  const name = formatBrandedName(c.name, c.brand);
  return c.calories != null
    ? `${name}, ${Math.round(c.calories)} calories`
    : name;
}

/**
 * The FULL flat, ordered list of selectable options: candidates first, then
 * portions — same top-to-bottom order the card renders and voice speaks. Each
 * option carries the exact logResolved() payload. Not trimmed here; callers
 * apply MAX_VOICE_OPTIONS via clarifyOptions().
 */
function allClarifyOptions(
  parsed: ParsedResult,
  rawInput: string,
): ClarifyOption[] {
  const candidates = clarificationCandidates(parsed);
  const allPortions = parsed.portion_options || [];
  const portions = allPortions.length > 1 ? allPortions : [];
  const foodName = formatBrandedName(parsed.food, parsed.brand);
  const options: ClarifyOption[] = [];
  for (const c of candidates) {
    options.push({
      key: `c-${c.fdc_id}`,
      kind: "candidate",
      speech: speakCandidate(c),
      title: formatBrandedName(c.name, c.brand),
      subtitle: c.serving_label,
      calories: c.calories ?? 0,
      pick: {
        food_name: formatBrandedName(c.name, c.brand),
        calories: c.calories,
        protein: c.protein,
        carbs: c.carbs,
        fat: c.fat,
        quantity: c.serving_label,
        raw_input: rawInput,
      },
    });
  }
  for (const p of portions) {
    options.push({
      key: `p-${p.label}`,
      kind: "portion",
      speech: `${p.label}, ${Math.round(p.calories)} calories`,
      title: p.label,
      calories: p.calories,
      pick: {
        food_name: foodName,
        calories: p.calories,
        protein: p.protein,
        carbs: p.carbs,
        fat: p.fat,
        quantity: p.label,
        raw_input: rawInput,
      },
    });
  }
  return options;
}

/**
 * Options shown on the card AND offered by voice right now: top
 * MAX_VOICE_OPTIONS by default, or the full list once expanded ("more" /
 * "See more"). Numbering on-screen and aloud always use this same list.
 */
function clarifyOptions(
  parsed: ParsedResult,
  rawInput: string,
  expanded: boolean,
): ClarifyOption[] {
  const all = allClarifyOptions(parsed, rawInput);
  return expanded ? all : all.slice(0, MAX_VOICE_OPTIONS);
}

function formatNumberedSpeech(
  options: Array<{ speech: string }>,
  startIndex = 1,
): string {
  return options
    .map((o, i) => `Number ${startIndex + i}: ${o.speech}`)
    .join(". ");
}

function withNumberCue(body: string, offerMore = false): string {
  let msg = `${SAY_NUMBER_OR_WORD} ${body}`;
  if (offerMore) msg += " Or say more to hear the rest.";
  return msg;
}

function buildNumberedClarificationSpeech(
  parsed: ParsedResult,
  rawInput: string,
  expanded: boolean,
): string {
  const all = allClarifyOptions(parsed, rawInput);
  if (all.length === 0) {
    const alts = parsed.alternatives ?? [];
    if (alts.length > 0) {
      const numbered = formatNumberedSpeech(alts.map((a) => ({ speech: a })));
      return withNumberCue(
        `I think this is ${parsed.food}. Did you mean: ${numbered}.`,
      );
    }
    return `I wasn't sure about that.${
      parsed.reasoning ? ` ${parsed.reasoning}.` : ""
    } Please be more specific.`;
  }
  const options = clarifyOptions(parsed, rawInput, expanded);
  const hasMore = all.length > options.length;
  const numbered = formatNumberedSpeech(options);
  return withNumberCue(
    `I think this is ${parsed.food}. Did you mean: ${numbered}.`,
    hasMore,
  );
}

function buildSpeechFromSpokenOptions(
  parsed: ParsedResult,
  options: ClarifyOption[],
  offerMore: boolean,
): string {
  if (options.length === 0) {
    return buildNumberedClarificationSpeech(parsed, "", true);
  }
  const numbered = formatNumberedSpeech(options);
  return withNumberCue(
    `I think this is ${parsed.food}. Did you mean: ${numbered}.`,
    offerMore,
  );
}

function buildMoreClarificationSpeech(
  parsed: ParsedResult,
  rawInput: string,
): string {
  const all = allClarifyOptions(parsed, rawInput);
  const additional = all.slice(MAX_VOICE_OPTIONS);
  if (additional.length === 0) {
    return buildNumberedClarificationSpeech(parsed, rawInput, true);
  }
  const numbered = formatNumberedSpeech(additional, MAX_VOICE_OPTIONS + 1);
  const lead =
    additional.length === 1 ? "Here's the other option" : "Here are the rest";
  return withNumberCue(`${lead}: ${numbered}.`);
}

export default function Home() {
  const [textInput, setTextInput] = useState("");
  const [logs, setLogs] = useState<FoodLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  // Refs so maybeAutoListen / startRecording see current flags after barge-in
  // TTS (React state can still be true when we try to reopen the mic).
  const loadingRef = useRef(false);
  const recordingRef = useRef(false);
  const setLoadingBoth = (value: boolean) => {
    loadingRef.current = value;
    setLoading(value);
  };
  const setRecordingBoth = (value: boolean) => {
    recordingRef.current = value;
    setRecording(value);
  };
  const [autoListening, setAutoListening] = useState(false);
  const [status, setStatus] = useState("");
  const [summary, setSummary] = useState({
    calories: 0,
    protein: 0,
    carbs: 0,
    fat: 0,
    entry_count: 0,
  });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editInput, setEditInput] = useState("");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [calorieGoal, setCalorieGoal] = useState(2000);
  const [goalInput, setGoalInput] = useState("");
  const editInputRef = useRef<HTMLInputElement | null>(null);
  const textInputRef = useRef<HTMLInputElement | null>(null);
  const confidenceSectionRef = useRef<HTMLElement | null>(null);
  const pendingParseWasNullRef = useRef(true);
  const [userId, setUserId] = useState<string | null>(null);
  const [pendingParse, setPendingParse] = useState<{
    parsed: ParsedResult;
    raw_input: string;
    uid: string;
  } | null>(null);
  const [selectedVoice, setSelectedVoice] = useState("alloy");
  const [menuOpen, setMenuOpen] = useState(false);
  const [howItWorksOpen, setHowItWorksOpen] = useState(false);
  const [summaryOnOpen, setSummaryOnOpen] = useState(false);
  const [autoListen, setAutoListen] = useState(false);
  const [greetOnOpen, setGreetOnOpen] = useState(true);
  const [mounted, setMounted] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [mode, setMode] = useState<AppMode>("see");
  const streamRef = useRef<MediaStream | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const hasOnOpenSpokenRef = useRef(false);
  const pendingParseRef = useRef(pendingParse);
  const postLoginVoiceSessionRef = useRef(false);
  const recordingTimedOutRef = useRef(false);
  const recordingTimeoutIdRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const startRecordingRef = useRef<
    (options?: { fromAutoListen?: boolean }) => Promise<void>
  >(async () => {});
  const [muted, setMuted] = useState(false);
  const [showNutrients, setShowNutrients] = useState({
    protein: false,
    carbs: false,
    fat: false,
  });
  const [conversationHistory, setConversationHistory] = useState<
    Array<{ role: "user" | "assistant"; content: string }>
  >([]);
  // conversation_history is only for (1) backend open-prompt detection
  // (clarification_state) and (2) quantity-prepend in the food parser. It does
  // NOT store the spoken option list — that lives in spokenClarifyOptionsRef
  // below. Same ref pattern as pendingParseRef: recorder onstop must not close
  // over a stale empty history (e.g. muted TTS returns before React re-renders).
  const conversationHistoryRef = useRef(conversationHistory);
  const setConversationHistoryBoth = useCallback(
    (
      next:
        | Array<{ role: "user" | "assistant"; content: string }>
        | ((
            prev: Array<{ role: "user" | "assistant"; content: string }>,
          ) => Array<{ role: "user" | "assistant"; content: string }>),
    ) => {
      if (typeof next === "function") {
        setConversationHistory((prev) => {
          const updated = next(prev);
          conversationHistoryRef.current = updated;
          return updated;
        });
      } else {
        conversationHistoryRef.current = next;
        setConversationHistory(next);
      }
    },
    [],
  );
  // Whether the clarification list is expanded past the trimmed default. Drives
  // BOTH the visual "See more" and the voice "more" command, and is read inside
  // the recorder's onstop closure (hence the ref) so "repeat"/number-selection
  // always act on the most recently shown list.
  const [clarifyExpanded, setClarifyExpanded] = useState(false);
  const clarifyExpandedRef = useRef(false);
  const setClarifyExpandedBoth = useCallback((value: boolean) => {
    clarifyExpandedRef.current = value;
    setClarifyExpanded(value);
  }, []);
  // The option list most recently spoken in this clarification turn. Number
  // selection and "repeat" resolve against THIS — not a regenerated slice —
  // so after "more" appends the trimmed-off items, later replies stay
  // consistent with the full expanded set. Owned by the frontend (not
  // conversation_history / clarification.py); those only classify the reply.
  const spokenClarifyOptionsRef = useRef<ClarifyOption[]>([]);
  const rememberSpokenClarifyOptions = (options: ClarifyOption[]) => {
    spokenClarifyOptionsRef.current = options;
  };
  const clearSpokenClarifyOptions = () => {
    spokenClarifyOptionsRef.current = [];
  };
  // Set when we just asked MORE_TIME_MESSAGE; the next voice reply is yes/no
  // (or a normal answer that falls through). Applies to every mic session.
  const awaitingMoreTimeReplyRef = useRef(false);
  // User tapped Speak-to-me while already listening — discard the clip silently.
  const cancelRecordingRef = useRef(false);
  // User cut TTS with the Speak button — don't auto-open the mic afterward.
  const suppressAutoListenRef = useRef(false);
  // Active barge-in session: Speak/Stop sets this to discard the mic clip.
  const cancelBargeInRef = useRef<(() => void) | null>(null);
  const processVoiceBlobRef = useRef<
    (blob: Blob, mimeType: string, uid: string) => Promise<void>
  >(async () => {});
  const [speaking, setSpeaking] = useState(false);
  const [showVoiceSetupRecovery, setShowVoiceSetupRecovery] = useState(false);
  const [continuingVoiceSetup, setContinuingVoiceSetup] = useState(false);

  const router = useRouter();

  const fetchLogs = useCallback(
    async (uid?: string) => {
      const id = uid ?? userId;
      if (!id) return;
      const res = await fetch(`${API_BASE}/food/${id}/today`);
      const data = await res.json();
      setLogs(data.reverse());
    },
    [userId],
  );

  const fetchSummary = useCallback(
    async (uid?: string) => {
      const id = uid ?? userId;
      if (!id) return;
      const res = await fetch(`${API_BASE}/food/${id}/summary`);
      const data = await res.json();
      setSummary(data);
      return data as typeof summary;
    },
    [userId],
  );

  const fetchProfile = useCallback(async (uid?: string) => {
    const id =
      uid ??
      (
        await supabase.auth.getSession()
      ).data.session?.user.id;
    if (!id) return;
    const res = await fetch(`${API_BASE}/user/${id}/profile`);
    const data = await res.json();
    setCalorieGoal(data.calorie_goal);
    return data as { calorie_goal: number };
  }, []);

  const GUEST_USER_ID = "c0daaa18-4a82-4022-be8e-e21224683f88";
  const isGuest = userId === GUEST_USER_ID;

  const caloriePercent = Math.min(
    100,
    Math.round((summary.calories / calorieGoal) * 100),
  );

  const speak = useCallback(
    (text: string) => _speak(text, { muted, selectedVoice, apiBase: API_BASE }),
    [muted, selectedVoice],
  );

  /**
   * Numbered clarification TTS with mic open for barge-in. Returns true when a
   * barge-in clip was handled (or Stop discarded it) — caller should skip
   * maybeAutoListen. Works in See and Speak (mic exists in both); muted falls
   * back to plain speak.
   */
  async function speakClarificationWithBargeIn(
    msg: string,
    uid: string,
  ): Promise<boolean> {
    if (muted) {
      await speak(msg);
      return false;
    }
    let cancelled = false;
    cancelBargeInRef.current = () => {
      cancelled = true;
    };
    setAutoListening(true);
    const result = await speakWithBargeIn(
      msg,
      { muted, selectedVoice, apiBase: API_BASE },
      {
        onMicReady: () => setRecordingBoth(true),
        onBargeIn: () => setStatus("Listening..."),
        shouldCancel: () => cancelled || suppressAutoListenRef.current,
      },
    );
    cancelBargeInRef.current = null;
    // Flush so follow-on maybeAutoListen / startRecording see mic free.
    flushSync(() => {
      setRecordingBoth(false);
      setAutoListening(false);
    });

    if (suppressAutoListenRef.current) {
      suppressAutoListenRef.current = false;
      return true;
    }
    if (!result.bargedIn) return false;
    await processVoiceBlobRef.current(result.blob, result.mimeType, uid);
    return true;
  }

  const speakTodaysSummary = useCallback(
    async (s: SummarySnapshot, goal: number) => {
      await speak(buildTodaysSummaryMessage(s, goal));
    },
    [speak],
  );

  const setModeAndPersist = useCallback((next: AppMode) => {
    setMode(next);
    persistMode(next);
    if (next === "see") {
      turnOffVoiceOnOpenPrefs({
        setGreetOnOpen,
        setSummaryOnOpen,
        setAutoListen,
      });
    }
  }, []);

  const wantsVoiceOnOpen = greetOnOpen || summaryOnOpen;

  const shouldOfferVoiceSetupRecovery = useCallback(() => {
    return (
      wantsVoiceOnOpen &&
      isVoiceSetupIncomplete() &&
      !isVoiceSetupRecoveryDismissed()
    );
  }, [wantsVoiceOnOpen]);

  const maybeAutoListen = useCallback(async () => {
    if (suppressAutoListenRef.current) {
      suppressAutoListenRef.current = false;
      return;
    }
    if (muted || loadingRef.current || recordingRef.current) {
      return;
    }
    const awaitingClarification = pendingParseRef.current !== null;
    const awaitingPostLogin = postLoginVoiceSessionRef.current;
    // Clarification answers re-open the mic in BOTH See and Speak — the Speak
    // button exists in both modes and must keep listening after choices.
    if (awaitingClarification) {
      await startRecordingRef.current({ fromAutoListen: true });
      return;
    }
    // Post-login greet auto-listen stays Speak-mode + pref gated.
    if (mode !== "speak" || !autoListen || !awaitingPostLogin) return;
    await startRecordingRef.current({ fromAutoListen: true });
  }, [autoListen, mode, muted]);

  const runOpenVoiceSetup = useCallback(
    async (options?: { isRecovery?: boolean }) => {
      if (!userId) return;
      markVoiceSetupStarted();
      const summaryData =
        (await fetchSummary(userId)) ?? summary;
      const profileData = await fetchProfile(userId);
      const goal = profileData?.calorie_goal ?? calorieGoal;

      if (options?.isRecovery) {
        await speak(CONTINUE_VOICE_MESSAGE);
      }

      const greetedThisSession = hasGreetedThisSession();
      if (greetOnOpen && !greetedThisSession) {
        markGreetedThisSession();
        await speak(GREET_ON_OPEN_MESSAGE);
      }
      if (summaryOnOpen) {
        await speakTodaysSummary(summaryData, goal);
      }
      if (autoListen && wantsVoiceOnOpen) {
        postLoginVoiceSessionRef.current = true;
      }
      markVoiceSetupComplete();
      flushSync(() => setLoadingBoth(false));
      await maybeAutoListen();
    },
    [
      userId,
      summary,
      calorieGoal,
      greetOnOpen,
      summaryOnOpen,
      autoListen,
      wantsVoiceOnOpen,
      fetchSummary,
      fetchProfile,
      speak,
      speakTodaysSummary,
      maybeAutoListen,
    ],
  );

  const continueWithVoice = useCallback(async () => {
    if (continuingVoiceSetup) return;
    setContinuingVoiceSetup(true);
    setShowVoiceSetupRecovery(false);
    hasOnOpenSpokenRef.current = true;
    try {
      flushSync(() => setMode("speak"));
      persistMode("speak");
      await runOpenVoiceSetup({ isRecovery: true });
    } finally {
      setContinuingVoiceSetup(false);
    }
  }, [continuingVoiceSetup, runOpenVoiceSetup]);

  const handleDismissVoiceSetupRecovery = useCallback(() => {
    dismissVoiceSetupRecovery();
    setShowVoiceSetupRecovery(false);
    hasOnOpenSpokenRef.current = true;
  }, []);

  useEffect(() => {
    const initialMode = readStoredMode("see");
    setMode(initialMode);
    persistMode(initialMode);
    if (initialMode === "see") {
      turnOffVoiceOnOpenPrefs({
        setGreetOnOpen,
        setSummaryOnOpen,
        setAutoListen,
      });
    } else {
      setSummaryOnOpen(readStoredBoolean(STORAGE_KEYS.summaryOnOpen, false));
      setAutoListen(readStoredBoolean(STORAGE_KEYS.autoListen, false));
      setGreetOnOpen(readStoredBoolean(STORAGE_KEYS.greetOnOpen, true));
    }
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!userId || !mounted) return;
    let cancelled = false;
    (async () => {
      await fetchLogs(userId);
      const [summaryData] = await Promise.all([
        fetchSummary(userId),
        fetchProfile(userId),
      ]);
      if (cancelled || hasOnOpenSpokenRef.current || !summaryData) return;

      if (shouldOfferVoiceSetupRecovery()) {
        hasOnOpenSpokenRef.current = true;
        setShowVoiceSetupRecovery(true);
        return;
      }

      // See mode: no unsolicited audio on open (foundational principle).
      if (mode !== "speak") {
        hasOnOpenSpokenRef.current = true;
        return;
      }

      if (!wantsVoiceOnOpen) {
        hasOnOpenSpokenRef.current = true;
        return;
      }

      hasOnOpenSpokenRef.current = true;
      await runOpenVoiceSetup();
    })();
    return () => {
      cancelled = true;
    };
  }, [
    userId,
    mounted,
    mode,
    fetchLogs,
    fetchSummary,
    fetchProfile,
    greetOnOpen,
    summaryOnOpen,
    wantsVoiceOnOpen,
    shouldOfferVoiceSetupRecovery,
    runOpenVoiceSetup,
  ]);

  useEffect(() => {
    pendingParseRef.current = pendingParse;
  }, [pendingParse]);

  useEffect(() => {
    conversationHistoryRef.current = conversationHistory;
  }, [conversationHistory]);

  useEffect(() => onSpeakingChange(setSpeaking), []);

  useEffect(() => {
    if (!status) return;
    const timer = setTimeout(() => setStatus(""), 5000);
    return () => clearTimeout(timer);
  }, [status]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
    }
  }, [editingId]);

  useEffect(() => {
    if (pendingParse && pendingParseWasNullRef.current) {
      queueMicrotask(() => confidenceSectionRef.current?.focus());
      pendingParseWasNullRef.current = false;
    } else if (!pendingParse) {
      pendingParseWasNullRef.current = true;
    }
  }, [pendingParse]);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) router.push("/login");
      else setUserId(session.user.id);
    });
  }, [router]);

  useEffect(() => {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) router.push("/login");
      else setUserId(session.user.id);
    });
    return () => subscription.unsubscribe();
  }, [router]);

  useEffect(() => {
    if (!userId) hasOnOpenSpokenRef.current = false;
  }, [userId]);

  useEffect(() => {
    if (!menuOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node)
      ) {
        setMenuOpen(false);
        setHowItWorksOpen(false);
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setHowItWorksOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!userId) return;
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) router.push("/login");
    });
  }, [router, userId]);

  async function signOut() {
    if (!userId) return;
    setMenuOpen(false);
    clearVoiceSessionKeys();
    endPostLoginVoiceSession();
    clearRecordingTimeout();
    await supabase.auth.signOut();
    router.push("/login");
  }

  function clearRecordingTimeout() {
    if (recordingTimeoutIdRef.current) {
      clearTimeout(recordingTimeoutIdRef.current);
      recordingTimeoutIdRef.current = null;
    }
  }

  function endPostLoginVoiceSession() {
    postLoginVoiceSessionRef.current = false;
  }

  async function handleRecordingSilenceTimeout() {
    // Every mic silence (clarify, greet, manual speak): ask more time, then
    // listen for yes (another 8s) / no (stop).
    awaitingMoreTimeReplyRef.current = true;
    setStatus(MORE_TIME_MESSAGE);
    await speak(MORE_TIME_MESSAGE);
    if (suppressAutoListenRef.current) {
      suppressAutoListenRef.current = false;
      return;
    }
    if (!muted && !recordingRef.current) {
      await startRecordingRef.current({ fromAutoListen: true });
    }
  }

  /** Speak button: stop TTS, or cancel listening, or start recording. */
  function handleSpeakButtonClick() {
    if (isSpeaking() || speaking || cancelBargeInRef.current) {
      suppressAutoListenRef.current = true;
      cancelBargeInRef.current?.();
      stopSpeaking();
      setRecordingBoth(false);
      setAutoListening(false);
      return;
    }
    if (recording) {
      cancelListeningSilent();
      return;
    }
    void startRecording();
  }

  async function submitText() {
    // Text wins over any in-progress TTS — cut speech immediately.
    stopSpeaking();
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    if (!textInput.trim()) return;
    setLoadingBoth(true);
    setStatus("Parsing...");
    const uid = session.user.id;
    let shouldAutoListen = false;
    try {
      const res = await fetch(`${API_BASE}/food/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          raw_input: textInput,
          conversation_history: conversationHistory,
        }),
      });
      const parsed = await res.json();

      if (parsed.error) {
        const err =
          "I couldn't understand that. Please try saying something more specific.";
        setStatus(err);
        await speak(err);
        return;
      }

      if (parsed.confidence === "high") {
        const resolvedInput = `${parsed.serving_size} ${parsed.food}`;
        await confirmLog(uid, resolvedInput);
      } else {
        setConversationHistoryBoth((prev) => [
          ...prev,
          { role: "user", content: textInput },
          { role: "assistant", content: JSON.stringify(parsed) },
        ]);
        const pending = { parsed, raw_input: textInput, uid };
        setPendingParse(pending);
        pendingParseRef.current = pending;
        setClarifyExpandedBoth(false);
        clearSpokenClarifyOptions();
        let msg: string;
        if (isBrandChoice(parsed)) {
          msg = `I think this is ${parsed.food}. ${BRAND_CHOICE_SPEECH}`;
        } else if (parsed.confidence === "low") {
          msg = `I wasn't sure about that. ${parsed.reasoning}. Please be more specific.`;
        } else {
          rememberSpokenClarifyOptions(
            clarifyOptions(parsed, textInput, false),
          );
          msg = buildNumberedClarificationSpeech(parsed, textInput, false);
        }
        setStatus(msg);
        setTextInput("");
        const numberedClarify =
          isBrandChoice(parsed) || parsed.confidence !== "low";
        if (numberedClarify) {
          const barged = await speakClarificationWithBargeIn(msg, uid);
          if (!barged) shouldAutoListen = true;
        } else {
          shouldAutoListen = true;
          await speak(msg);
        }
      }
    } catch {
      const err = "Error logging food.";
      setStatus(err);
      await speak(err);
    } finally {
      flushSync(() => setLoadingBoth(false));
    }
    if (shouldAutoListen) await maybeAutoListen();
  }

  async function deleteLog(id: string) {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    const uid = session.user.id;
    if (!confirm("Delete this entry?")) return;
    await fetch(`${API_BASE}/food/${id}`, { method: "DELETE" });
    await fetchLogs(uid);
    await fetchSummary(uid);
  }

  async function saveEdit(id: string) {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    const uid = session.user.id;
    if (!editInput.trim()) return;
    await fetch(`${API_BASE}/food/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_input: editInput, user_id: userId }),
    });
    setEditingId(null);
    fetchLogs(uid);
    fetchSummary(uid);
  }

  async function processVoiceBlob(
    blob: Blob,
    mimeType: string,
    uid: string,
  ) {
    const extension = mimeType.includes("wav")
      ? "wav"
      : mimeType === "audio/webm"
        ? "webm"
        : "mp4";
    const wasAwaitingClarification = pendingParseRef.current !== null;
    const pendingForFlag = pendingParseRef.current;
    const awaitingClarificationFlag = !pendingForFlag
      ? "false"
      : isBrandChoice(pendingForFlag.parsed)
        ? "brand_choice"
        : "list";

    const formData = new FormData();
    formData.append("user_id", uid);
    formData.append("audio", blob, `recording.${extension}`);
    formData.append(
      "conversation_history",
      JSON.stringify(conversationHistoryRef.current),
    );
    formData.append(
      "awaiting_more_time",
      awaitingMoreTimeReplyRef.current ? "true" : "false",
    );
    formData.append("awaiting_clarification", awaitingClarificationFlag);
    setLoadingBoth(true);
    setStatus("Transcribing...");
    let shouldAutoListen = false;
    let voiceResponseStatus: number | undefined;
    let voiceResponseBody: unknown;
    try {
      const res = await fetch(`${API_BASE}/food/voice`, {
        method: "POST",
        body: formData,
      });
      voiceResponseStatus = res.status;
      const responseText = await res.text();
      try {
        voiceResponseBody = JSON.parse(responseText);
      } catch {
        voiceResponseBody = responseText;
      }
      const data = voiceResponseBody as {
        error?: string;
        message?: string;
        transcription?: string;
        parsed?: ParsedResult;
        clarification?: {
          type:
            | "select"
            | "repeat"
            | "more"
            | "brand_choice"
            | "more_time"
            | "stop"
            | "unrecognized";
          index?: number;
          value?: "generic" | "brand";
        };
      };

      if (!res.ok) {
        throw new Error(
          `Voice API ${res.status}: ${responseText.slice(0, 500)}`,
        );
      }

      console.log(
        "[voice] transcribed",
        JSON.stringify({
          transcription: data.transcription,
          clarification: data.clarification,
          wasAwaitingClarification,
          historyLen: conversationHistoryRef.current.length,
          awaitingClarificationFlag,
        }),
      );

      // "Stop" anytime, or "Do you need more time?" yes/no.
      if (data.clarification?.type === "stop") {
        awaitingMoreTimeReplyRef.current = false;
        stopSpeaking();
        dismissPending();
        endPostLoginVoiceSession();
        setStatus("");
        return;
      }
      if (data.clarification?.type === "more_time") {
        awaitingMoreTimeReplyRef.current = false;
        flushSync(() => setLoadingBoth(false));
        await startRecordingRef.current({ fromAutoListen: true });
        return;
      }
      if (awaitingMoreTimeReplyRef.current) {
        awaitingMoreTimeReplyRef.current = false;
      }

      // Clarification commands are classified on the backend from
      // conversation_history; the frontend only acts on the result.
      let handledClarification = false;
      if (wasAwaitingClarification && data.clarification) {
        const pending = pendingParseRef.current;
        if (pending) {
          handledClarification = true;
          const cmd = data.clarification;
          if (cmd.type === "brand_choice" && cmd.value) {
            const barged = await resolveWithSource(
              pending.uid,
              pending.raw_input,
              cmd.value,
            );
            if (!barged) shouldAutoListen = true;
          } else if (cmd.type === "select" && cmd.index != null) {
            // Resolve against the list most recently spoken (trimmed default,
            // or full expanded set after "more") — no re-parse. Fall back to
            // the expand-flag slice only if we somehow never recorded a list.
            const options =
              spokenClarifyOptionsRef.current.length > 0
                ? spokenClarifyOptionsRef.current
                : clarifyOptions(
                    pending.parsed,
                    pending.raw_input,
                    clarifyExpandedRef.current,
                  );
            const chosen = options[cmd.index - 1];
            if (chosen) {
              await logResolved(pending.uid, chosen.pick);
              return;
            }
            const offerMore =
              allClarifyOptions(pending.parsed, pending.raw_input).length >
              options.length;
            const msg = `I only have ${options.length} option${options.length === 1 ? "" : "s"}. ${buildSpeechFromSpokenOptions(pending.parsed, options, offerMore)}`;
            setStatus(msg);
            const barged = await speakClarificationWithBargeIn(
              msg,
              pending.uid,
            );
            if (!barged) shouldAutoListen = true;
          } else if (cmd.type === "more") {
            // Speak only the trimmed-off items, then append them to the
            // tracked spoken list so later number/repeat use the full set.
            const all = allClarifyOptions(
              pending.parsed,
              pending.raw_input,
            );
            setClarifyExpandedBoth(true);
            rememberSpokenClarifyOptions(all);
            const msg = buildMoreClarificationSpeech(
              pending.parsed,
              pending.raw_input,
            );
            setStatus(msg);
            const barged = await speakClarificationWithBargeIn(
              msg,
              pending.uid,
            );
            if (!barged) shouldAutoListen = true;
          } else if (cmd.type === "unrecognized") {
            // Missed the number — re-ask without re-parsing food (that looped
            // the same list). Brand gate gets the brand prompt again.
            const msg = isBrandChoice(pending.parsed)
              ? `I didn't catch that. ${BRAND_CHOICE_SPEECH}`
              : (() => {
                  const options =
                    spokenClarifyOptionsRef.current.length > 0
                      ? spokenClarifyOptionsRef.current
                      : clarifyOptions(
                          pending.parsed,
                          pending.raw_input,
                          clarifyExpandedRef.current,
                        );
                  const offerMore =
                    allClarifyOptions(pending.parsed, pending.raw_input)
                      .length > options.length;
                  return `I didn't catch a number. ${buildSpeechFromSpokenOptions(pending.parsed, options, offerMore)}`;
                })();
            setStatus(msg);
            const barged = await speakClarificationWithBargeIn(
              msg,
              pending.uid,
            );
            if (!barged) shouldAutoListen = true;
          } else {
            // "repeat" — exact list most recently spoken (same items/order).
            const options =
              spokenClarifyOptionsRef.current.length > 0
                ? spokenClarifyOptionsRef.current
                : clarifyOptions(
                    pending.parsed,
                    pending.raw_input,
                    clarifyExpandedRef.current,
                  );
            const offerMore =
              allClarifyOptions(pending.parsed, pending.raw_input).length >
              options.length;
            const msg = buildSpeechFromSpokenOptions(
              pending.parsed,
              options,
              offerMore,
            );
            setStatus(msg);
            const barged = await speakClarificationWithBargeIn(
              msg,
              pending.uid,
            );
            if (!barged) shouldAutoListen = true;
          }
        }
      }

      if (!handledClarification) {
        if (data.error) {
          const err =
            "I couldn't understand that. Please try saying something more specific.";
          setStatus(err);
          await speak(err);
          if (wasAwaitingClarification) shouldAutoListen = true;
          return;
        }

        if (data.message && !data.parsed) {
          setStatus(data.message);
          await speak(data.message);
          fetchLogs(uid);
          await fetchSummary(uid);
          return;
        }

        if (!data.parsed) {
          throw new Error("Voice API response missing parsed food data");
        }

        console.log("[voice] processVoiceBlob response", {
          confidence: data.parsed.confidence,
          parsed: data.parsed,
          transcription: data.transcription,
        });

        if (data.parsed.confidence === "high") {
          const msg = `Logged ${data.parsed.food}, ${Math.round(data.parsed.calories ?? 0)} calories`;
          setStatus(
            `Heard: "${data.transcription}" — ${data.parsed.food}, ${Math.round(data.parsed.calories ?? 0)} cal`,
          );
          await speak(msg);
          await fetchLogs(uid);
          await fetchSummary(uid);
          setPendingParse(null);
          pendingParseRef.current = null;
          setConversationHistoryBoth([]);
          clearSpokenClarifyOptions();
          endPostLoginVoiceSession();
        } else {
          const pending = {
            parsed: data.parsed,
            raw_input: data.transcription ?? "",
            uid,
          };
          setPendingParse(pending);
          pendingParseRef.current = pending;
          setClarifyExpandedBoth(false);
          setConversationHistoryBoth((prev) => [
            ...prev,
            { role: "user", content: data.transcription ?? "" },
            { role: "assistant", content: JSON.stringify(data.parsed) },
          ]);
          // Brand-vs-generic gate comes first; otherwise a numbered list so
          // the user can answer "one", "two"… (even at low confidence, as
          // long as there are grounded options — the builder falls back to a
          // "be more specific" prompt only when there's genuinely nothing).
          let msg: string;
          if (isBrandChoice(data.parsed)) {
            clearSpokenClarifyOptions();
            msg = `I think this is ${data.parsed.food}. ${BRAND_CHOICE_SPEECH}`;
          } else {
            const spoken = clarifyOptions(
              data.parsed,
              data.transcription ?? "",
              false,
            );
            rememberSpokenClarifyOptions(spoken);
            msg = buildNumberedClarificationSpeech(
              data.parsed,
              data.transcription ?? "",
              false,
            );
          }
          setStatus(msg);
          const barged = await speakClarificationWithBargeIn(msg, uid);
          if (!barged) shouldAutoListen = true;
        }
      }
    } catch (err) {
      console.log("[voice] processVoiceBlob catch", {
        status: voiceResponseStatus,
        body: voiceResponseBody,
        error: err,
      });
      const errMsg = "Error processing audio. Please try again.";
      setStatus(errMsg);
      await speak(errMsg);
      if (wasAwaitingClarification) shouldAutoListen = true;
    } finally {
      flushSync(() => setLoadingBoth(false));
    }
    if (shouldAutoListen) await maybeAutoListen();
  }
  processVoiceBlobRef.current = processVoiceBlob;

  async function startRecording(options?: { fromAutoListen?: boolean }) {
    if (recordingRef.current || loadingRef.current) return;
    // Unlock audio context for Safari
    const AudioContext =
      window.AudioContext || (window as any).webkitAudioContext;
    if (AudioContext) {
      const ctx = new AudioContext();
      ctx.resume();
    }
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) {
      setAutoListening(false);
      return;
    }
    const uid = session.user.id;
    setAutoListening(!!options?.fromAutoListen);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        setAutoListening(false);
        setRecordingBoth(false);
        setStatus("Microphone access is required to listen.");
        return;
      }
    }
    const mimeType = MediaRecorder.isTypeSupported("audio/webm")
      ? "audio/webm"
      : "audio/mp4";
    const recorder = new MediaRecorder(stream, { mimeType });
    chunksRef.current = [];
    recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
    recorder.onstop = async () => {
      clearRecordingTimeout();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setRecordingBoth(false);
      setAutoListening(false);
      // User cancelled by tapping Speak-to-me again — no API, no TTS, no status.
      if (cancelRecordingRef.current) {
        cancelRecordingRef.current = false;
        recordingTimedOutRef.current = false;
        chunksRef.current = [];
        return;
      }
      const timedOut = recordingTimedOutRef.current;
      recordingTimedOutRef.current = false;
      const blob = new Blob(chunksRef.current, { type: mimeType });

      if (timedOut && blob.size < MIN_RECORDING_BYTES) {
        await handleRecordingSilenceTimeout();
        return;
      }

      await processVoiceBlob(blob, mimeType, uid);
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setRecordingBoth(true);
    setStatus("Recording...");
    recordingTimedOutRef.current = false;
    clearRecordingTimeout();
    recordingTimeoutIdRef.current = setTimeout(() => {
      recordingTimedOutRef.current = true;
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
    }, RECORDING_TIMEOUT_MS);
    streamRef.current = stream;
  }
  startRecordingRef.current = startRecording;

  function cancelListeningSilent() {
    cancelRecordingRef.current = true;
    awaitingMoreTimeReplyRef.current = false;
    clearRecordingTimeout();
    recordingTimedOutRef.current = false;
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    } else {
      cancelRecordingRef.current = false;
    }
    setRecordingBoth(false);
    setAutoListening(false);
    setStatus("");
  }

  async function saveGoal() {
    if (!goalInput) return;
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    const uid = session.user.id;
    await fetch(`${API_BASE}/user/${uid}/profile`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ calorie_goal: Number.parseFloat(goalInput) }),
    });
    setCalorieGoal(Number.parseFloat(goalInput));
    setGoalInput("");
    speak(`Calorie goal set to ${goalInput} calories`);
  }

  async function confirmLog(uid: string, raw_input: string) {
    const res = await fetch(`${API_BASE}/food`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: uid, raw_input }),
    });
    const data = await res.json();
    const msg = `Logged ${data.parsed.food}, ${Math.round(data.parsed.calories)} calories`;
    setStatus(msg);
    await speak(msg);
    setTextInput("");
    setPendingParse(null);
    pendingParseRef.current = null;
    endPostLoginVoiceSession();
    setConversationHistoryBoth([]);
    clearSpokenClarifyOptions();
    fetchLogs(uid);
    fetchSummary(uid);
  }

  async function logResolved(
    uid: string,
    pick: {
      food_name: string;
      calories: number;
      protein?: number;
      carbs?: number;
      fat?: number;
      quantity?: string;
      raw_input: string;
    },
  ) {
    setLoadingBoth(true);
    try {
      const res = await fetch(`${API_BASE}/food`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: uid,
          resolved: true,
          raw_input: pick.raw_input,
          food_name: pick.food_name,
          calories: pick.calories,
          protein: pick.protein,
          carbs: pick.carbs,
          fat: pick.fat,
          quantity: pick.quantity,
        }),
      });
      const data = await res.json();
      const msg = `Logged ${data.parsed.food}, ${Math.round(data.parsed.calories ?? 0)} calories`;
      setStatus(msg);
      await speak(msg);
      setTextInput("");
      setPendingParse(null);
      pendingParseRef.current = null;
      endPostLoginVoiceSession();
      setConversationHistoryBoth([]);
      clearSpokenClarifyOptions();
      await fetchLogs(uid);
      await fetchSummary(uid);
    } finally {
      flushSync(() => setLoadingBoth(false));
    }
  }

  // Re-run the parse for the ORIGINAL input, now restricted to a single source
  // (the user's brand-vs-general answer). Shared by text (button tap) and voice
  // (spoken "brand"/"general"), so both flows resolve identically. If the
  // filtered result is unambiguous it logs directly; otherwise it shows the
  // now single-source candidate/portion clarification.
  // Returns true if barge-in already handled the follow-up (skip maybeAutoListen).
  async function resolveWithSource(
    uid: string,
    originalInput: string,
    source: "generic" | "brand",
  ): Promise<boolean> {
    setLoadingBoth(true);
    try {
      const res = await fetch(`${API_BASE}/food/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_input: originalInput, source_filter: source }),
      });
      const parsed = (await res.json()) as ParsedResult & { error?: string };

      if (parsed.error) {
        const err = `I couldn't find a ${source === "brand" ? "branded" : "general"} match. Please try again.`;
        setStatus(err);
        await speak(err);
        return false;
      }

      if (parsed.confidence === "high") {
        await logResolved(uid, {
          food_name: formatBrandedName(parsed.food, parsed.brand),
          calories: parsed.calories,
          protein: parsed.macronutrients?.protein,
          carbs: parsed.macronutrients?.carbohydrates,
          fat: parsed.macronutrients?.fats,
          quantity: parsed.serving_size,
          raw_input: originalInput,
        });
        return false;
      }

      const pending = { parsed, raw_input: originalInput, uid };
      setPendingParse(pending);
      pendingParseRef.current = pending;
      setClarifyExpandedBoth(false);
      // Replace history so the open prompt is the filtered list — not the
      // earlier brand/general question (which made "1"/"2" re-trigger brand).
      setConversationHistoryBoth([
        { role: "user", content: originalInput },
        { role: "assistant", content: JSON.stringify(parsed) },
      ]);
      // Always remember the spoken numbered list when we offer voice picks,
      // including See-mode mic, so number replies resolve correctly.
      rememberSpokenClarifyOptions(
        clarifyOptions(parsed, originalInput, false),
      );
      const msg = buildNumberedClarificationSpeech(
        parsed,
        originalInput,
        false,
      );
      setStatus(msg);
      return await speakClarificationWithBargeIn(msg, uid);
    } finally {
      flushSync(() => setLoadingBoth(false));
    }
  }

  function dismissPending() {
    setPendingParse(null);
    pendingParseRef.current = null;
    setStatus("");
    setConversationHistoryBoth([]);
    clearSpokenClarifyOptions();
    setClarifyExpandedBoth(false);
  }

  // The clarification card, rendered in BOTH see and speak mode so the response
  // (candidates/portions or the brand question) stays on screen and manageable
  // rather than vanishing with an ephemeral status line. Returns null when
  // there's nothing pending. One definition = no drift between the two modes.
  function renderClarificationCard() {
    if (!pendingParse) return null;
    const parsed = pendingParse.parsed;
    const brandChoice = isBrandChoice(parsed);
    return (
      <section
        ref={confidenceSectionRef}
        tabIndex={-1}
        aria-labelledby="confidence-heading"
        aria-live="polite"
        className={`w-full text-left border rounded-xl p-4 sm:p-6 outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 ${parsed.confidence === "low" ? "bg-red-900/30 border-red-400/40" : "bg-yellow-900/30 border-yellow-400/40"}`}
      >
        <div className="flex items-start justify-between gap-3 mb-1">
          {!brandChoice ? (
            <h2
              id="confidence-heading"
              className="text-lg font-semibold text-white"
            >
              {parsed.confidence === "low" ? "Unsure" : "Less Sure"}
            </h2>
          ) : (
            <h2 id="confidence-heading" className="sr-only">
              Brand or general item
            </h2>
          )}
          <button
            type="button"
            onClick={dismissPending}
            className={`flex flex-col items-center shrink-0 text-white/80 hover:text-white focus:outline-none focus:ring-2 focus:ring-white rounded px-1.5 py-0.5 -mt-1 -mr-1 ${brandChoice ? "ml-auto" : ""}`}
            aria-label="Dismiss this suggestion"
          >
            <span aria-hidden="true" className="text-lg leading-none">
              ×
            </span>
            <span className="text-[10px] leading-tight">Tap to dismiss</span>
          </button>
        </div>
        {!brandChoice && (
          <>
            <p className="text-white text-sm mb-1">
              <strong>
                {formatBrandedName(parsed.food, parsed.brand)}
              </strong>
              {parsed.serving_label ? ` — ${parsed.serving_label}` : ""}{" "}
              — {Math.round(parsed.calories)} cal
            </p>
            {parsed.serving_note && (
              <p className="text-amber-200 text-xs mb-2">{parsed.serving_note}</p>
            )}
            {parsed.reasoning && (
              <p className="text-white text-sm mb-3">{parsed.reasoning}</p>
            )}
          </>
        )}
        {(() => {
          // Brand-vs-general comes first, before any mixed candidate list.
          if (brandChoice) {
            return (
              <div className="mb-4">
                <p className="text-sm text-white font-medium mb-3">
                  Are you looking for a specific brand, or a general item?
                </p>
                <div className="flex flex-col gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      resolveWithSource(
                        pendingParse.uid,
                        pendingParse.raw_input,
                        "generic",
                      )
                    }
                    className="flex items-center gap-3 text-left px-3 py-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                    aria-label="1, A general item"
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white/15 text-sm font-bold tabular-nums"
                    >
                      1
                    </span>
                    <span className="font-medium">A general item</span>
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      resolveWithSource(
                        pendingParse.uid,
                        pendingParse.raw_input,
                        "brand",
                      )
                    }
                    className="flex items-center gap-3 text-left px-3 py-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                    aria-label="2, A specific brand"
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white/15 text-sm font-bold tabular-nums"
                    >
                      2
                    </span>
                    <span className="font-medium">A specific brand</span>
                  </button>
                </div>
              </div>
            );
          }

          const allOptions = allClarifyOptions(
            parsed,
            pendingParse.raw_input,
          );
          const options = clarifyOptions(
            parsed,
            pendingParse.raw_input,
            clarifyExpanded,
          );
          const hasGrounded = allOptions.length > 0;
          const hasMore = allOptions.length > options.length;
          const visibleCandidates = options.filter((o) => o.kind === "candidate");
          const visiblePortions = options.filter((o) => o.kind === "portion");

          if (hasGrounded) {
            return (
              <div className="mb-4 flex flex-col gap-4">
                {visibleCandidates.length > 0 && (
                  <div>
                    <p className="text-xs text-white uppercase tracking-wide font-medium mb-2">
                      Did you mean a different food?
                    </p>
                    <div className="flex flex-col gap-2">
                      {visibleCandidates.map((o, i) => {
                        const n = i + 1;
                        return (
                          <button
                            key={o.key}
                            type="button"
                            onClick={() =>
                              logResolved(pendingParse.uid, o.pick)
                            }
                            className="flex items-center gap-3 text-left px-3 py-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                            aria-label={`${n}, Log ${o.title}, ${Math.round(o.calories)} calories`}
                          >
                            <span
                              aria-hidden="true"
                              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white/15 text-sm font-bold tabular-nums"
                            >
                              {n}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block font-medium truncate">
                                {o.title}
                              </span>
                              {o.subtitle && (
                                <span className="block text-xs text-white/70">
                                  {o.subtitle}
                                </span>
                              )}
                            </span>
                            <span className="shrink-0 text-xs font-semibold">
                              {Math.round(o.calories)} cal
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {visiblePortions.length > 0 && (
                  <div>
                    <p className="text-xs text-white uppercase tracking-wide font-medium mb-2">
                      How much? — {parsed.food}
                    </p>
                    <div className="flex flex-col gap-2">
                      {visiblePortions.map((o, i) => {
                        // Continue numbering after candidates so on-screen
                        // matches the flat spoken list (candidates then portions).
                        const n = visibleCandidates.length + i + 1;
                        return (
                          <button
                            key={o.key}
                            type="button"
                            onClick={() =>
                              logResolved(pendingParse.uid, o.pick)
                            }
                            className="flex items-center gap-3 text-left px-3 py-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                            aria-label={`${n}, Log ${o.title}, ${Math.round(o.calories)} calories`}
                          >
                            <span
                              aria-hidden="true"
                              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white/15 text-sm font-bold tabular-nums"
                            >
                              {n}
                            </span>
                            <span className="min-w-0 flex-1 truncate">
                              {o.title}
                            </span>
                            <span className="shrink-0 text-xs font-semibold">
                              {Math.round(o.calories)} cal
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {(hasMore || clarifyExpanded) && (
                  <button
                    type="button"
                    onClick={() => {
                      const next = !clarifyExpanded;
                      setClarifyExpandedBoth(next);
                      // Keep the voice "most recently spoken" list in sync with
                      // the card when the user expands/collapses visually, so a
                      // later spoken number still resolves against what's shown.
                      if (pendingParse) {
                        rememberSpokenClarifyOptions(
                          clarifyOptions(
                            pendingParse.parsed,
                            pendingParse.raw_input,
                            next,
                          ),
                        );
                      }
                    }}
                    className="self-start text-xs font-medium text-white underline underline-offset-2 hover:text-white/80 focus:outline-none focus:ring-2 focus:ring-white rounded px-1 py-0.5"
                    aria-expanded={clarifyExpanded}
                  >
                    {clarifyExpanded ? "See fewer" : "See more"}
                  </button>
                )}

                <p className="text-xs text-white">
                  If none of these match, type or say what&apos;s needed and
                  press{" "}
                  <span className="font-medium text-white">Log Food</span> or{" "}
                  <span className="font-medium text-white">Speak to me</span>.
                </p>
              </div>
            );
          }

          if (parsed.alternatives && parsed.alternatives.length > 0) {
            return (
              <div className="mb-4">
                <p className="text-xs text-white uppercase tracking-wide font-medium mb-2">
                  Did you mean?
                </p>
                <div className="flex flex-col gap-2">
                  {parsed.alternatives.map((alt, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => {
                        setPendingParse({ ...pendingParse, raw_input: alt });
                        confirmLog(pendingParse.uid, alt);
                      }}
                      className="flex items-center gap-3 text-left px-3 py-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                      aria-label={`${i + 1}, Log ${alt} instead`}
                    >
                      <span
                        aria-hidden="true"
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white/15 text-sm font-bold tabular-nums"
                      >
                        {i + 1}
                      </span>
                      <span className="min-w-0 flex-1">{alt}</span>
                    </button>
                  ))}
                </div>
                <p className="text-xs text-white mt-3">
                  If none of these match, type or say what&apos;s needed and
                  press{" "}
                  <span className="font-medium text-white">Log Food</span> or{" "}
                  <span className="font-medium text-white">Speak to me</span>.
                </p>
              </div>
            );
          }

          return null;
        })()}
        {!brandChoice && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() =>
                confirmLog(pendingParse.uid, pendingParse.raw_input)
              }
              className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
              aria-label={`Confirm and log ${parsed.food}`}
            >
              Yes, log it
            </button>
            <button
              type="button"
              onClick={() => {
                dismissPending();
                textInputRef.current?.focus();
              }}
              className="px-4 py-2 bg-white/10 hover:bg-white/20 border border-white/20 text-white text-sm font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
              aria-label="Cancel and re-enter food"
            >
              Let me re-enter
            </button>
          </div>
        )}
      </section>
    );
  }

  async function clearDemoData() {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    if (!confirm("Clear all demo data?")) return;
    const uid = session.user.id;
    await fetch(`${API_BASE}/food/${uid}/all`, { method: "DELETE" });
    await fetchLogs(uid);
    await fetchSummary(uid);
  }

  if (!mounted) return null;

  return (
    <div className="min-h-screen bg-blue-700">
      <Head>
        <title>S2M — Log Your Food</title>
      </Head>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-white focus:text-blue-700 focus:rounded focus:font-semibold"
      >
        Skip to main content
      </a>

      <div className="max-w-5xl mx-auto px-4 py-6 sm:px-6 lg:px-8 pb-24 sm:pb-8">
        <header className="flex items-center justify-between gap-3 mb-8">
          <div className="bg-black/25 border border-white/20 rounded-lg px-2 py-1.5 flex items-center gap-1.5">
            <span className="text-white font-semibold text-sm tracking-wide">
              S2M
            </span>
            <svg
              width="22"
              height="16"
              viewBox="0 0 22 16"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M7 2 Q10 8 7 14"
                stroke="rgba(255,255,255,0.55)"
                strokeWidth="1.4"
                fill="none"
                strokeLinecap="round"
              />
              <path
                d="M11 0 Q15 8 11 16"
                stroke="rgba(255,255,255,0.35)"
                strokeWidth="1.4"
                fill="none"
                strokeLinecap="round"
              />
              <path
                d="M15 0 Q20 8 15 16"
                stroke="rgba(255,255,255,0.18)"
                strokeWidth="1.4"
                fill="none"
                strokeLinecap="round"
              />
            </svg>
          </div>

          <div className="flex bg-black/25 rounded-full p-0.5">
            <button
              type="button"
              onClick={() => setModeAndPersist("see")}
              aria-pressed={mode === "see" ? "true" : "false"}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${mode === "see" ? "bg-white text-blue-700" : "text-white/80 hover:text-white"}`}
            >
              See
            </button>
            <button
              type="button"
              onClick={() => setModeAndPersist("speak")}
              aria-pressed={mode === "speak" ? "true" : "false"}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${mode === "speak" ? "bg-white text-blue-700" : "text-white/80 hover:text-white"}`}
            >
              Speak
            </button>
          </div>

          <button
            type="button"
            onClick={() => setMuted(!muted)}
            className="p-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
            aria-label={muted ? "Unmute audio" : "Mute audio"}
            aria-pressed={muted ? "true" : "false"}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              aria-hidden="true"
            >
              {muted ? (
                <>
                  <path
                    d="M3 6H1v4h2l4 3V3L3 6z"
                    fill="rgba(255,255,255,0.4)"
                  />
                  <line
                    x1="10"
                    y1="6"
                    x2="14"
                    y2="10"
                    stroke="rgba(255,255,255,0.4)"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                  <line
                    x1="14"
                    y1="6"
                    x2="10"
                    y2="10"
                    stroke="rgba(255,255,255,0.4)"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </>
              ) : (
                <>
                  <path
                    d="M3 6H1v4h2l4 3V3L3 6z"
                    fill="rgba(255,255,255,0.8)"
                  />
                  <path
                    d="M11 5.5 Q13 8 11 10.5"
                    stroke="rgba(255,255,255,0.8)"
                    strokeWidth="1.4"
                    fill="none"
                    strokeLinecap="round"
                  />
                  <path
                    d="M13 3.5 Q16 8 13 12.5"
                    stroke="rgba(255,255,255,0.5)"
                    strokeWidth="1.4"
                    fill="none"
                    strokeLinecap="round"
                  />
                </>
              )}
            </svg>
          </button>

          <div ref={menuRef} className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setMenuOpen((open) => !open);
                }
              }}
              className="p-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              aria-controls="header-menu"
              aria-haspopup="true"
            >
              <svg
                width="16"
                height="12"
                viewBox="0 0 16 12"
                fill="none"
                aria-hidden="true"
              >
                <rect
                  y="0"
                  width="16"
                  height="1.5"
                  rx="0.75"
                  fill="rgba(255,255,255,0.8)"
                />
                <rect
                  y="5"
                  width="16"
                  height="1.5"
                  rx="0.75"
                  fill="rgba(255,255,255,0.8)"
                />
                <rect
                  y="10"
                  width="16"
                  height="1.5"
                  rx="0.75"
                  fill="rgba(255,255,255,0.8)"
                />
              </svg>
            </button>

            {menuOpen && (
              <div
                id="header-menu"
                role="menu"
                aria-label="Settings and account"
                className="absolute right-0 top-full z-50 mt-1 w-[min(100vw-2rem,280px)] rounded-lg border border-white/20 bg-blue-900/95 py-2 shadow-lg backdrop-blur-sm"
              >
                <p className="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-wide text-white/50">
                  Voice
                </p>
                {mode === "see" && (
                  <p className="px-3 pb-2 text-[11px] leading-snug text-white/55">
                    Voice on open runs in Speak mode. See default turns off
                    greet, summary on open, and auto-listen.
                  </p>
                )}
                <div className="border-b border-white/15 px-3 pb-2">
                  <label
                    htmlFor="menu-voice-select"
                    className="mb-1.5 block text-xs font-medium text-white/90"
                  >
                    Voice
                  </label>
                  {mounted && (
                    <select
                      id="menu-voice-select"
                      value={selectedVoice}
                      onChange={(e) => setSelectedVoice(e.target.value)}
                      className="w-full rounded-lg border border-white/30 bg-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-white"
                    >
                      {VOICES.map((v) => (
                        <option key={v} value={v} className="text-black">
                          {v}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <MenuSwitch
                  id="menu-summary-on-open"
                  label="Speak daily summary on open"
                  checked={summaryOnOpen}
                  onChange={(enabled) => {
                    setSummaryOnOpen(enabled);
                    persistBoolean(STORAGE_KEYS.summaryOnOpen, enabled);
                  }}
                />
                <MenuSwitch
                  id="menu-auto-listen"
                  label="Auto-listen after speaking, including after login welcome prompt"
                  checked={autoListen}
                  onChange={(enabled) => {
                    setAutoListen(enabled);
                    persistBoolean(STORAGE_KEYS.autoListen, enabled);
                  }}
                />
                <MenuSwitch
                  id="menu-greet-on-open"
                  label="Greet me on open"
                  checked={greetOnOpen}
                  onChange={(enabled) => {
                    setGreetOnOpen(enabled);
                    persistBoolean(STORAGE_KEYS.greetOnOpen, enabled);
                  }}
                />

                <div className="border-b border-white/15 px-3 py-2">
                  <label
                    htmlFor="menu-default-mode"
                    className="mb-1.5 block text-xs font-medium text-white/90"
                  >
                    See/Speak default mode
                  </label>
                  <select
                    id="menu-default-mode"
                    value={mode}
                    onChange={(e) =>
                      setModeAndPersist(e.target.value as AppMode)
                    }
                    className="w-full rounded-lg border border-white/30 bg-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-white"
                  >
                    <option value="see" className="text-black">
                      See
                    </option>
                    <option value="speak" className="text-black">
                      Speak
                    </option>
                  </select>
                </div>

                <div className="border-b border-white/15">
                  <button
                    type="button"
                    aria-expanded={howItWorksOpen}
                    aria-controls="how-it-works-panel"
                    onClick={() => setHowItWorksOpen((open) => !open)}
                    className="w-full px-3 py-2.5 text-left text-xs font-medium text-white/90 hover:bg-white/5 focus:outline-none focus:bg-white/10"
                  >
                    How it works
                  </button>
                  {howItWorksOpen && (
                    <p
                      id="how-it-works-panel"
                      className="border-t border-white/10 px-3 py-2.5 text-xs leading-relaxed text-white/80"
                    >
                      {HOW_IT_WORKS_TEXT}
                    </p>
                  )}
                </div>

                <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-white/50">
                  Account
                </p>
                <button
                  type="button"
                  role="menuitem"
                  onClick={signOut}
                  className="w-full px-3 py-2.5 text-left text-sm font-semibold text-white hover:bg-white/10 focus:outline-none focus:bg-white/10"
                >
                  Log out
                </button>
              </div>
            )}
          </div>
        </header>

        <main id="main-content">
          <h1 className="sr-only">S2M — Log Your Food</h1>
          {mode === "speak" ? (
            <section
              aria-label="Log food by voice"
              className="flex flex-col items-center justify-center py-20 text-center"
            >
              <button
                type="button"
                onClick={handleSpeakButtonClick}
                disabled={loading && !speaking && !recording}
                aria-pressed={recording || speaking ? "true" : "false"}
                aria-label={
                  speaking
                    ? "Stop speaking"
                    : autoListening
                      ? "Listening ..."
                      : recording
                        ? "Stop recording"
                        : "Speak to log food"
                }
                className={`w-44 h-44 rounded-full font-semibold text-white text-sm flex flex-col items-center justify-center gap-3 focus:outline-none focus:ring-4 transition-colors ${
                  speaking
                    ? "bg-red-600 hover:bg-red-700 focus:ring-white"
                    : recording
                      ? autoListening
                        ? "animate-pulse bg-amber-500 ring-4 ring-amber-200/90 hover:bg-amber-600 focus:ring-amber-100"
                        : "bg-green-700 focus:ring-white"
                      : "bg-green-600 hover:bg-green-700 focus:ring-white"
                }`}
              >
                <svg
                  width="48"
                  height="42"
                  viewBox="0 0 64 56"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M10 10 Q10 3 16 3 Q26 3 29 14 Q32 25 29 38 Q26 49 16 49 Q10 49 10 42 L10 36 Q15 39 20 36 Q27 33 27 22 Q27 11 20 8 Q15 6 13 10 Z"
                    stroke="white"
                    strokeWidth="2"
                    fill="none"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M13 25 Q11 29 13 33"
                    stroke="white"
                    strokeWidth="1.8"
                    fill="none"
                    strokeLinecap="round"
                  />
                  <path
                    d="M36 12 Q44 28 36 44"
                    stroke="white"
                    strokeWidth="2"
                    fill="none"
                    strokeLinecap="round"
                    opacity="0.85"
                  />
                  <path
                    d="M43 7 Q54 28 43 49"
                    stroke="white"
                    strokeWidth="2"
                    fill="none"
                    strokeLinecap="round"
                    opacity="0.55"
                  />
                  <path
                    d="M50 3 Q64 28 50 53"
                    stroke="white"
                    strokeWidth="2"
                    fill="none"
                    strokeLinecap="round"
                    opacity="0.28"
                  />
                </svg>
                <span>
                  {speaking
                    ? "Stop"
                    : autoListening
                      ? "Listening ..."
                      : recording
                        ? "Listening..."
                        : "Speak to me"}
                </span>
              </button>

              {showVoiceSetupRecovery && (
                <div className="mt-5 flex justify-center">
                  <VoiceSetupRecoveryPanel
                    onContinue={continueWithVoice}
                    onDismiss={handleDismissVoiceSetupRecovery}
                    continuing={continuingVoiceSetup}
                  />
                </div>
              )}

              {autoListening && (
                <p
                  role="status"
                  aria-live="polite"
                  className="mt-3 flex items-center justify-center gap-2 text-xs font-medium text-amber-200"
                >
                  <span className="inline-flex h-2 w-2 animate-pulse rounded-full bg-amber-300" />
                  Mic open — speak now
                </p>
              )}

              <p className="text-white/80 text-xs mt-4 max-w-xs text-center">
                If I'm not sure what you said, I'll ask you to clarify — just
                click "Speak to me" again and then speak the missing detail.
              </p>

              <div className="mt-8 max-w-xs">
                <p className="text-white/70 text-xs mb-3">Try saying:</p>
                <div className="flex flex-wrap justify-center gap-2">
                  {[
                    "I had two eggs",
                    "How many calories today?",
                    "What did I eat?",
                    "Delete my last entry",
                    "How's my progress?",
                  ].map((prompt) => (
                    <span
                      key={prompt}
                      className="bg-white/10 border border-white/15 text-white/80 px-3 py-1.5 rounded-full text-xs"
                    >
                      &ldquo;{prompt}&rdquo;
                    </span>
                  ))}
                </div>
              </div>

              {status && (
                <div
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                  className="mt-6 max-w-sm"
                >
                  <p className="px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white text-sm">
                    {status}
                  </p>
                </div>
              )}
              {/* Same persistent clarification card as text mode */}
              {pendingParse && (
                <div className="mt-6 w-full max-w-md">
                  {renderClarificationCard()}
                </div>
              )}
            </section>
          ) : (
            <div className="flex flex-col gap-3">
              {/* Today's Summary Card */}
              <section
                aria-labelledby="summary-heading"
                className="bg-white/15 border border-white/20 rounded-xl p-4 sm:p-6"
              >
                <h2
                  id="summary-heading"
                  className="text-lg font-semibold text-white mb-3"
                >
                  Today&apos;s Summary
                </h2>

                <div className="flex gap-3 mb-3">
                  <div className="rounded-lg bg-blue-950 border border-blue-800/80 p-3 text-center min-w-[100px]">
                    <p className="text-xs text-blue-50 uppercase tracking-wide font-medium">
                      Calories
                    </p>
                    <p
                      className="text-2xl font-bold text-white"
                      aria-label={`${summary.calories} of ${calorieGoal} calories`}
                    >
                      {Math.round(summary.calories)}
                      <span className="text-sm font-normal text-blue-100">
                        /{calorieGoal}
                      </span>
                    </p>
                  </div>

                  <div className="flex flex-col gap-2 flex-1">
                    <div className="flex gap-3">
                      {(["protein", "carbs", "fat"] as const).map((key) => {
                        const pressed = showNutrients[key];
                        return (
                          <label
                            key={key}
                            className="flex flex-col items-center gap-1 cursor-pointer"
                          >
                            <span className="text-xs text-white">
                              {key.charAt(0).toUpperCase() + key.slice(1)}
                            </span>
                            <button
                              type="button"
                              role="switch"
                              aria-checked={pressed ? "true" : "false"}
                              aria-label={`Toggle ${key} in summary`}
                              onClick={() =>
                                setShowNutrients((prev) => ({
                                  ...prev,
                                  [key]: !prev[key],
                                }))
                              }
                              className={`relative w-10 h-5 rounded-full border transition-colors focus:outline-none focus:ring-2 focus:ring-white ${pressed ? "bg-green-500 border-green-400" : "bg-white/10 border-white/20"}`}
                            >
                              <span
                                aria-hidden="true"
                                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform duration-200 ${pressed ? "translate-x-5" : "translate-x-0"}`}
                              />
                            </button>
                          </label>
                        );
                      })}
                    </div>

                    {Object.values(showNutrients).some(Boolean) && (
                      <div className="flex gap-2">
                        {showNutrients.protein && (
                          <div className="rounded-lg bg-blue-950 border border-blue-800/70 p-2 text-center flex-1">
                            <p className="text-xs text-blue-50 uppercase tracking-wide font-medium">
                              Protein
                            </p>
                            <p className="text-base font-bold text-white">
                              {Number(summary.protein).toFixed(1)}
                              <span className="text-xs font-normal text-blue-100">
                                g
                              </span>
                            </p>
                          </div>
                        )}
                        {showNutrients.carbs && (
                          <div className="rounded-lg bg-blue-950 border border-blue-800/70 p-2 text-center flex-1">
                            <p className="text-xs text-blue-50 uppercase tracking-wide font-medium">
                              Carbs
                            </p>
                            <p className="text-base font-bold text-white">
                              {Number(summary.carbs).toFixed(1)}
                              <span className="text-xs font-normal text-blue-100">
                                g
                              </span>
                            </p>
                          </div>
                        )}
                        {showNutrients.fat && (
                          <div className="rounded-lg bg-blue-950 border border-blue-800/70 p-2 text-center flex-1">
                            <p className="text-xs text-blue-50 uppercase tracking-wide font-medium">
                              Fat
                            </p>
                            <p className="text-base font-bold text-white">
                              {Number(summary.fat).toFixed(1)}
                              <span className="text-xs font-normal text-blue-100">
                                g
                              </span>
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Progress bar */}
                <div className="mb-4">
                  <label htmlFor="calorie-progress" className="sr-only">
                    Calorie progress: {caloriePercent}% of daily goal
                  </label>
                  <progress
                    id="calorie-progress"
                    value={Math.round(summary.calories)}
                    max={calorieGoal}
                    className="w-full h-3 rounded-full overflow-hidden appearance-none [&::-webkit-progress-bar]:bg-white/20 [&::-webkit-progress-bar]:rounded-full [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:transition-all [&::-webkit-progress-value]:duration-500"
                    style={{
                      accentColor:
                        caloriePercent >= 100
                          ? "#f87171"
                          : caloriePercent >= 75
                            ? "#facc15"
                            : "#4ade80",
                    }}
                  />
                  <div className="flex items-center justify-between mt-1">
                    <p className="text-xs text-white">
                      {caloriePercent}% of daily goal
                    </p>
                    <p className="text-xs text-white">
                      {summary.entry_count}{" "}
                      {summary.entry_count === 1 ? "entry" : "entries"}
                    </p>
                  </div>
                </div>

                {showVoiceSetupRecovery && (
                  <div className="mb-4">
                    <VoiceSetupRecoveryPanel
                      onContinue={continueWithVoice}
                      onDismiss={handleDismissVoiceSetupRecovery}
                      continuing={continuingVoiceSetup}
                    />
                  </div>
                )}

                {/* Hear Today's Summary button */}
                <button
                  type="button"
                  onClick={() => speakTodaysSummary(summary, calorieGoal)}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 border border-white/20 rounded-lg text-white text-sm font-medium focus:outline-none focus:ring-2 focus:ring-white transition-colors mb-4"
                  aria-label="Hear today's nutrition summary"
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 16 16"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M3 6H1v4h2l4 3V3L3 6z"
                      fill="rgba(255,255,255,0.8)"
                    />
                    <path
                      d="M11 5.5 Q13 8 11 10.5"
                      stroke="rgba(255,255,255,0.8)"
                      strokeWidth="1.4"
                      fill="none"
                      strokeLinecap="round"
                    />
                    <path
                      d="M13 3.5 Q16 8 13 12.5"
                      stroke="rgba(255,255,255,0.5)"
                      strokeWidth="1.4"
                      fill="none"
                      strokeLinecap="round"
                    />
                  </svg>
                  Hear today&apos;s summary
                </button>

                {/* Settings — collapsible */}
                <details className="group">
                  <summary className="cursor-pointer text-xs text-white hover:text-white transition-colors list-none flex items-center gap-1 select-none">
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 12 12"
                      fill="none"
                      className="transition-transform group-open:rotate-90"
                      aria-hidden="true"
                    >
                      <path
                        d="M4 2l4 4-4 4"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    Settings
                  </summary>
                  <div className="mt-3 flex flex-col gap-4 border-t border-white/20 pt-4">
                    <fieldset>
                      <legend className="text-sm font-medium text-white mb-2">
                        Update calorie goal
                      </legend>
                      <div className="flex flex-wrap gap-2">
                        <label htmlFor="calorie-goal-input" className="sr-only">
                          New calorie goal
                        </label>
                        <input
                          id="calorie-goal-input"
                          type="number"
                          value={goalInput}
                          onChange={(e) => setGoalInput(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && saveGoal()}
                          placeholder={`Current: ${calorieGoal} cal`}
                          min={0}
                          className="flex-1 min-w-0 px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder-white text-sm focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
                        />
                        <button
                          type="button"
                          onClick={saveGoal}
                          className="px-4 py-2 bg-white text-blue-700 font-semibold rounded-lg text-sm hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors"
                          aria-label="Save new calorie goal"
                        >
                          Save goal
                        </button>
                      </div>
                    </fieldset>
                  </div>
                </details>
              </section>

              {/* Log Food section */}
              <section
                aria-labelledby="log-input-heading"
                className="bg-white/15 border border-white/20 rounded-xl p-4 sm:p-7"
              >
                <h2
                  id="log-input-heading"
                  className="text-lg font-semibold text-white mb-4"
                >
                  Log Food
                </h2>
                <div className="flex items-center gap-3 sm:items-end sm:gap-4">
                  <div className="flex-shrink-0 flex flex-col items-center gap-1.5">
                    <span className="text-[10px] sm:text-xs text-white">
                      Speak to me
                    </span>
                    <button
                      type="button"
                      onClick={handleSpeakButtonClick}
                      disabled={loading && !speaking && !recording}
                      aria-pressed={recording || speaking ? "true" : "false"}
                      aria-label={
                        speaking
                          ? "Stop speaking"
                          : recording
                            ? "Stop voice recording"
                            : "Start voice recording to log food"
                      }
                      className={`w-10 h-10 rounded-full flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-white transition-colors disabled:cursor-not-allowed ${
                        speaking
                          ? "bg-red-600 hover:bg-red-700"
                          : recording
                            ? "bg-amber-500 hover:bg-amber-600"
                            : "bg-green-600 hover:bg-green-700"
                      }`}
                    >
                      <svg
                        width="16"
                        height="14"
                        viewBox="0 0 64 56"
                        fill="none"
                        aria-hidden="true"
                      >
                        <path
                          d="M10 10 Q10 3 16 3 Q26 3 29 14 Q32 25 29 38 Q26 49 16 49 Q10 49 10 42 L10 36 Q15 39 20 36 Q27 33 27 22 Q27 11 20 8 Q15 6 13 10 Z"
                          stroke="white"
                          strokeWidth="2"
                          fill="none"
                          strokeLinejoin="round"
                        />
                        <path
                          d="M13 25 Q11 29 13 33"
                          stroke="white"
                          strokeWidth="1.8"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M36 12 Q44 28 36 44"
                          stroke="white"
                          strokeWidth="2"
                          fill="none"
                          strokeLinecap="round"
                          opacity="0.85"
                        />
                        <path
                          d="M43 7 Q54 28 43 49"
                          stroke="white"
                          strokeWidth="2"
                          fill="none"
                          strokeLinecap="round"
                          opacity="0.55"
                        />
                      </svg>
                    </button>
                  </div>

                  <div
                    className="w-px h-10 bg-white/20 flex-shrink-0"
                    aria-hidden="true"
                  />

                  <div className="flex flex-col gap-1.5 flex-1 min-w-0">
                    <label
                      htmlFor="food-text-input"
                      className="text-[10px] sm:text-xs text-white"
                    >
                      Type it instead
                    </label>
                    <div className="flex gap-1.5 sm:gap-2">
                      <input
                        id="food-text-input"
                        ref={textInputRef}
                        type="text"
                        value={textInput}
                        onChange={(e) => {
                          // Typing a text reply cuts any in-progress verbal response.
                          if (e.target.value) stopSpeaking();
                          setTextInput(e.target.value);
                        }}
                        onKeyDown={(e) => e.key === "Enter" && submitText()}
                        placeholder="e.g. two eggs and a coffee"
                        autoComplete="off"
                        className="flex-1 min-w-0 px-2 py-1.5 sm:px-3 sm:py-2.5 rounded-lg bg-white/60 border border-white/30 text-blue-900 placeholder-blue-900 text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
                      />
                      <button
                        type="button"
                        onClick={submitText}
                        disabled={loading}
                        className="px-2.5 py-1.5 sm:px-4 sm:py-2.5 bg-green-700 hover:bg-green-800 disabled:bg-green-800 disabled:cursor-not-allowed text-white font-semibold rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-white transition-colors flex-shrink-0"
                        aria-label={
                          loading ? "Logging food, please wait" : "Log food"
                        }
                        aria-busy={loading}
                      >
                        {loading ? "..." : "Log food"}
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              {/* Pending parse / clarification (same card also shown in speak mode) */}
              {renderClarificationCard()}

              {/* Status live region */}
              {status && (
                <div role="status" aria-live="polite" aria-atomic="true">
                  <p className="px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white text-sm">
                    {status}
                  </p>
                </div>
              )}

              {/* Today's logs — toggled */}
              <section aria-labelledby="logs-heading">
                <button
                  type="button"
                  onClick={() => setShowLogs((prev) => !prev)}
                  className="w-full flex items-center justify-between px-4 py-3 bg-white/10 hover:bg-white/20 border border-white/20 rounded-xl text-white text-sm font-medium focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                  aria-expanded={showLogs ? "true" : "false"}
                  aria-controls="logs-table"
                  id="logs-disclosure-button"
                >
                  <span id="logs-heading">
                    Today&apos;s logs ({summary.entry_count})
                  </span>
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 12 12"
                    fill="none"
                    className={`transition-transform ${showLogs ? "rotate-180" : ""}`}
                    aria-hidden="true"
                  >
                    <path
                      d="M2 4l4 4 4-4"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>

                {isGuest && (
                  <button
                    type="button"
                    onClick={clearDemoData}
                    className="w-full mt-2 py-2 bg-red-500/20 hover:bg-red-500/40 border border-red-400/30 text-red-200 text-xs font-medium rounded-xl transition-colors focus:outline-none focus:ring-2 focus:ring-white"
                    aria-label="Clear all demo data"
                  >
                    Clear demo data
                  </button>
                )}

                {showLogs && (
                  <div id="logs-table" className="mt-3">
                    {logs.length === 0 ? (
                      <div className="bg-white/10 border border-white/20 rounded-xl p-8 text-center">
                        <p className="text-white text-sm">
                          Nothing logged yet today.
                        </p>
                        <p className="text-blue-300/60 text-xs mt-1">
                          Type or speak what you ate to get started.
                        </p>
                      </div>
                    ) : (
                      <>
                        <p className="text-xs text-blue-300/60 mb-1 sm:hidden">
                          Scroll right to see more →
                        </p>
                        <div className="overflow-x-auto rounded-xl border border-white/20">
                          <table
                            className="w-full min-w-[500px] text-sm text-left"
                            aria-label="Today's food log entries"
                          >
                            <thead>
                              <tr className="border-b border-white/20 bg-white/10">
                                <th
                                  scope="col"
                                  className="px-3 py-2 text-[10px] font-semibold text-white uppercase tracking-wide"
                                >
                                  Food
                                </th>
                                <th
                                  scope="col"
                                  className="px-3 py-2 text-[10px] font-semibold text-white uppercase tracking-wide"
                                >
                                  Cal
                                </th>
                                <th
                                  scope="col"
                                  className="px-3 py-2 text-[10px] font-semibold text-white uppercase tracking-wide"
                                >
                                  Protein
                                </th>
                                <th
                                  scope="col"
                                  className="px-3 py-2 text-[10px] font-semibold text-white uppercase tracking-wide"
                                >
                                  Carbs
                                </th>
                                <th
                                  scope="col"
                                  className="px-3 py-2 text-[10px] font-semibold text-white uppercase tracking-wide"
                                >
                                  Fat
                                </th>
                                <th scope="col" className="px-3 py-2">
                                  <span className="sr-only">Actions</span>
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {logs.map((log, index) => (
                                <tr
                                  key={log._id}
                                  className={`border-b border-white/10 last:border-0 ${index % 2 === 0 ? "bg-white/5" : "bg-transparent"}`}
                                >
                                  {editingId === log._id ? (
                                    <>
                                      <td colSpan={5} className="px-3 py-2">
                                        <label
                                          htmlFor={`edit-input-${log._id}`}
                                          className="sr-only"
                                        >
                                          Edit food entry for {log.food_name}
                                        </label>
                                        <input
                                          id={`edit-input-${log._id}`}
                                          ref={editInputRef}
                                          value={editInput}
                                          onChange={(e) =>
                                            setEditInput(e.target.value)
                                          }
                                          onKeyDown={(e) => {
                                            if (e.key === "Enter")
                                              saveEdit(log._id);
                                            if (e.key === "Escape")
                                              setEditingId(null);
                                          }}
                                          placeholder="Describe what you ate"
                                          className="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder-white text-xs focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
                                        />
                                      </td>
                                      <td className="px-3 py-2">
                                        <div className="flex gap-2">
                                          <button
                                            type="button"
                                            onClick={() => saveEdit(log._id)}
                                            className="px-2 py-1 bg-green-600 hover:bg-green-700 text-white text-xs font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                                            aria-label={`Save edit for ${log.food_name}`}
                                          >
                                            Save
                                          </button>
                                          <button
                                            type="button"
                                            onClick={() => setEditingId(null)}
                                            className="px-2 py-1 bg-gray-600 hover:bg-gray-700 text-white text-xs font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                                            aria-label="Cancel edit"
                                          >
                                            Cancel
                                          </button>
                                        </div>
                                      </td>
                                    </>
                                  ) : (
                                    <>
                                      <td className="px-3 py-2 text-white text-xs font-medium">
                                        {log.food_name}
                                      </td>
                                      <td className="px-3 py-2 text-white text-xs">
                                        {log.calories}
                                      </td>
                                      <td className="px-3 py-2 text-white text-xs">
                                        {log.protein}g
                                      </td>
                                      <td className="px-3 py-2 text-white text-xs">
                                        {log.carbs}g
                                      </td>
                                      <td className="px-3 py-2 text-white text-xs">
                                        {log.fat}g
                                      </td>
                                      <td className="px-3 py-2">
                                        <div className="flex gap-2 justify-end">
                                          <button
                                            type="button"
                                            onClick={() => {
                                              setEditingId(log._id);
                                              setEditInput(log.raw_input);
                                            }}
                                            className="p-1.5 rounded-lg bg-blue-500/20 hover:bg-blue-500/40 text-white hover:text-white focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                                            aria-label={`Edit ${log.food_name}`}
                                          >
                                            <svg
                                              width="12"
                                              height="12"
                                              viewBox="0 0 14 14"
                                              fill="none"
                                              aria-hidden="true"
                                            >
                                              <path
                                                d="M9.5 1.5l3 3L4 13H1v-3L9.5 1.5z"
                                                stroke="currentColor"
                                                strokeWidth="1.4"
                                                fill="none"
                                                strokeLinejoin="round"
                                              />
                                            </svg>
                                          </button>
                                          <button
                                            type="button"
                                            onClick={() => deleteLog(log._id)}
                                            className="p-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/40 text-red-300 hover:text-white focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                                            aria-label={`Delete ${log.food_name}`}
                                          >
                                            <svg
                                              width="12"
                                              height="12"
                                              viewBox="0 0 14 14"
                                              fill="none"
                                              aria-hidden="true"
                                            >
                                              <path
                                                d="M2 3.5h10M5 3.5V2.5a.5.5 0 01.5-.5h3a.5.5 0 01.5.5v1M5.5 6v4M8.5 6v4M3 3.5l.7 7.5a.5.5 0 00.5.5h5.6a.5.5 0 00.5-.5L11 3.5"
                                                stroke="currentColor"
                                                strokeWidth="1.4"
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                              />
                                            </svg>
                                          </button>
                                        </div>
                                      </td>
                                    </>
                                  )}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </section>
            </div>
          )}
        </main>

        {/* Bottom nav — mobile only */}
        <nav
          aria-label="Main navigation"
          className="fixed bottom-0 left-0 right-0 bg-blue-800 border-t border-white/20 flex justify-around items-center py-2 sm:hidden"
        >
          <button
            type="button"
            aria-label="Home"
            className="flex flex-col items-center gap-1 p-2 text-white/80 hover:text-white transition-colors"
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M3 12L12 3L21 12V21H15V15H9V21H3V12Z"
                stroke="currentColor"
                strokeWidth="1.8"
                fill="none"
                strokeLinejoin="round"
              />
            </svg>
            <span className="text-xs">Home</span>
          </button>
          <button
            type="button"
            aria-label="Progress"
            className="flex flex-col items-center gap-1 p-2 text-white/80 hover:text-white transition-colors"
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
            >
              <polyline
                points="22 12 18 12 15 21 9 3 6 12 2 12"
                stroke="currentColor"
                strokeWidth="1.8"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <span className="text-xs">Progress</span>
          </button>
          <button
            type="button"
            aria-label="History"
            className="flex flex-col items-center gap-1 p-2 text-white/80 hover:text-white transition-colors"
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
            >
              <rect
                x="3"
                y="4"
                width="18"
                height="18"
                rx="2"
                stroke="currentColor"
                strokeWidth="1.8"
                fill="none"
              />
              <line
                x1="3"
                y1="9"
                x2="21"
                y2="9"
                stroke="currentColor"
                strokeWidth="1.8"
              />
              <line
                x1="8"
                y1="2"
                x2="8"
                y2="6"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
              <line
                x1="16"
                y1="2"
                x2="16"
                y2="6"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
            <span className="text-xs">History</span>
          </button>
          <button
            type="button"
            aria-label="Profile"
            className="flex flex-col items-center gap-1 p-2 text-white/80 hover:text-white transition-colors"
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
            >
              <circle
                cx="12"
                cy="8"
                r="4"
                stroke="currentColor"
                strokeWidth="1.8"
                fill="none"
              />
              <path
                d="M4 20C4 17 7.6 15 12 15C16.4 15 20 17 20 20"
                stroke="currentColor"
                strokeWidth="1.8"
                fill="none"
                strokeLinecap="round"
              />
            </svg>
            <span className="text-xs">Profile</span>
          </button>
        </nav>
      </div>
    </div>
  );
}
