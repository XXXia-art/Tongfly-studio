import {directions, yoloTargets} from '../data/droneBlockCatalog.js';
import {droneBridge} from '../services/droneBridge.js';
import {vlmClient} from '../services/vlmClient.js';
import {sdClient} from '../services/sdClient.js';

const fallbackScratch = {
  ArgumentType: {
    NUMBER: 'number',
    STRING: 'string'
  },
  BlockType: {
    BOOLEAN: 'Boolean',
    COMMAND: 'command',
    REPORTER: 'reporter'
  }
};

class DroneScratchExtension {
  constructor(Scratch = fallbackScratch, services = {}) {
    this.Scratch = Scratch || fallbackScratch;
    this.services = {
      droneBridge,
      vlmClient,
      sdClient,
      ...services
    };
  }

  getInfo() {
    const {ArgumentType, BlockType} = this.Scratch;
    return {
      id: 'droneVLM',
      name: '无人机 AI',
      color1: '#4c97ff',
      color2: '#3373cc',
      color3: '#2e5aa7',
      blocks: [
        {
          opcode: 'fly',
          blockType: BlockType.COMMAND,
          text: '[DIRECTION] 速度 [SPEED] 米/秒 时间 [SECONDS] 秒',
          arguments: {
            DIRECTION: {type: ArgumentType.STRING, menu: 'directions', defaultValue: '向前'},
            SPEED: {type: ArgumentType.NUMBER, defaultValue: 1},
            SECONDS: {type: ArgumentType.NUMBER, defaultValue: 2}
          }
        },
        {
          opcode: 'turn',
          blockType: BlockType.COMMAND,
          text: '转向 速度 [SPEED] 度/秒 时间 [SECONDS] 秒',
          arguments: {
            SPEED: {type: ArgumentType.NUMBER, defaultValue: 45},
            SECONDS: {type: ArgumentType.NUMBER, defaultValue: 1}
          }
        },
        {
          opcode: 'waitSeconds',
          blockType: BlockType.COMMAND,
          text: '等待 [SECONDS] 秒',
          arguments: {
            SECONDS: {type: ArgumentType.NUMBER, defaultValue: 1}
          }
        },
        {
          opcode: 'battery',
          blockType: BlockType.REPORTER,
          text: '电量'
        },
        {
          opcode: 'altitude',
          blockType: BlockType.REPORTER,
          text: '高度'
        },
        {
          opcode: 'yoloDetect',
          blockType: BlockType.BOOLEAN,
          text: 'YOLO 识别到 [TARGET] ?',
          arguments: {
            TARGET: {type: ArgumentType.STRING, menu: 'targets', defaultValue: '人'}
          }
        },
        {
          opcode: 'askVision',
          blockType: BlockType.REPORTER,
          text: '询问画面 [QUESTION]',
          arguments: {
            QUESTION: {type: ArgumentType.STRING, defaultValue: '前方有什么？'}
          }
        },
        {
          opcode: 'chat',
          blockType: BlockType.REPORTER,
          text: '问小助手 [TEXT]',
          arguments: {
            TEXT: {type: ArgumentType.STRING, defaultValue: '怎样飞得更稳？'}
          }
        },
        {
          opcode: 'createImage',
          blockType: BlockType.REPORTER,
          text: '创建图片 [PROMPT]',
          arguments: {
            PROMPT: {type: ArgumentType.STRING, defaultValue: '无人机看到的彩色天空'}
          }
        }
      ],
      menus: {
        directions: {
          acceptReporters: true,
          items: directions.map(item => item.label)
        },
        targets: {
          acceptReporters: true,
          items: yoloTargets
        }
      }
    };
  }

  fly(args) {
    return this.services.droneBridge.runCommand({
      direction: args.DIRECTION,
      speed: args.SPEED,
      seconds: args.SECONDS
    });
  }

  turn(args) {
    return this.services.droneBridge.runCommand({
      type: 'turn',
      speed: args.SPEED,
      seconds: args.SECONDS
    });
  }

  waitSeconds(args) {
    return this.services.droneBridge.runCommand({
      type: 'wait',
      speed: 0,
      seconds: args.SECONDS
    });
  }

  battery() {
    return Math.round(this.services.droneBridge.getFrameMeta().battery);
  }

  altitude() {
    return Number(this.services.droneBridge.getFrameMeta().altitude.toFixed(1));
  }

  async yoloDetect(args) {
    const result = await this.services.vlmClient.detect(args.TARGET, this.services.droneBridge.getFrameMeta());
    return result.found;
  }

  askVision(args) {
    return this.services.vlmClient.describeFrame(args.QUESTION, this.services.droneBridge.getFrameMeta());
  }

  chat(args) {
    return this.services.vlmClient.chat(args.TEXT);
  }

  createImage(args) {
    return this.services.sdClient.createImage(args.PROMPT);
  }
}

export default DroneScratchExtension;

if (typeof window !== 'undefined' && window.Scratch?.extensions) {
  window.Scratch.extensions.register(new DroneScratchExtension(window.Scratch));
}
