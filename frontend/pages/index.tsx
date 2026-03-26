import React, { useState, useRef, useEffect } from "react";

const API_BASE = "http://localhost:8000";
const USER_ID = "test_user_1";

interface FoodLog {
  _id: string;
  food_name: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  quantity: string;
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
  const [started, setStarted] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    fetchLogs();
    fetchSummary();
  }, []);

  useEffect(() => {
    if (!status) return;
    const timer = setTimeout(() => setStatus(""), 5000);
    return () => clearTimeout(timer);
  }, [status]);

  function handleStart() {
    setStarted(true);
    speak(
      `Today you have logged ${summary.calories} calories. Protein ${summary.protein} grams, carbs ${summary.carbs} grams, fat ${summary.fat} grams.`,
    );
  }

  async function fetchLogs() {
    const res = await fetch(`${API_BASE}/food/${USER_ID}/today`);
    const data = await res.json();
    setLogs(data.reverse());
  }

  async function submitText() {
    if (!textInput.trim()) return;
    setLoading(true);
    setStatus("Parsing...");
    try {
      const res = await fetch(`${API_BASE}/food`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: USER_ID, raw_input: textInput }),
      });
      const data = await res.json();
      const msg = `Logged ${data.parsed.food}, ${data.parsed.calories} calories`;
      setStatus(msg);
      speak(msg);
      setTextInput("");
      fetchLogs();
    } catch {
      const err = "Error logging food.";
      setStatus(err);
      speak(err);
    } finally {
      setLoading(false);
    }
  }

  async function deleteLog(id: string) {
    if (!confirm("Delete this entry?")) return;
    await fetch(`${API_BASE}/food/${id}`, { method: "DELETE" });
    fetchLogs();
  }

  async function saveEdit(id: string) {
    if (!editInput.trim()) return;
    await fetch(`${API_BASE}/food/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_input: editInput, user_id: USER_ID }),
    });
    setEditingId(null);
    fetchLogs();
    fetchSummary();
  }
  async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
    recorder.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      const formData = new FormData();
      formData.append("user_id", USER_ID);
      formData.append("audio", blob, "recording.webm");
      setLoading(true);
      setStatus("Transcribing...");
      try {
        const res = await fetch(`${API_BASE}/food/voice`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        const msg = `Logged ${data.parsed.food}, ${data.parsed.calories} calories`;
        setStatus(
          `Heard: "${data.transcription}" — ${data.parsed.food}, ${data.parsed.calories} cal`,
        );
        speak(msg);
        fetchLogs();
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
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  async function fetchSummary() {
    const res = await fetch(`${API_BASE}/food/${USER_ID}/summary`);
    const data = await res.json();
    setSummary(data);
    speak(
      `Today you have logged ${data.calories} calories. Protein ${data.protein} grams, carbs ${data.carbs} grams, fat ${data.fat} grams.`,
    );
  }

  return (
    <div
      style={{
        maxWidth: 600,
        margin: "40px auto",
        padding: "0 20px",
        fontFamily: "sans-serif",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <h1>Speak2Me Fitness</h1>
        {!started && (
          <button onClick={handleStart} style={{ padding: "10px 20px" }}>
            Tap to start
          </button>
        )}
      </div>
      <h2>Log by text</h2>
      <input
        type="text"
        value={textInput}
        onChange={(e) => setTextInput(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submitText()}
        placeholder="e.g. two eggs and a coffee"
        style={{ width: "100%", padding: 8, fontSize: 16, marginBottom: 8 }}
      />
      <button
        onClick={submitText}
        disabled={loading}
        style={{ padding: "8px 16px", backgroundColor: "red", color: "white" }}
      >
        Log food
      </button>

      <h2>Log by voice</h2>
      <button
        onClick={recording ? stopRecording : startRecording}
        disabled={loading}
        style={{
          padding: "8px 16px",
          background: recording ? "#c00" : "#333",
          color: "#fff",
        }}
      >
        {recording ? "Stop recording" : "Start recording"}
      </button>

      {status && <p style={{ marginTop: 12, color: "pink" }}>{status}</p>}

      <h2>Today&apos;s logs</h2>
      {logs.length === 0 && <p>No logs yet.</p>}
      <table
        style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}
      >
        <thead>
          <tr style={{ borderBottom: "2px solid #ccc", textAlign: "left" }}>
            <th style={{ padding: "6px 8px" }}>Food</th>
            <th style={{ padding: "6px 8px" }}>Cal</th>
            <th style={{ padding: "6px 8px" }}>P</th>
            <th style={{ padding: "6px 8px" }}>C</th>
            <th style={{ padding: "6px 8px" }}>F</th>
            <th style={{ padding: "6px 8px" }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => (
            <tr key={log._id} style={{ borderBottom: "1px solid #eee" }}>
              {editingId === log._id ? (
                <>
                  <td colSpan={5} style={{ padding: "6px 8px" }}>
                    <input
                      value={editInput}
                      onChange={(e) => setEditInput(e.target.value)}
                      placeholder="Describe what you ate"
                      title="Edit food entry"
                      style={{ width: "100%", padding: 6, fontSize: 14 }}
                    />
                  </td>
                  <td style={{ padding: "6px 8px" }}>
                    <button
                      onClick={() => saveEdit(log._id)}
                      style={{ marginRight: 8 }}
                    >
                      Save
                    </button>
                    <button onClick={() => setEditingId(null)}>Cancel</button>
                  </td>
                </>
              ) : (
                <>
                  <td style={{ padding: "6px 8px" }}>{log.food_name}</td>
                  <td style={{ padding: "6px 8px" }}>{log.calories}</td>
                  <td style={{ padding: "6px 8px" }}>{log.protein}g</td>
                  <td style={{ padding: "6px 8px" }}>{log.carbs}g</td>
                  <td style={{ padding: "6px 8px" }}>{log.fat}g</td>
                  <td style={{ padding: "6px 8px" }}>
                    <button
                      onClick={() => deleteLog(log._id)}
                      style={{ background: "red", color: "white" }}
                    >
                      Delete
                    </button>
                  </td>
                  <td style={{ padding: "6px 8px" }}>
                    <button
                      onClick={() => {
                        setEditingId(log._id);
                        setEditInput(log.raw_input);
                      }}
                      style={{ background: "blue", color: "white" }}
                    >
                      Edit
                    </button>
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <div
        style={{
          background: "#f5f5f5",
          padding: "12px 16px",
          borderRadius: 6,
          marginBottom: 16,
        }}
      >
        <strong>Today</strong> — {summary.calories} cal &nbsp;|&nbsp; P:{" "}
        {summary.protein}g &nbsp;|&nbsp; C: {summary.carbs}g &nbsp;|&nbsp; F:{" "}
        {summary.fat}g &nbsp;|&nbsp;
        {summary.entry_count} {summary.entry_count === 1 ? "entry" : "entries"}
      </div>
    </div>
  );
}
