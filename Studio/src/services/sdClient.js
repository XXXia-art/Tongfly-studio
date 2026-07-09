import {sendMode} from './controlBus.js';

class SDClient {
  async createImage(prompt) {
    const result = await sendMode({
      mode: 4,
      describe: '创建图片'
    });
    return `已进入创建图片模式：${result.udp?.target || 'mode UDP'}`;
  }
}

export const sdClient = new SDClient();
export {SDClient};
