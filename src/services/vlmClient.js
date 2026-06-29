import {yoloTargets} from '../data/droneBlockCatalog.js';

class VLMClientMock {
  async chat(text) {
    await wait(260);
    if (/画面|看到|图像|前方|哪里/.test(text)) {
      return '我不会自动读取图传。运行「询问画面」积木或点击「看画面」时，我才会理解当前图像。';
    }
    if (/模块|封装|阶梯/.test(text)) {
      return '可以把「向前、向上、向前、向上」封装成「阶梯式飞行」，之后像普通积木一样调用。';
    }
    return '我在旁边陪你调程序。先用短动作试飞，再把常用动作封装成自己的积木。';
  }

  async describeFrame(question, frameMeta) {
    await wait(420);
    const meta = frameMeta || {};
    return `我看到${meta.scene || '一片安全的飞行区域'}。高度约 ${(meta.altitude || 0).toFixed(1)} 米，距离起点约 ${(meta.distance || 0).toFixed(1)} 米。${question ? `关于「${question}」，建议保持慢速并确认目标在画面中央。` : ''}`;
  }

  async detect(target, frameMeta) {
    await wait(300);
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

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export const vlmClient = new VLMClientMock();
export {VLMClientMock};
