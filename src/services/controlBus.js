const BRIDGE_BASE = import.meta.env?.VITE_BRIDGE_BASE_URL || '';

async function postJson(path, body) {
  const response = await fetch(`${BRIDGE_BASE}${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const text = await response.text().catch(() => 'unknown error');
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return response.json();
}

export function sendMode(payload) {
  return postJson('/bridge/mode', {
    mode: payload.mode
  });
}

export function sendContent(payload) {
  return postJson('/bridge/content', payload);
}
