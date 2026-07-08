import {sendContent} from './controlBus.js';

class SDClient {
  async createImage(prompt) {
    const result = await sendContent({
      mode: 3,
      describe: '文本SD生成图片',
      payload: {prompt}
    });
    return `已发送到总控状态机：${result.udp?.target || 'content UDP'}`;
  }
}

export const sdClient = new SDClient();
export {SDClient};
