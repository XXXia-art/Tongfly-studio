import {yoloTargets} from '../data/droneBlockCatalog.js';
import {sendContent} from './controlBus.js';

class VLMClient {
  async chat(text, options = {}) {
    const {mode = 7} = options;
    const result = await sendContent({
      mode,
      text
    });
    return `已发送到总控状态机：${result.udp?.target || 'content UDP'}`;
  }

  async describeFrame(question, frameMeta, imageBase64) {
    const result = await sendContent({
      mode: 6,
      text: question
    });
    return `看画面请求已发送到总控状态机：${result.udp?.target || 'content UDP'}`;
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
