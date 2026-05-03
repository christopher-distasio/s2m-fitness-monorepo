import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "../lib/supabaseClient";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

interface ParsedResult {
  food: string;
  calories: number;
  serving_size?: string;
  macronutrients?: {
    carbohydrates: number;
    protein: number;
    fats: number;
    sugar: number;
  };
  confidence?: "high" | "medium" | "low";
  reasoning?: string;
  alternatives?: string[];
  notes?: string;
}

export default function Home() {
  const [textInput, setTextInput] = useState("");
  const [logs, setLogs] = useState<FoodLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
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
  const [userId, setUserId] = useState<string | null>(null);
  const [pendingParse, setPendingParse] = useState<{
    parsed: ParsedResult;
    raw_input: string;
    uid: string;
  } | null>(null);
  const [selectedVoice, setSelectedVoice] = useState("alloy");
  const [mounted, setMounted] = useState(false);

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
    },
    [userId],
  );

  const fetchProfile = useCallback(async () => {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    const uid = session.user.id;
    const res = await fetch(`${API_BASE}/user/${uid}/profile`);
    const data = await res.json();
    setCalorieGoal(data.calorie_goal);
  }, []);

  const [mode, setMode] = useState<"see" | "speak">("see");
  const streamRef = useRef<MediaStream | null>(null);
  const [muted, setMuted] = useState(false);

  const [showNutrients, setShowNutrients] = useState({
    protein: false,
    carbs: false,
    fat: false,
  });

  const [conversationHistory, setConversationHistory] = useState<
    Array<{ role: "user" | "assistant"; content: string }>
  >([]);

  useEffect(() => {
    if (!userId) return;
    fetchLogs();
    fetchSummary();
    fetchProfile();
  }, [userId, fetchLogs, fetchSummary, fetchProfile]);

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

  useEffect(() => setMounted(true), []);

  async function speak(text: string) {
    if (muted) return;
    try {
      const res = await fetch(`${API_BASE}/food/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: selectedVoice }),
      });
      if (!res.ok) throw new Error("TTS failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play();
    } catch {
      console.log("using fallback")
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    }
  }

  async function submitText() {
    // console.log(conversationHistory)
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    if (!textInput.trim()) return;
    setLoading(true);
    setStatus("Parsing...");
    const uid = session.user.id;
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
        speak(err);
        return;
      }

      if (parsed.confidence === "high") {
        const resolvedInput = `${parsed.serving_size} ${parsed.food}`;
        await confirmLog(uid, resolvedInput);
      } else {
        // Add this exchange to conversation history
        setConversationHistory((prev) => [
          ...prev,
          { role: "user", content: textInput },
          { role: "assistant", content: JSON.stringify(parsed) },
        ]);
        setPendingParse({ parsed, raw_input: textInput, uid });
        const alternatives = parsed.alternatives?.join(", or ") ?? "";
        const msg =
          parsed.confidence === "low"
            ? `I wasn't sure about that. ${parsed.reasoning}. Please be more specific.`
            : `I think this is ${parsed.food}. Did you mean ${alternatives}?`;
        setStatus(msg);
        speak(msg);
        setTextInput("");
      }
    } catch {
      const err = "Error logging food.";
      setStatus(err);
      speak(err);
    } finally {
      setLoading(false);
    }
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

  async function startRecording() {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    const uid = session.user.id;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
    recorder.onstop = async () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      const formData = new FormData();
      formData.append("user_id", uid);
      formData.append("audio", blob, "recording.webm");
      setLoading(true);
      setStatus("Transcribing...");
      try {
        formData.append(
          "conversation_history",
          JSON.stringify(conversationHistory),
        );
        const res = await fetch(`${API_BASE}/food/voice`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();

        if (data.error) {
          const err =
            "I couldn't understand that. Please try saying something more specific.";
          setStatus(err);
          speak(err);
          return;
        }

        if (data.message && !data.parsed) {
          setStatus(data.message);
          speak(data.message);
          fetchLogs(uid);
          await fetchSummary(uid);
          return;
        }

        if (data.parsed.confidence === "high") {
          const msg = `Logged ${data.parsed.food}, ${data.parsed.calories} calories`;
          setStatus(
            `Heard: "${data.transcription}" — ${data.parsed.food}, ${data.parsed.calories} cal`,
          );
          speak(msg);
          await fetchLogs(uid);
          await fetchSummary(uid);
        } else {
          setPendingParse({
            parsed: data.parsed,
            raw_input: data.transcription,
            uid,
          });
          setConversationHistory((prev) => [
            ...prev,
            { role: "user", content: data.transcription },
            { role: "assistant", content: JSON.stringify(data.parsed) },
          ]);
          const alternatives = data.parsed.alternatives?.join(", or ") ?? "";
          const msg =
            data.parsed.confidence === "low"
              ? `I wasn't sure about that. ${data.parsed.reasoning}. Please be more specific.`
              : `I think this is ${data.parsed.food}. Did you mean ${alternatives}?`;
          setStatus(msg);
          speak(msg);
        }
      } catch {
        const err = "Error processing audio. Please try again.";
        setStatus(err);
        speak(err);
      } finally {
        setLoading(false);
      }
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setRecording(true);
    setStatus("Recording...");
    setTimeout(() => {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
        setRecording(false);
      }
    }, 8000);
    streamRef.current = stream;
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
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
    const msg = `Logged ${data.parsed.food}, ${data.parsed.calories} calories`;
    setStatus(msg);
    speak(msg);
    setTextInput("");
    setPendingParse(null);
    // Clear history — conversation is resolved
    setConversationHistory([]);
    fetchLogs(uid);
    fetchSummary(uid);
  }
  const caloriePercent = Math.min(
    100,
    Math.round((summary.calories / calorieGoal) * 100),
  );

  useEffect(() => {
    if (!userId) return;
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) router.push("/login");
    });
  }, [router, userId]);

  if (!mounted) return null;

  return (
    <div className="min-h-screen bg-blue-700">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-white focus:text-blue-700 focus:rounded focus:font-semibold"
      >
        Skip to main content
      </a>

      <div className="max-w-5xl mx-auto px-4 py-6 sm:px-6 lg:px-8 pb-16 sm:pb-0">
        {/* Header — S2M logo, See/Speak mode toggle, mute, sign out, hamburger */}{" "}
        <header className="flex items-center justify-between gap-3 mb-8">
          <div className="bg-black/25 border border-white/20 rounded-lg px-2 py-1.5 flex items-center gap-1.5">
            <span className="text-white font-semibold text-sm tracking-wide">
              S2M
            </span>
            <svg width="22" height="16" viewBox="0 0 22 16" fill="none">
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
              onClick={() => setMode("see")}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                mode === "see"
                  ? "bg-white text-blue-700"
                  : "text-white/60 hover:text-white"
              }`}
            >
              See
            </button>
            <button
              onClick={() => setMode("speak")}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                mode === "speak"
                  ? "bg-white text-blue-700"
                  : "text-white/60 hover:text-white"
              }`}
            >
              Speak
            </button>
          </div>
          {/* Mute — suppresses TTS output, does not affect recording */}
          <button
            onClick={() => setMuted(!muted)}
            className="p-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
            aria-label={muted ? "Unmute audio" : "Mute audio"}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
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
          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                if (!userId) return;
                await supabase.auth.signOut();
                router.push("/login");
              }}
              className="px-3 py-1.5 bg-white/10 hover:bg-white/20 text-white text-[10px] sm:text-xs font-semibold rounded-lg border border-white/20 focus:outline-none focus:ring-2 focus:ring-white transition-colors"
              aria-label="Sign out"
            >
              Sign out
            </button>
            <button
              className="p-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
              aria-label="Open menu"
            >
              <svg width="16" height="12" viewBox="0 0 16 12" fill="none">
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
          </div>
        </header>
        <main id="main-content">
          {/* See/Speak mode — controls full content area swap */}
          {mode === "speak" ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <button
                onClick={recording ? stopRecording : startRecording}
                disabled={loading}
                aria-label={recording ? "Stop recording" : "Speak to log food"}
                className={`w-44 h-44 rounded-full font-semibold text-white text-sm flex flex-col items-center justify-center gap-3 focus:outline-none focus:ring-4 focus:ring-white transition-colors ${
                  recording ? "bg-green-700" : "bg-green-600 hover:bg-green-700"
                }`}
              >
                <svg width="48" height="42" viewBox="0 0 64 56" fill="none">
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
                <span>{recording ? "Listening..." : "Speak to me"}</span>
              </button>
              <div className="mt-8 max-w-xs">
                <p className="text-white/40 text-xs mb-3">Try saying:</p>
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
                      className="bg-white/10 border border-white/15 text-white/60 px-3 py-1.5 rounded-full text-xs"
                    >
                      &ldquo;{prompt}&rdquo;
                    </span>
                  ))}
                </div>
              </div>
              <p className="text-white/60 text-xs mt-4 max-w-xs text-center">
                ( If I'm not sure what you said, I'll ask you to clarify. Then
                just press the large "Speak to me" circle again to speak the
                missing details. )
              </p>

              {status && (
                <p className="mt-6 px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white text-sm max-w-sm">
                  {status}
                </p>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="flex flex-col gap-6">
                {/* Daily Summary Card — calories always visible, nutrients opt-in via toggles */}{" "}
                <section
                  aria-labelledby="summary-heading"
                  className="bg-white/10 backdrop-blur-sm border border-white/20 rounded-xl p-4 sm:p-6 mb-6"
                >
                  <h2
                    id="summary-heading"
                    className="text-lg font-semibold text-white mb-3"
                  >
                    Today&apos;s Summary
                  </h2>

                  <div className="flex gap-3 mb-3">
                    {/* Calories card — fixed width */}
                    <div className="bg-white/10 rounded-lg p-3 text-center min-w-[100px]">
                      <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                        Calories
                      </p>
                      <p
                        className="text-2xl font-bold text-white"
                        aria-label={`${summary.calories} of ${calorieGoal} calories`}
                      >
                        {summary.calories}
                        <span className="text-sm font-normal text-blue-200">
                          /{calorieGoal}
                        </span>
                      </p>
                    </div>

                    {/* Right side — toggles and selected nutrient cards */}
                    <div className="flex flex-col gap-2 flex-1">
                      {/* Toggle buttons — fixed equal size */}
                      <div className="flex gap-2">
                        {(["protein", "carbs", "fat"] as const).map((key) => {
                          const pressed = showNutrients[key];
                          return (
                            <button
                              key={key}
                              onClick={() =>
                                setShowNutrients((prev) => ({
                                  ...prev,
                                  [key]: !prev[key],
                                }))
                              }
                              className={`w-16 h-8 rounded-full text-xs font-medium border transition-colors focus:outline-none focus:ring-2 focus:ring-white flex-shrink-0 ${
                                pressed
                                  ? "bg-white/25 border-white/50 text-white"
                                  : "bg-white/10 border-white/20 text-white/60 hover:text-white"
                              }`}
                              aria-pressed={pressed}
                            >
                              {pressed ? "− " : "+ "}
                              {key.charAt(0).toUpperCase() + key.slice(1)}
                            </button>
                          );
                        })}
                      </div>

                      {/* Selected nutrient cards */}
                      {Object.values(showNutrients).some(Boolean) && (
                        <div className="flex gap-2">
                          {showNutrients.protein && (
                            <div className="bg-white/10 rounded-lg p-2 text-center flex-1">
                              <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                                Protein
                              </p>
                              <p className="text-base font-bold text-white">
                                {Number(summary.protein).toFixed(1)}
                                <span className="text-xs font-normal text-blue-200">
                                  g
                                </span>
                              </p>
                            </div>
                          )}
                          {showNutrients.carbs && (
                            <div className="bg-white/10 rounded-lg p-2 text-center flex-1">
                              <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                                Carbs
                              </p>
                              <p className="text-base font-bold text-white">
                                {Number(summary.carbs).toFixed(1)}
                                <span className="text-xs font-normal text-blue-200">
                                  g
                                </span>
                              </p>
                            </div>
                          )}
                          {showNutrients.fat && (
                            <div className="bg-white/10 rounded-lg p-2 text-center flex-1">
                              <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                                Fat
                              </p>
                              <p className="text-base font-bold text-white">
                                {Number(summary.fat).toFixed(1)}
                                <span className="text-xs font-normal text-blue-200">
                                  g
                                </span>
                              </p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                  {/* Calorie progress bar */}
                  <div className="mb-4">
                    <label htmlFor="calorie-progress" className="sr-only">
                      Calorie progress: {caloriePercent}% of daily goal
                    </label>
                    <progress
                      id="calorie-progress"
                      value={summary.calories}
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
                    <p className="text-xs text-blue-200 mt-1">
                      {caloriePercent}% of daily goal &middot;{" "}
                      {summary.entry_count}{" "}
                      {summary.entry_count === 1 ? "entry" : "entries"}
                    </p>
                  </div>

                  {/* Calorie goal setter */}
                  <fieldset className="border-t border-white/20 pt-4">
                    <legend className="text-sm font-medium text-blue-200 mb-2">
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
                        className="flex-1 min-w-0 px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder-blue-300 text-sm focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
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
                  {mounted && (
                    <fieldset className="border-t border-white/20 pt-4 mt-4">
                      <legend className="text-sm font-medium text-blue-200 mb-2">
                        Voice preference
                      </legend>
                      <select
                        value={selectedVoice}
                        onChange={(e) => setSelectedVoice(e.target.value)}
                        aria-label="Voice preference"
                        className="px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white text-sm focus:outline-none focus:ring-2 focus:ring-white"
                      >
                        {[
                          "alloy",
                          "echo",
                          "fable",
                          "onyx",
                          "nova",
                          "shimmer",
                        ].map((v) => (
                          <option key={v} value={v} className="text-black">
                            {v}
                          </option>
                        ))}
                      </select>
                    </fieldset>
                  )}
                </section>
                {/* Log by text */}
                <section
                  aria-labelledby="text-log-heading"
                  className="bg-white/10 backdrop-blur-sm border border-white/20 rounded-xl p-4 sm:p-6 mb-6"
                >
                  <h2
                    id="text-log-heading"
                    className="text-lg font-semibold text-white mb-3"
                  >
                    Log by text
                  </h2>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <label htmlFor="food-text-input" className="sr-only">
                      Describe what you ate
                    </label>
                    <input
                      id="food-text-input"
                      ref={textInputRef}
                      type="text"
                      value={textInput}
                      onChange={(e) => setTextInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && submitText()}
                      placeholder="Describe what you ate. e.g. two eggs and a coffee"
                      autoComplete="off"
                      className="flex-1 px-3 py-2.5 rounded-lg bg-white/10 border border-white/30 text-white placeholder-blue-300 text-base focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
                      aria-label="Describe what you ate"
                    />
                    <button
                      onClick={submitText}
                      disabled={loading}
                      className="px-5 py-2.5 bg-red-500 hover:bg-red-600 disabled:bg-red-400 disabled:cursor-not-allowed text-white font-semibold rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors"
                      aria-label={
                        loading ? "Logging food, please wait" : "Log food"
                      }
                    >
                      {loading ? "Logging..." : "Log food"}
                    </button>
                  </div>
                </section>
                {pendingParse && (
                  <section
                    aria-labelledby="confidence-heading"
                    aria-live="polite"
                    className={`border rounded-xl p-4 sm:p-6 mb-6 ${
                      pendingParse.parsed.confidence === "low"
                        ? "bg-red-900/30 border-red-400/40"
                        : "bg-yellow-900/30 border-yellow-400/40"
                    }`}
                  >
                    <h2
                      id="confidence-heading"
                      className="text-lg font-semibold text-white mb-1"
                    >
                      {pendingParse.parsed.confidence === "low"
                        ? "Unsure"
                        : "Less Sure"}
                    </h2>

                    <p className="text-white text-sm mb-1">
                      <strong>{pendingParse.parsed.food}</strong> —{" "}
                      {pendingParse.parsed.calories} cal
                    </p>

                    {pendingParse.parsed.reasoning && (
                      <p className="text-blue-200 text-sm mb-3">
                        {pendingParse.parsed.reasoning}
                      </p>
                    )}

                    {pendingParse.parsed.alternatives &&
                      pendingParse.parsed.alternatives.length > 0 && (
                        <div className="mb-4">
                          <p className="text-xs text-blue-200 uppercase tracking-wide font-medium mb-2">
                            Did you mean?
                          </p>
                          <div className="flex flex-col gap-2">
                            {pendingParse.parsed.alternatives.map((alt, i) => (
                              <button
                                key={i}
                                onClick={() => {
                                  const updated = {
                                    ...pendingParse,
                                    raw_input: alt,
                                  };
                                  setPendingParse(updated);
                                  confirmLog(pendingParse.uid, alt);
                                }}
                                className="text-left px-3 py-2 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                                aria-label={`Log ${alt} instead`}
                              >
                                {alt}
                              </button>
                            ))}
                          </div>
                          <p className="text-xs text-blue-200 mt-3">
                            If none of these options match, type or say what's
                            needed (e.g. "large bowl") in "Log by text" then
                            press{" "}
                            <span className="font-medium text-white">
                              Log Food
                            </span>{" "}
                            , or press{" "}
                            <span className="font-medium text-white">
                              Log by voice
                            </span>
                            .
                          </p>{" "}
                        </div>
                      )}

                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() =>
                          confirmLog(pendingParse.uid, pendingParse.raw_input)
                        }
                        className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                        aria-label={`Confirm and log ${pendingParse.parsed.food}`}
                      >
                        Yes, log it
                      </button>
                      <button
                        onClick={() => {
                          setPendingParse(null);
                          setStatus("");
                          setConversationHistory([]);
                          textInputRef.current?.focus();
                        }}
                        className="px-4 py-2 bg-white/10 hover:bg-white/20 border border-white/20 text-white text-sm font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                        aria-label="Cancel and re-enter food"
                      >
                        Let me re-enter
                      </button>
                    </div>
                  </section>
                )}
                {/* Log by voice */}
                <section
                  aria-labelledby="voice-log-heading"
                  className="bg-white/10 backdrop-blur-sm border border-white/20 rounded-xl p-4 sm:p-6 mb-6"
                >
                  <h2
                    id="voice-log-heading"
                    className="text-lg font-semibold text-white mb-3"
                  >
                    Log by voice
                  </h2>
                  <button
                    onClick={recording ? stopRecording : startRecording}
                    disabled={loading}
                    aria-label={
                      recording
                        ? "Stop voice recording"
                        : "Start voice recording to log food"
                    }
                    className={`flex items-center gap-2 px-5 py-3 rounded-lg font-semibold text-white text-sm focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors disabled:cursor-not-allowed ${
                      recording
                        ? "bg-red-600 hover:bg-red-700 disabled:bg-red-500"
                        : "bg-gray-700 hover:bg-gray-800 disabled:bg-gray-500"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`w-3 h-3 rounded-full ${recording ? "bg-white animate-pulse" : "bg-gray-400"}`}
                    />
                    {recording ? "Stop recording" : "Start recording"}
                  </button>
                </section>
                {/* Status live region */}
                <div
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                  className="mb-6"
                >
                  {status && (
                    <p className="px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white text-sm">
                      {status}
                    </p>
                  )}
                </div>
              </div>
              {/* Right column — today's logs, visible alongside left column on desktop */}
              <div className="flex flex-col gap-6">
                {/* Food log table */}
                <section aria-labelledby="logs-heading">
                  <h2
                    id="logs-heading"
                    className="text-lg font-semibold text-white mb-3"
                  >
                    Today&apos;s logs
                  </h2>

                  {logs.length === 0 ? (
                    <p className="text-blue-200 text-sm">No logs yet today.</p>
                  ) : (
                    <div className="overflow-x-auto rounded-xl border border-white/20">
                      <table
                        className="w-full text-sm text-left"
                        aria-label="Today's food log entries"
                      >
                        <thead>
                          <tr className="border-b border-white/20 bg-white/10">
                            <th
                              scope="col"
                              className="px-4 py-3 text-xs font-semibold text-blue-200 uppercase tracking-wide"
                            >
                              Food
                            </th>
                            <th
                              scope="col"
                              className="px-4 py-3 text-xs font-semibold text-blue-200 uppercase tracking-wide"
                            >
                              Cal
                            </th>
                            <th
                              scope="col"
                              className="px-4 py-3 text-xs font-semibold text-blue-200 uppercase tracking-wide hidden sm:table-cell"
                            >
                              Protein
                            </th>
                            <th
                              scope="col"
                              className="px-4 py-3 text-xs font-semibold text-blue-200 uppercase tracking-wide hidden sm:table-cell"
                            >
                              Carbs
                            </th>
                            <th
                              scope="col"
                              className="px-4 py-3 text-xs font-semibold text-blue-200 uppercase tracking-wide hidden sm:table-cell"
                            >
                              Fat
                            </th>
                            <th
                              scope="col"
                              className="px-4 py-3 text-xs font-semibold text-blue-200 uppercase tracking-wide"
                            >
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
                                  <td colSpan={5} className="px-4 py-3">
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
                                      className="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder-blue-300 text-sm focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
                                    />
                                  </td>
                                  <td className="px-4 py-3">
                                    <div className="flex gap-2">
                                      <button
                                        onClick={() => saveEdit(log._id)}
                                        className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-xs font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors"
                                        aria-label={`Save edit for ${log.food_name}`}
                                      >
                                        Save
                                      </button>
                                      <button
                                        onClick={() => setEditingId(null)}
                                        className="px-3 py-1.5 bg-gray-600 hover:bg-gray-700 text-white text-xs font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors"
                                        aria-label="Cancel edit"
                                      >
                                        Cancel
                                      </button>
                                    </div>
                                  </td>
                                </>
                              ) : (
                                <>
                                  <td className="px-4 py-3 text-white font-medium">
                                    {log.food_name}
                                  </td>
                                  <td className="px-4 py-3 text-white">
                                    {log.calories}
                                  </td>
                                  <td className="px-4 py-3 text-white hidden sm:table-cell">
                                    {log.protein}g
                                  </td>
                                  <td className="px-4 py-3 text-white hidden sm:table-cell">
                                    {log.carbs}g
                                  </td>
                                  <td className="px-4 py-3 text-white hidden sm:table-cell">
                                    {log.fat}g
                                  </td>
                                  <td className="px-4 py-3">
                                    <div className="flex gap-2 justify-end">
                                      <button
                                        onClick={() => {
                                          setEditingId(log._id);
                                          setEditInput(log.raw_input);
                                        }}
                                        className="px-3 py-1.5 bg-blue-500 hover:bg-blue-600 text-white text-xs font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors"
                                        aria-label={`Edit ${log.food_name}`}
                                      >
                                        Edit
                                      </button>
                                      <button
                                        onClick={() => deleteLog(log._id)}
                                        className="px-3 py-1.5 bg-red-500 hover:bg-red-600 text-white text-xs font-semibold rounded-lg focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors"
                                        aria-label={`Delete ${log.food_name}`}
                                      >
                                        Delete
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
                  )}
                </section>
              </div>
            </div>
          )}
        </main>
        {/* Bottom nav — mobile only, hidden sm: and above, labels always visible for accessibility */}
        <nav
          aria-label="Main navigation"
          className="fixed bottom-0 left-0 right-0 bg-blue-800 border-t border-white/20 flex justify-around items-center py-2 sm:hidden"
        >
          <button
            aria-label="Home"
            className="flex flex-col items-center gap-1 p-2 text-white/60 hover:text-white transition-colors"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
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
            aria-label="Progress"
            className="flex flex-col items-center gap-1 p-2 text-white/60 hover:text-white transition-colors"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
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
            aria-label="History"
            className="flex flex-col items-center gap-1 p-2 text-white/60 hover:text-white transition-colors"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
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
            aria-label="Profile"
            className="flex flex-col items-center gap-1 p-2 text-white/60 hover:text-white transition-colors"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
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
