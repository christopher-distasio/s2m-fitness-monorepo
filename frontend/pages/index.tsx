import React, { useState, useRef, useEffect } from "react";
import { supabase } from "../lib/supabaseClient";
import { useRouter } from "next/router";

const API_BASE = "http://localhost:8000";

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
}

function speak(text: string) {
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.95;
  window.speechSynthesis.speak(utterance);
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
  const router = useRouter();

  useEffect(() => {
    if (!userId) return;
    fetchLogs();
    fetchSummary();
    fetchProfile();
  }, [userId]);

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
  }, []);

  useEffect(() => {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) router.push("/login");
      else setUserId(session.user.id);
    });
    return () => subscription.unsubscribe();
  }, []);

  async function fetchLogs(uid?: string) {
    const id = uid ?? userId;
    if (!id) return;
    const res = await fetch(`${API_BASE}/food/${id}/today`);
    const data = await res.json();
    setLogs(data.reverse());
  }

  async function submitText() {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    if (!textInput.trim()) return;
    setLoading(true);
    setStatus("Parsing...");
    const uid = session.user.id;
    try {
      const res = await fetch(`${API_BASE}/food`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: uid, raw_input: textInput }),
      });
      const data = await res.json();
      const msg = `Logged ${data.parsed.food}, ${data.parsed.calories} calories`;
      setStatus(msg);
      speak(msg);
      setTextInput("");
      fetchLogs(uid);
      fetchSummary(uid);
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
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      const formData = new FormData();
      formData.append("user_id", uid);
      formData.append("audio", blob, "recording.webm");
      setLoading(true);
      setStatus("Transcribing...");
      try {
        const res = await fetch(`${API_BASE}/food/voice`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (data.message && !data.parsed) {
          setStatus(data.message);
          speak(data.message);
          fetchLogs(uid);
          await fetchSummary(uid);
          return;
        }
        const msg = `Logged ${data.parsed.food}, ${data.parsed.calories} calories`;
        setStatus(
          `Heard: "${data.transcription}" — ${data.parsed.food}, ${data.parsed.calories} cal`,
        );
        speak(msg);
        await fetchLogs(uid);
        await fetchSummary(uid);
      } catch {
        const err = "Error processing audio.";
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
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  async function fetchSummary(uid?: string) {
    const id = uid ?? userId;
    if (!id) return;
    const res = await fetch(`${API_BASE}/food/${id}/summary`);
    const data = await res.json();
    setSummary(data);
    speak(
      `Today you have logged ${data.calories} calories. Protein ${data.protein} grams, carbs ${data.carbs} grams, fat ${data.fat} grams.`,
    );
  }
  async function fetchProfile() {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    const uid = session.user.id;
    const res = await fetch(`${API_BASE}/user/${uid}/profile`);
    const data = await res.json();
    setCalorieGoal(data.calorie_goal);
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

  const caloriePercent = Math.min(
    100,
    Math.round((summary.calories / calorieGoal) * 100),
  );

  useEffect(() => {
    if (!userId) return;
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) router.push("/login");
    });
  }, []);

  return (
    <div className="min-h-screen bg-blue-700">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-white focus:text-blue-700 focus:rounded focus:font-semibold"
      >
        Skip to main content
      </a>

      <div className="max-w-5xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-3 mb-8">
          <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
            Speak2Me Fitness
          </h1>
          <div className="flex gap-3 items-center">
            {
              <div className="flex gap-3 items-center">
                <button
                  onClick={async () => {
                    if (!userId) return;
                    await supabase.auth.signOut();
                    router.push("/login");
                  }}
                  className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white text-sm font-semibold rounded-lg border border-white/20 focus:outline-none focus:ring-2 focus:ring-white transition-colors"
                  aria-label="Sign out"
                >
                  Sign out
                </button>
              </div>
            }
          </div>
        </header>

        <main id="main-content">
          {/* Daily Summary Card */}
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

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              <div className="bg-white/10 rounded-lg p-3 text-center">
                <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                  Calories
                </p>
                <p
                  className="text-xl font-bold text-white"
                  aria-label={`${summary.calories} of ${calorieGoal} calories`}
                >
                  {summary.calories}
                  <span className="text-sm font-normal text-blue-200">
                    /{calorieGoal}
                  </span>
                </p>
              </div>
              <div className="bg-white/10 rounded-lg p-3 text-center">
                <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                  Protein
                </p>
                <p className="text-xl font-bold text-white">
                  {Number(summary.protein).toFixed(1)}
                  <span className="text-sm font-normal text-blue-200">g</span>
                </p>
              </div>
              <div className="bg-white/10 rounded-lg p-3 text-center">
                <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                  Carbs
                </p>
                <p className="text-xl font-bold text-white">
                  {Number(summary.carbs).toFixed(1)}
                  <span className="text-sm font-normal text-blue-200">g</span>
                </p>
              </div>
              <div className="bg-white/10 rounded-lg p-3 text-center">
                <p className="text-xs text-blue-200 uppercase tracking-wide font-medium">
                  Fat
                </p>
                <p className="text-xl font-bold text-white">
                  {Number(summary.fat).toFixed(1)}
                  <span className="text-sm font-normal text-blue-200">g</span>
                </p>
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
                {caloriePercent}% of daily goal &middot; {summary.entry_count}{" "}
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
                placeholder="e.g. two eggs and a coffee"
                autoComplete="off"
                className="flex-1 px-3 py-2.5 rounded-lg bg-white/10 border border-white/30 text-white placeholder-blue-300 text-base focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
                aria-label="Describe what you ate"
              />
              <button
                onClick={submitText}
                disabled={loading}
                className="px-5 py-2.5 bg-red-500 hover:bg-red-600 disabled:bg-red-400 disabled:cursor-not-allowed text-white font-semibold rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700 transition-colors"
                aria-label={loading ? "Logging food, please wait" : "Log food"}
              >
                {loading ? "Logging..." : "Log food"}
              </button>
            </div>
          </section>

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
              aria-pressed={recording ? "true" : "false"}
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
                                onChange={(e) => setEditInput(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") saveEdit(log._id);
                                  if (e.key === "Escape") setEditingId(null);
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
        </main>
      </div>
    </div>
  );
}
