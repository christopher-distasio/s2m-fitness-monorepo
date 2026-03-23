import React, { useState, useRef, useEffect } from 'react';

const API_BASE = 'http://localhost:8000';
const USER_ID = 'test_user_1';

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

export default function Home() {
  const [textInput, setTextInput] = useState('');
  const [logs, setLogs] = useState<FoodLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [status, setStatus] = useState('');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    fetchLogs();
  }, []);

  async function fetchLogs() {
    const res = await fetch(`${API_BASE}/food/${USER_ID}`);
    const data = await res.json();
    setLogs(data.reverse());
  }

  async function submitText() {
    if (!textInput.trim()) return;
    setLoading(true);
    setStatus('Parsing...');
    try {
      const res = await fetch(`${API_BASE}/food`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: USER_ID, raw_input: textInput }),
      });
      const data = await res.json();
      setStatus(`Logged: ${data.parsed.food} — ${data.parsed.calories} cal (${data.parsed.confidence} confidence)`);
      setTextInput('');
      fetchLogs();
    } catch {
      setStatus('Error logging food.');
    } finally {
      setLoading(false);
    }
  }

  async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
    recorder.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
      const formData = new FormData();
      formData.append('user_id', USER_ID);
      formData.append('audio', blob, 'recording.webm');
      setLoading(true);
      setStatus('Transcribing...');
      try {
        const res = await fetch(`${API_BASE}/food/voice`, {
          method: 'POST',
          body: formData,
        });
        const data = await res.json();
        setStatus(`Heard: "${data.transcription}" — ${data.parsed.food}, ${data.parsed.calories} cal`);
        fetchLogs();
      } catch {
        setStatus('Error processing audio.');
      } finally {
        setLoading(false);
      }
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setRecording(true);
    setStatus('Recording...');
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  return (
    <div style={{ maxWidth: 600, margin: '40px auto', padding: '0 20px', fontFamily: 'sans-serif' }}>
      <h1>Speak2Me Fitness</h1>

      <h2>Log by text</h2>
      <input
        type="text"
        value={textInput}
        onChange={(e) => setTextInput(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submitText()}
        placeholder="e.g. two eggs and a coffee"
        style={{ width: '100%', padding: 8, fontSize: 16, marginBottom: 8 }}
      />
      <button onClick={submitText} disabled={loading} style={{ padding: '8px 16px' }}>
        Log food
      </button>

      <h2>Log by voice</h2>
      <button
        onClick={recording ? stopRecording : startRecording}
        disabled={loading}
        style={{ padding: '8px 16px', background: recording ? '#c00' : '#333', color: '#fff' }}
      >
        {recording ? 'Stop recording' : 'Start recording'}
      </button>

      {status && <p style={{ marginTop: 12, color: '#555' }}>{status}</p>}

      <h2>Today&apos;s logs</h2>
      {logs.length === 0 && <p>No logs yet.</p>}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #ccc', textAlign: 'left' }}>
            <th style={{ padding: '6px 8px' }}>Food</th>
            <th style={{ padding: '6px 8px' }}>Cal</th>
            <th style={{ padding: '6px 8px' }}>P</th>
            <th style={{ padding: '6px 8px' }}>C</th>
            <th style={{ padding: '6px 8px' }}>F</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => (
            <tr key={log._id} style={{ borderBottom: '1px solid #eee' }}>
              <td style={{ padding: '6px 8px' }}>{log.food_name}</td>
              <td style={{ padding: '6px 8px' }}>{log.calories}</td>
              <td style={{ padding: '6px 8px' }}>{log.protein}g</td>
              <td style={{ padding: '6px 8px' }}>{log.carbs}g</td>
              <td style={{ padding: '6px 8px' }}>{log.fat}g</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}