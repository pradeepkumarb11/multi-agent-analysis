const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function createSession() {
  const res = await fetch(`${API_URL}/api/sessions`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to create session');
  return res.json();
}

export async function uploadCSV(sessionId, file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_URL}/api/upload/${sessionId}`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error('Failed to upload CSV');
  return res.json();
}

export async function askQuestion(sessionId, uploadId, question) {
  const res = await fetch(`${API_URL}/api/ask/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: uploadId, question }),
  });
  if (!res.ok) throw new Error('Failed to submit question');
  return res.json();
}

export function streamJobEvents(jobId, onEvent, onComplete, onError) {
  const eventSource = new EventSource(`${API_URL}/api/stream/${jobId}`);

  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.agent === 'END') {
        eventSource.close();
        onComplete(data);
      } else {
        onEvent(data);
      }
    } catch (err) {
      console.error('SSE parse error:', err);
    }
  };

  eventSource.onerror = (err) => {
    console.error('SSE connection error:', err);
    eventSource.close();
    onError(new Error('Connection to stream lost.'));
  };

  return () => eventSource.close();
}

export async function getHistory(sessionId) {
  const res = await fetch(`${API_URL}/api/history/${sessionId}`);
  if (!res.ok) throw new Error('Failed to fetch history');
  return res.json();
}
