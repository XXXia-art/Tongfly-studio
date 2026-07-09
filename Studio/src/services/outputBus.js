const BRIDGE_BASE = import.meta.env?.VITE_BRIDGE_BASE_URL || '';

export async function readOutput(since = 0) {
  const response = await fetch(`${BRIDGE_BASE}/bridge/output?since=${encodeURIComponent(since)}`);
  if (!response.ok) {
    const text = await response.text().catch(() => 'unknown error');
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return response.json();
}
