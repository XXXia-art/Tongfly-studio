const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

async function postJson(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
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

class SDClient {
  async createImage(prompt) {
    const data = await postJson('/api/sd/generate', {
      prompt,
      width: 512,
      height: 512,
      num_inference_steps: 25,
      guidance_scale: 7.5
    });
    return `data:image/png;base64,${data.image_base64}`;
  }
}

export const sdClient = new SDClient();
export {SDClient};
