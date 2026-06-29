import {yoloTargets} from '../data/droneBlockCatalog.js';

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

class VLMClient {
  async chat(text) {
    const data = await postJson('/api/vlm/chat', {text});
    return data.response;
  }

  async describeFrame(question, frameMeta, imageBase64) {
    const data = await postJson('/api/vlm/describe', {
      question,
      image_base64: imageBase64 || undefined
    });
    return data.response;
  }

  async detect(target, frameMeta) {
    // YOLO 模型权重尚未准备，仍使用规则化模拟结果。
    const visibleTargets = new Set(['降落垫', '蓝色圆环', '树']);
    if ((frameMeta?.altitude || 0) > 1.8) visibleTargets.add('人');
    if ((frameMeta?.target || '') === target) visibleTargets.add(target);
    return {
      target,
      found: visibleTargets.has(target),
      confidence: visibleTargets.has(target) ? 0.78 : 0.18,
      knownTargets: yoloTargets
    };
  }
}

export const vlmClient = new VLMClient();
export {VLMClient};
