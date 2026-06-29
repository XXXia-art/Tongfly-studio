const SCRATCH_MOTION = '#4C97FF';
const SCRATCH_CONTROL = '#FFAB19';

export const yoloTargets = [
  '人',
  '无人机',
  '降落垫',
  '小车',
  '树',
  '球',
  '红色物体',
  '蓝色圆环'
];

export const directions = [
  {label: '向前', type: 'forward', icon: '↑', color: SCRATCH_MOTION},
  {label: '向后', type: 'backward', icon: '↓', color: SCRATCH_MOTION},
  {label: '向左', type: 'left', icon: '←', color: SCRATCH_MOTION},
  {label: '向右', type: 'right', icon: '→', color: SCRATCH_MOTION},
  {label: '向上', type: 'up', icon: '⇧', color: SCRATCH_MOTION},
  {label: '向下', type: 'down', icon: '⇩', color: SCRATCH_MOTION}
];

export const blockCatalog = {
  flight: {
    label: '飞行',
    color: SCRATCH_MOTION,
    blocks: [
      ...directions.map(direction => ({
        id: direction.type,
        kind: 'command',
        color: direction.color,
        icon: direction.icon,
        text: `${direction.label} [speed] 米/秒 [seconds] 秒`,
        defaults: {speed: direction.type === 'up' || direction.type === 'down' ? 0.6 : 1, seconds: direction.type === 'up' || direction.type === 'down' ? 1.5 : 2}
      })),
      {
        id: 'turn',
        kind: 'command',
        color: SCRATCH_MOTION,
        icon: '↻',
        text: '转向 [speed] 度/秒 [seconds] 秒',
        defaults: {speed: 45, seconds: 1}
      }
    ]
  },
  logic: {
    label: '逻辑',
    color: SCRATCH_CONTROL,
    note: '迁移到 scratch-gui 后优先使用 Scratch 原生 Control 分类。',
    blocks: [
      {id: 'repeat', kind: 'native', color: SCRATCH_CONTROL, shape: 'control', text: '重复执行 [times] 次'},
      {id: 'forever', kind: 'native', color: SCRATCH_CONTROL, shape: 'control', text: '无限循环'},
      {id: 'ifThen', kind: 'native', color: SCRATCH_CONTROL, shape: 'control', text: '如果 [condition] 那么'},
      {id: 'wait', kind: 'native', color: SCRATCH_CONTROL, text: '等待 [seconds] 秒'},
      {id: 'sustain', kind: 'loop', color: SCRATCH_CONTROL, shape: 'control', text: '持续执行 [seconds] 秒'}
    ]
  },
  ai: {
    label: 'AI',
    color: '#9966ff',
    blocks: [
      {
        id: 'yoloDetect',
        kind: 'boolean',
        color: '#9966ff',
        icon: '◆',
        text: 'YOLO 识别到 [target] ?',
        defaults: {target: '人'}
      },
      {
        id: 'askVision',
        kind: 'reporter',
        color: '#0f8c73',
        icon: '?',
        text: '询问画面 [question]',
        defaults: {question: '前方有什么？'}
      },
      {
        id: 'chat',
        kind: 'reporter',
        color: '#9966ff',
        icon: '…',
        text: '问小助手 [text]',
        defaults: {text: '怎样飞得更稳？'}
      },
      {
        id: 'createImage',
        kind: 'reporter',
        color: '#cf6b37',
        icon: '▣',
        text: '创建图片 [prompt]',
        defaults: {prompt: '无人机看到的彩色天空'}
      }
    ]
  },
  custom: {
    label: '封装',
    color: '#4d7a64',
    blocks: [
      {id: 'stairFlight', kind: 'custom', text: '阶梯式飞行'}
    ]
  }
};

export const starterProgram = [
  {id: 'forward', params: {speed: 1, seconds: 2}},
  {id: 'up', params: {speed: 0.6, seconds: 1.5}},
  {id: 'forward', params: {speed: 1, seconds: 2}},
  {id: 'up', params: {speed: 0.6, seconds: 1.5}},
  {id: 'askVision', params: {question: '我现在飞到哪里了？'}}
];
