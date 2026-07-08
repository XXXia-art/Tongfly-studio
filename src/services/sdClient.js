import {sendContent} from './controlBus.js';

class SDClient {
  async createImage(prompt) {
    const result = await sendContent({
      type: 'creative_paint_input',
      source: '创意喷绘',
      payload: {prompt}
    });
    return `已发送到总控状态机：${result.udp?.target || 'content UDP'}`;
  }
}

export const sdClient = new SDClient();
export {SDClient};
