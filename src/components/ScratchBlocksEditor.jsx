import React, {forwardRef, useEffect, useImperativeHandle, useRef} from 'react';
import * as ScratchBlocks from 'scratch-blocks';
import {yoloTargets} from '../data/droneBlockCatalog.js';

const BLOCKS_MEDIA_PATH = '/blocks-media/';
const FOREVER_DEMO_LIMIT = 10;

function scratchStyle(primary, secondary, tertiary) {
  return {
    colourPrimary: primary,
    colourSecondary: secondary,
    colourTertiary: tertiary
  };
}

const scratchDroneTheme = ScratchBlocks.Theme.defineTheme('scratch-drone-default', {
  blockStyles: {
    motion: scratchStyle('#4C97FF', '#4280D7', '#3373CC'),
    looks: scratchStyle('#9966FF', '#855CD6', '#774DCB'),
    sounds: scratchStyle('#CF63CF', '#C94FC9', '#BD42BD'),
    control: scratchStyle('#FFAB19', '#EC9C13', '#CF8B17'),
    event: scratchStyle('#FFBF00', '#E6AC00', '#CC9900'),
    sensing: scratchStyle('#5CB1D6', '#47A8D1', '#2E8EB8'),
    pen: scratchStyle('#0FBD8C', '#0DA57A', '#0B8E69'),
    operators: scratchStyle('#59C059', '#46B946', '#389438'),
    data: scratchStyle('#FF8C1A', '#FF8000', '#DB6E00'),
    data_lists: scratchStyle('#FF661A', '#FF5500', '#E64D00'),
    more: scratchStyle('#FF6680', '#FF4D6A', '#FF3355'),
    textField: scratchStyle('#FFFFFF', '#FFFFFF', '#DDDDDD')
  },
  categoryStyles: {
    motion_category: {colour: '#4C97FF'},
    looks_category: {colour: '#9966FF'},
    control_category: {colour: '#FFAB19'},
    sensing_category: {colour: '#5CB1D6'},
    more_category: {colour: '#FF6680'}
  },
  componentStyles: {
    workspaceBackgroundColour: '#F9F9F9',
    toolboxBackgroundColour: '#FFFFFF',
    toolboxForegroundColour: '#575E75',
    flyoutBackgroundColour: '#F9F9F9',
    flyoutForegroundColour: '#575E75',
    scrollbarColour: '#CECDCE',
    scrollbarOpacity: 1,
    insertionMarkerColour: '#000000',
    insertionMarkerOpacity: 0.2,
    markerColour: '#4C97FF',
    cursorColour: '#4C97FF'
  }
});

const blockTypes = {
  forward: 'drone_forward',
  backward: 'drone_backward',
  left: 'drone_left',
  right: 'drone_right',
  up: 'drone_up',
  down: 'drone_down',
  turn: 'drone_turn',
  hover: 'drone_hover',
  land: 'drone_land',
  returnHome: 'drone_return_home',
  stopFlight: 'drone_stop_flight',
  yoloDetect: 'drone_yolo_detect',
  yoloCount: 'drone_yolo_count',
  yoloPosition: 'drone_yolo_position',
  yoloNear: 'drone_yolo_near',
  followTarget: 'drone_follow_target',
  avoidTarget: 'drone_avoid_target',
  landingPadFound: 'drone_landing_pad_found',
  askVision: 'drone_ask_vision',
  sceneSummary: 'drone_scene_summary',
  isSceneSafe: 'drone_scene_safe',
  canLand: 'drone_can_land',
  taskDone: 'drone_task_done',
  chooseAction: 'drone_choose_action',
  chat: 'drone_chat',
  createImage: 'drone_create_image',
  createFromFrame: 'drone_create_from_frame',
  transformFrame: 'drone_transform_frame',
  saveImage: 'drone_save_image',
  showImage: 'drone_show_image',
  whenRun: 'drone_when_run',
  whenDetected: 'drone_when_detected',
  whenBatteryLow: 'drone_when_battery_low',
  whenDistanceLess: 'drone_when_distance_less',
  whenHeard: 'drone_when_heard',
  whenTaskDone: 'drone_when_task_done',
  safetyBatteryReturn: 'drone_safety_battery_return',
  safetyTooCloseStop: 'drone_safety_too_close_stop',
  safetyUnsafeHover: 'drone_safety_unsafe_hover',
  setMaxAltitude: 'drone_set_max_altitude',
  setMaxSpeed: 'drone_set_max_speed',
  emergencyStop: 'drone_emergency_stop',
  protectMode: 'drone_protect_mode',
  battery: 'drone_battery',
  altitude: 'drone_altitude',
  distance: 'drone_distance',
  moduleCall: 'drone_module_call'
};

const flightBlocks = [
  [blockTypes.forward, '向前', 'forward', 1, 2, '米/秒'],
  [blockTypes.backward, '向后', 'backward', 1, 2, '米/秒'],
  [blockTypes.left, '向左', 'left', 1, 1, '米/秒'],
  [blockTypes.right, '向右', 'right', 1, 1, '米/秒'],
  [blockTypes.up, '向上', 'up', 0.6, 1.5, '米/秒'],
  [blockTypes.down, '向下', 'down', 0.6, 1.5, '米/秒']
];

const directions = ['左', '中', '右'];
const actionChoices = ['悬停', '向前', '降落', '返航'];
const styleChoices = ['卡通', '科幻', '手绘', '夜晚'];
const yoloTargetOptions = ['人', '猫', '狗', '汽车'];

let droneBlocksRegistered = false;

const ScratchBlocksEditor = forwardRef(function ScratchBlocksEditor({services, onLog}, ref) {
  const hostRef = useRef(null);
  const workspaceRef = useRef(null);
  const cleanupToolboxCategoriesRef = useRef(() => {});

  useImperativeHandle(ref, () => ({
    runProgram: async () => {
      await deployWorkspace(workspaceRef.current, services, onLog);
      await runWorkspace(workspaceRef.current, services, onLog);
    },
    resetProgram: () => loadStarterWorkspace(workspaceRef.current),
    getWorkspaceXml: () => serializeWorkspace(workspaceRef.current),
    getMissionFile: () => compileWorkspaceToMission(workspaceRef.current),
    refreshModules: () => refreshToolbox(workspaceRef.current, hostRef.current, cleanupToolboxCategoriesRef)
  }), [services, onLog]);

  useEffect(() => {
    if (!hostRef.current) return undefined;

    ensureScratchMessages();
    registerDroneBlocks();
    const workspace = ScratchBlocks.inject(hostRef.current, {
      toolbox: buildToolboxXml(),
      theme: scratchDroneTheme,
      pathToMedia: BLOCKS_MEDIA_PATH,
      media: BLOCKS_MEDIA_PATH,
      trashcan: true,
      comments: true,
      collapse: false,
      sounds: false,
      oneBasedIndex: true,
      move: {
        scrollbars: true,
        drag: true,
        wheel: true
      },
      zoom: {
        controls: true,
        wheel: true,
        startScale: 0.88,
        maxScale: 1.8,
        minScale: 0.55,
        scaleSpeed: 1.1
      }
    });

    workspaceRef.current = workspace;
    loadStarterWorkspace(workspace);
    requestAnimationFrame(() => {
      ScratchBlocks.svgResize(workspace);
      cleanupToolboxCategoriesRef.current = decorateToolboxCategories(hostRef.current);
    });

    const resizeObserver = new ResizeObserver(() => ScratchBlocks.svgResize(workspace));
    resizeObserver.observe(hostRef.current);
    const handleModulesChanged = event => {
      refreshToolbox(workspace, hostRef.current, cleanupToolboxCategoriesRef);
      if (event.detail?.deletedModule) {
        onLog?.(`模块「${event.detail.deletedModule}」已删除。`);
      }
    };
    window.addEventListener('drone-modules-changed', handleModulesChanged);

    return () => {
      window.removeEventListener('drone-modules-changed', handleModulesChanged);
      cleanupToolboxCategoriesRef.current();
      resizeObserver.disconnect();
      workspace.dispose();
      workspaceRef.current = null;
    };
  }, []);

  return <div className="scratch-blocks-host" ref={hostRef} />;
});

function refreshToolbox(workspace, host, cleanupRef) {
  if (!workspace) return;
  workspace.updateToolbox(buildToolboxXml());
  const runDecoration = () => {
    cleanupRef?.current?.();
    const cleanup = decorateToolboxCategories(host);
    if (cleanupRef) cleanupRef.current = cleanup;
  };
  requestAnimationFrame(runDecoration);
}

function decorateToolboxCategories(host) {
  const categories = Array.from(host?.querySelectorAll('.blocklyToolboxCategoryContainer') || []);
  if (!categories.length) return () => {};

  const selectCategory = selectedCategory => {
    categories.forEach(category => {
      category.classList.toggle('drone-category-selected', category === selectedCategory);
    });
  };

  const cleanups = categories.map((category, index) => {
    const handleClick = () => selectCategory(category);
    category.addEventListener('click', handleClick);
    category.classList.toggle('drone-category-selected', index === 0);
    return () => category.removeEventListener('click', handleClick);
  });

  return () => cleanups.forEach(cleanup => cleanup());
}

function getSavedModuleNames() {
  const names = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (key?.startsWith('droneModule:')) {
      names.push(key.slice('droneModule:'.length));
    }
  }
  return names.sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
}

function ensureScratchMessages() {
  Object.assign(ScratchBlocks.Msg, {
    CONTROL_FOREVER: '重复执行',
    CONTROL_REPEAT: '重复执行 %1 次',
    CONTROL_IF: '如果 %1 那么',
    CONTROL_ELSE: '否则',
    CONTROL_STOP: '停止',
    CONTROL_STOP_ALL: '全部脚本',
    CONTROL_STOP_THIS: '这个脚本',
    CONTROL_STOP_OTHER: '角色的其他脚本',
    CONTROL_WAIT: '等待 %1 秒',
    CONTROL_WAITUNTIL: '等待直到 %1',
    CONTROL_REPEATUNTIL: '重复执行直到 %1',
    CONTROL_WHILE: '当 %1',
    CONTROL_FOREACH: '对于 %1 中的每一个 %2',
    CONTROL_STARTASCLONE: '当作为克隆体启动时',
    CONTROL_CREATECLONEOF: '克隆 %1',
    CONTROL_CREATECLONEOF_MYSELF: '自己',
    CONTROL_DELETETHISCLONE: '删除此克隆体',
    CONTROL_COUNTER: '计数器',
    CONTROL_INCRCOUNTER: '计数器增加',
    CONTROL_CLEARCOUNTER: '计数器归零',
    CONTROL_ALLATONCE: '作为单个帧运行',
    DUPLICATE_BLOCK: '复制',
    DELETE_BLOCK: '删除',
    DELETE_X_BLOCKS: '删除 %1 块积木',
    DELETE_ALL_BLOCKS: '删除全部 %1 块积木？',
    CLEAN_UP: '整理积木',
    ADD_COMMENT: '添加注释',
    REMOVE_COMMENT: '删除注释',
    COLLAPSE_BLOCK: '折叠积木',
    EXPAND_BLOCK: '展开积木',
    HELP: '帮助',
    UNDO: '撤销',
    REDO: '重做'
  });
}

function registerDroneBlocks() {
  if (droneBlocksRegistered) return;

  flightBlocks.forEach(([type, label]) => {
    ScratchBlocks.Blocks[type] = {
      init() {
        this.jsonInit({
          message0: `${label} 速度 %1 米/秒 时间 %2 秒`,
          args0: [
            {type: 'input_value', name: 'SPEED', check: 'Number'},
            {type: 'input_value', name: 'SECONDS', check: 'Number'}
          ],
          extensions: ['colours_motion', 'shape_statement']
        });
      }
    };
  });

  ScratchBlocks.Blocks[blockTypes.turn] = {
    init() {
      const ws = this.workspace.options.parentWorkspace ?? this.workspace;
      this.jsonInit({
        message0: '转向 %1 速度 %2 度/秒 时间 %3 秒',
        args0: [
          {
            type: 'field_image',
            src: ws.options.pathToMedia + 'rotate-right.svg',
            width: 24,
            height: 24,
            alt: '↻'
          },
          {type: 'input_value', name: 'SPEED', check: 'Number'},
          {type: 'input_value', name: 'SECONDS', check: 'Number'}
        ],
        extensions: ['colours_motion', 'shape_statement']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.hover] = {
    init() {
      this.jsonInit({
        message0: '悬停 %1 秒',
        args0: [{type: 'input_value', name: 'SECONDS', check: 'Number'}],
        extensions: ['colours_motion', 'shape_statement']
      });
    }
  };

  [
    [blockTypes.land, '降落'],
    [blockTypes.returnHome, '返航'],
    [blockTypes.stopFlight, '停止全部飞行']
  ].forEach(([type, label]) => {
    ScratchBlocks.Blocks[type] = {
      init() {
        this.jsonInit({
          message0: label,
          extensions: ['colours_motion', 'shape_statement']
        });
      }
    };
  });

  ScratchBlocks.Blocks[blockTypes.yoloDetect] = {
    init() {
      this.jsonInit({
        message0: 'YOLO 识别到 %1 ?',
        args0: [{type: 'field_dropdown', name: 'TARGET', options: yoloTargetOptions.map(value => [value, value])}],
        extensions: ['colours_sensing', 'output_boolean']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.yoloCount] = {
    init() {
      this.jsonInit({
        message0: '%1 的数量',
        args0: [{type: 'input_value', name: 'TARGET', check: 'String'}],
        extensions: ['colours_sensing', 'output_number']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.yoloPosition] = {
    init() {
      this.jsonInit({
        message0: '%1 在画面 %2 ?',
        args0: [
          {type: 'input_value', name: 'TARGET', check: 'String'},
          {type: 'field_dropdown', name: 'POSITION', options: directions.map(value => [value, value])}
        ],
        extensions: ['colours_sensing', 'output_boolean']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.yoloNear] = {
    init() {
      this.jsonInit({
        message0: '%1 是否靠近 ?',
        args0: [{type: 'input_value', name: 'TARGET', check: 'String'}],
        extensions: ['colours_sensing', 'output_boolean']
      });
    }
  };

  [
    [blockTypes.followTarget, '跟随目标 %1'],
    [blockTypes.avoidTarget, '避开目标 %1']
  ].forEach(([type, message0]) => {
    ScratchBlocks.Blocks[type] = {
      init() {
        this.jsonInit({
          message0,
          args0: [{type: 'input_value', name: 'TARGET', check: 'String'}],
          extensions: ['colours_sensing', 'shape_statement']
        });
      }
    };
  });

  ScratchBlocks.Blocks[blockTypes.landingPadFound] = {
    init() {
      this.jsonInit({
        message0: '找到降落垫 ?',
        extensions: ['colours_sensing', 'output_boolean']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.askVision] = {
    init() {
      this.jsonInit({
        message0: '询问画面 %1',
        args0: [{type: 'input_value', name: 'QUESTION', check: 'String'}],
        extensions: ['colours_sensing', 'output_string']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.sceneSummary] = {
    init() {
      this.jsonInit({
        message0: '画面里有什么',
        extensions: ['colours_sensing', 'output_string']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.isSceneSafe] = {
    init() {
      this.jsonInit({
        message0: '前方安全吗 ?',
        extensions: ['colours_sensing', 'output_boolean']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.canLand] = {
    init() {
      this.jsonInit({
        message0: '适合降落吗 ?',
        extensions: ['colours_sensing', 'output_boolean']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.taskDone] = {
    init() {
      this.jsonInit({
        message0: '任务完成了吗 %1',
        args0: [{type: 'input_value', name: 'TASK', check: 'String'}],
        extensions: ['colours_sensing', 'output_boolean']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.chooseAction] = {
    init() {
      this.jsonInit({
        message0: '根据画面选择动作 %1',
        args0: [{type: 'input_value', name: 'QUESTION', check: 'String'}],
        extensions: ['colours_sensing', 'output_string']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.chat] = {
    init() {
      this.jsonInit({
        message0: '问小助手 %1',
        args0: [{type: 'input_value', name: 'TEXT', check: 'String'}],
        extensions: ['colours_looks', 'output_string']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.createImage] = {
    init() {
      this.jsonInit({
        message0: '创建图片 %1',
        args0: [{type: 'input_value', name: 'PROMPT', check: 'String'}],
        extensions: ['colours_looks', 'output_string']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.createFromFrame] = {
    init() {
      this.jsonInit({
        message0: '把当前画面画成 %1 风格',
        args0: [{type: 'field_dropdown', name: 'STYLE', options: styleChoices.map(value => [value, value])}],
        extensions: ['colours_looks', 'output_string']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.transformFrame] = {
    init() {
      this.jsonInit({
        message0: '把画面变成 %1',
        args0: [{type: 'field_dropdown', name: 'STYLE', options: styleChoices.map(value => [value, value])}],
        extensions: ['colours_looks', 'output_string']
      });
    }
  };

  [
    [blockTypes.saveImage, '保存生成图片'],
    [blockTypes.showImage, '显示生成图片']
  ].forEach(([type, label]) => {
    ScratchBlocks.Blocks[type] = {
      init() {
        this.jsonInit({
          message0: label,
          extensions: ['colours_looks', 'shape_statement']
        });
      }
    };
  });

  [
    [blockTypes.whenRun, '当点击运行'],
    [blockTypes.whenTaskDone, '当任务完成']
  ].forEach(([type, label]) => {
    ScratchBlocks.Blocks[type] = {
      init() {
        this.jsonInit({
          message0: label,
          extensions: ['colours_event', 'shape_hat']
        });
      }
    };
  });

  ScratchBlocks.Blocks[blockTypes.whenDetected] = {
    init() {
      this.jsonInit({
        message0: '当识别到 %1',
        args0: [{type: 'input_value', name: 'TARGET', check: 'String'}],
        extensions: ['colours_event', 'shape_hat']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.whenBatteryLow] = {
    init() {
      this.jsonInit({
        message0: '当电量低于 %1 %',
        args0: [{type: 'input_value', name: 'PERCENT', check: 'Number'}],
        extensions: ['colours_event', 'shape_hat']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.whenDistanceLess] = {
    init() {
      this.jsonInit({
        message0: '当距离小于 %1 米',
        args0: [{type: 'input_value', name: 'DISTANCE', check: 'Number'}],
        extensions: ['colours_event', 'shape_hat']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.whenHeard] = {
    init() {
      this.jsonInit({
        message0: '当听到指令 %1',
        args0: [{type: 'input_value', name: 'TEXT', check: 'String'}],
        extensions: ['colours_event', 'shape_hat']
      });
    }
  };

  [
    [blockTypes.safetyBatteryReturn, '如果电量低，自动返航'],
    [blockTypes.safetyTooCloseStop, '如果距离太近，停止'],
    [blockTypes.safetyUnsafeHover, '如果画面不安全，悬停'],
    [blockTypes.emergencyStop, '紧急停止'],
    [blockTypes.protectMode, '开启保护模式']
  ].forEach(([type, label]) => {
    ScratchBlocks.Blocks[type] = {
      init() {
        this.jsonInit({
          message0: label,
          extensions: ['colours_control', 'shape_statement']
        });
      }
    };
  });

  ScratchBlocks.Blocks[blockTypes.setMaxAltitude] = {
    init() {
      this.jsonInit({
        message0: '设置最大高度 %1 米',
        args0: [{type: 'input_value', name: 'ALTITUDE', check: 'Number'}],
        extensions: ['colours_control', 'shape_statement']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.setMaxSpeed] = {
    init() {
      this.jsonInit({
        message0: '设置最大速度 %1 米/秒',
        args0: [{type: 'input_value', name: 'SPEED', check: 'Number'}],
        extensions: ['colours_control', 'shape_statement']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.battery] = {
    init() {
      this.jsonInit({
        message0: '电量',
        extensions: ['colours_sensing', 'output_number']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.distance] = {
    init() {
      this.jsonInit({
        message0: '距离',
        extensions: ['colours_sensing', 'output_number']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.altitude] = {
    init() {
      this.jsonInit({
        message0: '高度',
        extensions: ['colours_sensing', 'output_number']
      });
    }
  };

  ScratchBlocks.Blocks[blockTypes.moduleCall] = {
    init() {
      this.jsonInit({
        message0: '调用模块 %1',
        args0: [{type: 'field_input', name: 'MODULE', text: '阶梯式飞行'}],
        extensions: ['colours_more', 'shape_statement']
      });
    },
    customContextMenu(options) {
      if (!this.isInFlyout) return;
      const moduleName = this.getFieldValue('MODULE');
      if (!moduleName) return;
      options.push({
        enabled: true,
        text: `删除模块「${moduleName}」`,
        callback: () => {
          window.localStorage.removeItem(`droneModule:${moduleName}`);
          window.dispatchEvent(new CustomEvent('drone-modules-changed', {
            detail: {deletedModule: moduleName}
          }));
        }
      });
    }
  };

  droneBlocksRegistered = true;
}

function buildToolboxXml() {
  const modules = getSavedModuleNames();
  return `<xml id="toolbox" style="display: none">
    <category name="飞行" colour="#4C97FF" secondaryColour="#4280D7">
      ${flightBlocks.map(([type, , , speed, seconds]) => flightBlockXml(type, speed, seconds)).join('')}
      ${flightBlockXml(blockTypes.turn, 45, 1)}
      <block type="${blockTypes.hover}">${numberValue('SECONDS', 2)}</block>
    </category>
    <category name="逻辑" colour="#FFAB19" secondaryColour="#EC9C13">
      <block type="control_wait">${numberValue('DURATION', 1)}</block>
      <block type="control_repeat">${numberValue('TIMES', 3)}</block>
      <block type="control_forever"></block>
      <block type="control_repeat_until">${emptyValue('CONDITION')}</block>
    </category>
    <category name="感知" colour="#5CB1D6" secondaryColour="#47A8D1">
      <block type="${blockTypes.yoloDetect}"></block>
      <block type="${blockTypes.yoloCount}">${textValue('TARGET', '人')}</block>
      <block type="${blockTypes.yoloPosition}">${textValue('TARGET', '降落垫')}</block>
      <block type="${blockTypes.yoloNear}">${textValue('TARGET', '树')}</block>
      <block type="${blockTypes.followTarget}">${textValue('TARGET', '蓝色圆环')}</block>
      <block type="${blockTypes.avoidTarget}">${textValue('TARGET', '树')}</block>
      <block type="${blockTypes.landingPadFound}"></block>
      <block type="${blockTypes.battery}"></block>
      <block type="${blockTypes.altitude}"></block>
      <block type="${blockTypes.distance}"></block>
    </category>
    <category name="理解" colour="#5CB1D6" secondaryColour="#47A8D1">
      <block type="${blockTypes.askVision}">${textValue('QUESTION', '前方有什么？')}</block>
      <block type="${blockTypes.chat}">${textValue('TEXT', '怎样飞得更稳？')}</block>
      <block type="${blockTypes.sceneSummary}"></block>
      <block type="${blockTypes.isSceneSafe}"></block>
      <block type="${blockTypes.canLand}"></block>
      <block type="${blockTypes.taskDone}">${textValue('TASK', '找到降落垫')}</block>
      <block type="${blockTypes.chooseAction}">${textValue('QUESTION', '下一步怎么飞？')}</block>
    </category>
    <category name="创作" colour="#9966FF" secondaryColour="#855CD6">
      <block type="${blockTypes.createImage}">${textValue('PROMPT', '无人机看到的天空')}</block>
      <block type="${blockTypes.createFromFrame}"></block>
      <block type="${blockTypes.transformFrame}"></block>
      <block type="${blockTypes.saveImage}"></block>
      <block type="${blockTypes.showImage}"></block>
    </category>
    <category name="事件" colour="#FFBF00" secondaryColour="#E6AC00">
      <block type="${blockTypes.whenRun}"></block>
      <block type="${blockTypes.whenDetected}">${textValue('TARGET', '人')}</block>
      <block type="${blockTypes.whenBatteryLow}">${numberValue('PERCENT', 20)}</block>
      <block type="${blockTypes.whenDistanceLess}">${numberValue('DISTANCE', 1)}</block>
      <block type="${blockTypes.whenHeard}">${textValue('TEXT', '开始巡逻')}</block>
      <block type="${blockTypes.whenTaskDone}"></block>
    </category>
    <category name="封装" colour="#FF6680" secondaryColour="#FF4D6A">
      ${modules.length ? modules.map(moduleBlockXml).join('') : '<label text="还没有封装模块"></label>'}
    </category>
  </xml>`;
}

function moduleBlockXml(moduleName) {
  return `<block type="${blockTypes.moduleCall}">
    <field name="MODULE">${escapeXml(moduleName)}</field>
  </block>`;
}

function flightBlockXml(type, speed, seconds) {
  return `<block type="${type}">
    ${numberValue('SPEED', speed)}
    ${numberValue('SECONDS', seconds)}
  </block>`;
}

function numberValue(name, value) {
  return `<value name="${name}"><shadow type="math_number"><field name="NUM">${value}</field></shadow></value>`;
}

function textValue(name, value) {
  return `<value name="${name}"><shadow type="text"><field name="TEXT">${escapeXml(value)}</field></shadow></value>`;
}

function booleanValue(name) {
  return emptyValue(name);
}

function emptyValue(name) {
  return `<value name="${name}"></value>`;
}

function loadStarterWorkspace(workspace) {
  if (!workspace) return;
  workspace.clear();
  const starterXml = `<xml xmlns="https://developers.google.com/blockly/xml">
    <block type="${blockTypes.forward}" x="52" y="44">
      ${numberValue('SPEED', 1)}
      ${numberValue('SECONDS', 2)}
      <next>
        <block type="control_repeat">
          ${numberValue('TIMES', 3)}
          <statement name="SUBSTACK">
            <block type="${blockTypes.up}">
              ${numberValue('SPEED', 0.6)}
              ${numberValue('SECONDS', 1)}
              <next>
                <block type="${blockTypes.forward}">
                  ${numberValue('SPEED', 1)}
                  ${numberValue('SECONDS', 1.5)}
                </block>
              </next>
            </block>
          </statement>
        </block>
      </next>
    </block>
    <block type="${blockTypes.askVision}" x="430" y="70">
      ${textValue('QUESTION', '我现在飞到哪里了？')}
    </block>
  </xml>`;
  ScratchBlocks.Xml.domToWorkspace(ScratchBlocks.utils.xml.textToDom(starterXml), workspace);
}

function serializeWorkspace(workspace) {
  if (!workspace) return '';
  return ScratchBlocks.Xml.domToText(ScratchBlocks.Xml.workspaceToDom(workspace));
}

async function deployWorkspace(workspace, services, onLog) {
  const missionFile = compileWorkspaceToMission(workspace);
  if (!missionFile.programs.length) {
    onLog?.('没有可发送给无人机的任务文件。');
    return null;
  }

  const result = await services.droneBridge.sendMissionFile(missionFile);
  if (result.ok) {
    onLog?.(`任务文件 ${missionFile.id} 已发送到机载芯片，大小 ${result.bytes} 字节。`);
    onLog?.(`发送链路：${result.route}`);
  }
  return missionFile;
}

function compileWorkspaceToMission(workspace) {
  const sourceXml = serializeWorkspace(workspace);
  const programs = workspace ? workspace.getTopBlocks(true)
    .filter(block => !block.isInFlyout)
    .sort((a, b) => a.getRelativeToSurfaceXY().y - b.getRelativeToSurfaceXY().y)
    .map(block => compileTopBlock(block))
    .filter(Boolean) : [];
  const body = {
    format: 'TongfeiDroneMission',
    version: 1,
    id: `tdm-${Date.now().toString(36)}`,
    createdAt: new Date().toISOString(),
    target: {
      onboard: 'edge-chip',
      downstream: 'flight-controller'
    },
    safety: {
      maxForeverIterations: FOREVER_DEMO_LIMIT,
      requiresAck: true
    },
    programs,
    source: {
      type: 'scratch-blocks-xml',
      xml: sourceXml
    }
  };
  return {
    ...body,
    checksum: checksumJson(body)
  };
}

function checksumJson(value) {
  const text = JSON.stringify(value);
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
  }
  return `sum32:${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

function compileTopBlock(block) {
  const trigger = isEventHat(block.type) ? compileTrigger(block) : {type: 'manual_run'};
  const firstCommand = isEventHat(block.type) ? block.getNextBlock() : block;
  const stack = compileStack(firstCommand);
  if (!stack.length && block.outputConnection) {
    return {
      trigger,
      kind: 'reporter',
      value: compileExpression(block)
    };
  }
  if (!stack.length) return null;
  return {
    trigger,
    kind: 'stack',
    steps: stack
  };
}

function compileStack(firstBlock) {
  const steps = [];
  let block = firstBlock;
  while (block) {
    const command = compileCommand(block);
    if (command) steps.push(command);
    block = block.getNextBlock();
  }
  return steps;
}

function compileTrigger(block) {
  if (block.type === blockTypes.whenDetected) {
    return {type: 'vision_detected', target: compileInput(block, 'TARGET')};
  }
  if (block.type === blockTypes.whenBatteryLow) {
    return {type: 'battery_below', percent: compileInput(block, 'PERCENT')};
  }
  if (block.type === blockTypes.whenDistanceLess) {
    return {type: 'distance_below', meters: compileInput(block, 'DISTANCE')};
  }
  if (block.type === blockTypes.whenHeard) {
    return {type: 'voice_command', text: compileInput(block, 'TEXT')};
  }
  if (block.type === blockTypes.whenTaskDone) {
    return {type: 'task_done'};
  }
  return {type: 'manual_run'};
}

function compileCommand(block) {
  const flight = flightBlocks.find(([blockType]) => blockType === block.type);
  if (flight) {
    const [, label, commandType] = flight;
    return commandNode(commandType, label, {
      speed: compileInput(block, 'SPEED'),
      seconds: compileInput(block, 'SECONDS')
    });
  }

  const commandMap = {
    [blockTypes.turn]: ['turn', '转向', {speed: 'SPEED', seconds: 'SECONDS'}],
    [blockTypes.hover]: ['hover', '悬停', {seconds: 'SECONDS'}],
    [blockTypes.land]: ['land', '降落', {}],
    [blockTypes.returnHome]: ['return_home', '返航', {}],
    [blockTypes.stopFlight]: ['stop_flight', '停止全部飞行', {}],
    [blockTypes.followTarget]: ['follow_target', '跟随目标', {target: 'TARGET'}],
    [blockTypes.avoidTarget]: ['avoid_target', '避开目标', {target: 'TARGET'}],
    [blockTypes.saveImage]: ['save_generated_image', '保存生成图片', {}],
    [blockTypes.showImage]: ['show_generated_image', '显示生成图片', {}],
    [blockTypes.safetyBatteryReturn]: ['guard_battery_return', '电量低自动返航', {}],
    [blockTypes.safetyTooCloseStop]: ['guard_too_close_stop', '距离太近停止', {}],
    [blockTypes.safetyUnsafeHover]: ['guard_unsafe_hover', '画面不安全悬停', {}],
    [blockTypes.setMaxAltitude]: ['set_max_altitude', '设置最大高度', {meters: 'ALTITUDE'}],
    [blockTypes.setMaxSpeed]: ['set_max_speed', '设置最大速度', {meters_per_second: 'SPEED'}],
    [blockTypes.emergencyStop]: ['emergency_stop', '紧急停止', {}],
    [blockTypes.protectMode]: ['enable_protect_mode', '开启保护模式', {}],
    [blockTypes.moduleCall]: ['call_module', '调用模块', {module: 'MODULE'}]
  };

  if (commandMap[block.type]) {
    const [opcode, label, params] = commandMap[block.type];
    return commandNode(opcode, label, compileParamMap(block, params));
  }

  if (block.type === 'control_wait') {
    return commandNode('wait', '等待', {seconds: compileInput(block, 'DURATION')});
  }
  if (block.type === 'control_repeat') {
    return commandNode('repeat', '重复执行', {
      times: compileInput(block, 'TIMES'),
      steps: compileStack(block.getInputTargetBlock('SUBSTACK'))
    });
  }
  if (block.type === 'control_forever') {
    return commandNode('forever', '无限循环', {
      maxIterations: FOREVER_DEMO_LIMIT,
      steps: compileStack(block.getInputTargetBlock('SUBSTACK'))
    });
  }
  if (block.type === 'control_repeat_until') {
    return commandNode('repeat_until', '重复执行直到', {
      condition: compileInput(block, 'CONDITION'),
      steps: compileStack(block.getInputTargetBlock('SUBSTACK'))
    });
  }
  if (block.type === 'control_if') {
    return commandNode('if', '如果那么', {
      condition: compileInput(block, 'CONDITION'),
      steps: compileStack(block.getInputTargetBlock('SUBSTACK'))
    });
  }
  if (block.outputConnection) {
    return commandNode('evaluate', blockLabel(block), {value: compileExpression(block)});
  }
  return null;
}

function commandNode(opcode, label, params) {
  return {
    opcode,
    label,
    params
  };
}

function compileParamMap(block, paramMap) {
  return Object.fromEntries(Object.entries(paramMap).map(([param, input]) => [
    param,
    block.getField(input) ? block.getFieldValue(input) : compileInput(block, input)
  ]));
}

function compileInput(block, inputName) {
  const target = block.getInputTargetBlock(inputName);
  if (target) return compileExpression(target);
  if (block.getField(inputName)) return literalValue(block.getFieldValue(inputName));
  return null;
}

function compileExpression(block) {
  if (!block) return null;
  if (block.type === 'math_number' || block.type === 'math_integer' || block.type === 'math_positive_number') {
    return literalValue(Number(block.getFieldValue('NUM')));
  }
  if (block.type === 'text') {
    return literalValue(block.getFieldValue('TEXT') || '');
  }

  const expressionMap = {
    [blockTypes.battery]: ['battery_percent', '电量', {}],
    [blockTypes.altitude]: ['altitude_meters', '高度', {}],
    [blockTypes.distance]: ['distance_meters', '距离', {}],
    [blockTypes.yoloDetect]: ['yolo_detect', 'YOLO识别', {target: 'TARGET'}],
    [blockTypes.yoloCount]: ['yolo_count', '目标数量', {target: 'TARGET'}],
    [blockTypes.yoloPosition]: ['yolo_position_is', '目标位置', {target: 'TARGET', position: 'POSITION'}],
    [blockTypes.yoloNear]: ['yolo_near', '目标靠近', {target: 'TARGET'}],
    [blockTypes.landingPadFound]: ['landing_pad_found', '找到降落垫', {}],
    [blockTypes.askVision]: ['vlm_ask_frame', '询问画面', {question: 'QUESTION'}],
    [blockTypes.sceneSummary]: ['vlm_scene_summary', '画面里有什么', {}],
    [blockTypes.isSceneSafe]: ['vlm_scene_safe', '前方安全吗', {}],
    [blockTypes.canLand]: ['vlm_can_land', '适合降落吗', {}],
    [blockTypes.taskDone]: ['vlm_task_done', '任务完成了吗', {task: 'TASK'}],
    [blockTypes.chooseAction]: ['vlm_choose_action', '根据画面选择动作', {question: 'QUESTION'}],
    [blockTypes.chat]: ['vlm_chat', '问小助手', {text: 'TEXT'}],
    [blockTypes.createImage]: ['sd_text_to_image', '创建图片', {prompt: 'PROMPT'}],
    [blockTypes.createFromFrame]: ['sd_frame_to_image', '当前画面生成图', {style: 'STYLE'}],
    [blockTypes.transformFrame]: ['sd_transform_frame', '画面风格转换', {style: 'STYLE'}]
  };

  if (expressionMap[block.type]) {
    const [opcode, label, params] = expressionMap[block.type];
    return {
      kind: 'expression',
      opcode,
      label,
      params: compileParamMap(block, params)
    };
  }
  return {
    kind: 'expression',
    opcode: block.type,
    label: blockLabel(block),
    params: {}
  };
}

function literalValue(value) {
  return {
    kind: 'literal',
    value
  };
}

async function runWorkspace(workspace, services, onLog) {
  if (!workspace) return;
  const topBlocks = workspace.getTopBlocks(true)
    .filter(block => !block.isInFlyout)
    .sort((a, b) => a.getRelativeToSurfaceXY().y - b.getRelativeToSurfaceXY().y);

  if (!topBlocks.length) {
    onLog?.('工作区里还没有可运行的积木。');
    return;
  }

  for (const block of topBlocks) {
    if (block.outputConnection) {
      const value = await readBlockValue(block, services, onLog);
      onLog?.(`${blockLabel(block)}：${String(value)}`);
      continue;
    }
    await runStack(block, services, onLog);
  }
}

async function runStack(firstBlock, services, onLog) {
  let block = firstBlock;
  while (block) {
    await runBlock(block, services, onLog);
    block = block.getNextBlock();
  }
}

async function runBlock(block, services, onLog) {
  const type = block.type;
  const flight = flightBlocks.find(([blockType]) => blockType === type);
  if (flight) {
    const [, label, commandType] = flight;
    const speed = await readNumberInput(block, 'SPEED', services, 1);
    const seconds = await readNumberInput(block, 'SECONDS', services, 1);
    onLog?.(`${label}：速度 ${speed}，时间 ${seconds} 秒`);
    await services.droneBridge.runCommand({type: commandType, speed, seconds});
    return;
  }

  if (type === blockTypes.turn) {
    const speed = await readNumberInput(block, 'SPEED', services, 45);
    const seconds = await readNumberInput(block, 'SECONDS', services, 1);
    onLog?.(`转向：速度 ${speed}，时间 ${seconds} 秒`);
    await services.droneBridge.runCommand({type: 'turn', speed, seconds});
    return;
  }

  if (type === blockTypes.hover) {
    const seconds = await readNumberInput(block, 'SECONDS', services, 2);
    onLog?.(`悬停 ${seconds} 秒`);
    await services.droneBridge.runCommand({type: 'wait', speed: 0, seconds});
    return;
  }

  if (type === blockTypes.land) {
    onLog?.('降落：无人机缓慢下降。');
    await services.droneBridge.runCommand({type: 'down', speed: 0.6, seconds: 2});
    return;
  }

  if (type === blockTypes.returnHome) {
    onLog?.('返航：无人机向起点方向返回。');
    await services.droneBridge.runCommand({type: 'backward', speed: 1, seconds: 2});
    return;
  }

  if (type === blockTypes.stopFlight || type === blockTypes.emergencyStop) {
    onLog?.(type === blockTypes.emergencyStop ? '紧急停止：所有飞行动作已暂停。' : '停止全部飞行指令。');
    await services.droneBridge.runCommand({type: 'wait', speed: 0, seconds: 0.2});
    return;
  }

  if (type === 'control_wait') {
    const seconds = await readNumberInput(block, 'DURATION', services, 1);
    onLog?.(`等待 ${seconds} 秒`);
    await services.droneBridge.runCommand({type: 'wait', speed: 0, seconds});
    return;
  }

  if (type === 'control_repeat') {
    const times = Math.max(0, Math.min(50, Math.round(await readNumberInput(block, 'TIMES', services, 1))));
    onLog?.(`重复执行 ${times} 次`);
    for (let i = 0; i < times; i += 1) {
      await runStack(block.getInputTargetBlock('SUBSTACK'), services, onLog);
    }
    return;
  }

  if (type === 'control_forever') {
    onLog?.(`无限循环演示执行 ${FOREVER_DEMO_LIMIT} 次`);
    for (let i = 0; i < FOREVER_DEMO_LIMIT; i += 1) {
      await runStack(block.getInputTargetBlock('SUBSTACK'), services, onLog);
    }
    return;
  }

  if (type === 'control_repeat_until') {
    onLog?.(`重复执行直到条件成立，最多演示 ${FOREVER_DEMO_LIMIT} 次`);
    for (let i = 0; i < FOREVER_DEMO_LIMIT; i += 1) {
      if (await readBooleanInput(block, 'CONDITION', services, false)) return;
      await runStack(block.getInputTargetBlock('SUBSTACK'), services, onLog);
    }
    return;
  }

  if (type === 'control_if') {
    const passed = await readBooleanInput(block, 'CONDITION', services, false);
    onLog?.(passed ? '如果条件成立，执行内部积木。' : '如果条件不成立，跳过内部积木。');
    if (passed) await runStack(block.getInputTargetBlock('SUBSTACK'), services, onLog);
    return;
  }

  if (type === blockTypes.followTarget || type === blockTypes.avoidTarget) {
    const target = String(await readInputValue(block, 'TARGET', services) || '目标');
    const follow = type === blockTypes.followTarget;
    onLog?.(`${follow ? '跟随' : '避开'}目标：${target}`);
    await services.droneBridge.runCommand({type: follow ? 'forward' : 'backward', speed: 0.6, seconds: 1});
    return;
  }

  if (type === blockTypes.saveImage || type === blockTypes.showImage) {
    onLog?.(type === blockTypes.saveImage ? '生成图片已保存到作品里。' : '显示最近生成的图片。');
    return;
  }

  if (type === blockTypes.safetyBatteryReturn) {
    const battery = services.droneBridge.getFrameMeta().battery;
    if (battery < 25) {
      onLog?.('安全保护：电量偏低，自动返航。');
      await services.droneBridge.runCommand({type: 'backward', speed: 1, seconds: 2});
    } else {
      onLog?.(`安全保护：电量 ${Math.round(battery)}%，暂不返航。`);
    }
    return;
  }

  if (type === blockTypes.safetyTooCloseStop) {
    const distance = services.droneBridge.getFrameMeta().distance;
    onLog?.(distance < 1 ? '安全保护：距离太近，停止。' : '安全保护：距离正常。');
    if (distance < 1) await services.droneBridge.runCommand({type: 'wait', speed: 0, seconds: 0.2});
    return;
  }

  if (type === blockTypes.safetyUnsafeHover) {
    const safe = await readBlockValue({type: blockTypes.isSceneSafe}, services);
    if (!safe) {
      onLog?.('安全保护：画面不安全，先悬停。');
      await services.droneBridge.runCommand({type: 'wait', speed: 0, seconds: 1});
    } else {
      onLog?.('安全保护：画面安全。');
    }
    return;
  }

  if (type === blockTypes.setMaxAltitude) {
    const altitude = await readNumberInput(block, 'ALTITUDE', services, 3);
    onLog?.(`设置最大高度：${altitude} 米`);
    return;
  }

  if (type === blockTypes.setMaxSpeed) {
    const speed = await readNumberInput(block, 'SPEED', services, 1);
    onLog?.(`设置最大速度：${speed} 米/秒`);
    return;
  }

  if (type === blockTypes.protectMode) {
    onLog?.('保护模式已开启：将优先悬停、避障和返航。');
    return;
  }

  if (isEventHat(type)) {
    onLog?.(`${blockLabel(block)} 事件触发。`);
    return;
  }

  if (type === blockTypes.moduleCall) {
    await runSavedModule(block.getFieldValue('MODULE') || '阶梯式飞行', services, onLog);
    return;
  }

  if (block.outputConnection) {
    const value = await readBlockValue(block, services, onLog);
    onLog?.(`${blockLabel(block)}：${String(value)}`);
  }
}

async function runSavedModule(moduleName, services, onLog) {
  const moduleXml = window.localStorage.getItem(`droneModule:${moduleName}`);
  if (!moduleXml) {
    onLog?.(`还没有找到“${moduleName}”模块，请先用上方按钮封装当前工作区。`);
    return;
  }

  const moduleWorkspace = new ScratchBlocks.Workspace();
  try {
    ScratchBlocks.Xml.domToWorkspace(ScratchBlocks.utils.xml.textToDom(moduleXml), moduleWorkspace);
    onLog?.(`调用模块：${moduleName}`);
    await runWorkspace(moduleWorkspace, services, onLog);
  } finally {
    moduleWorkspace.dispose();
  }
}

async function readNumberInput(block, inputName, services, fallback) {
  const value = await readInputValue(block, inputName, services);
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

async function readBooleanInput(block, inputName, services, fallback) {
  const value = await readInputValue(block, inputName, services);
  return typeof value === 'boolean' ? value : fallback;
}

async function readInputValue(block, inputName, services) {
  const target = block.getInputTargetBlock(inputName);
  if (!target) return undefined;
  return readBlockValue(target, services);
}

async function readBlockValue(block, services) {
  if (!block) return undefined;
  if (block.type === 'math_number' || block.type === 'math_integer' || block.type === 'math_positive_number') {
    return Number(block.getFieldValue('NUM'));
  }
  if (block.type === 'text') {
    return block.getFieldValue('TEXT') || '';
  }
  if (block.type === blockTypes.battery) {
    return Math.round(services.droneBridge.getFrameMeta().battery);
  }
  if (block.type === blockTypes.altitude) {
    return Number(services.droneBridge.getFrameMeta().altitude.toFixed(1));
  }
  if (block.type === blockTypes.distance) {
    return Number(services.droneBridge.getFrameMeta().distance.toFixed(1));
  }
  if (block.type === blockTypes.yoloDetect) {
    const target = String(block.getFieldValue('TARGET') || await readInputValue(block, 'TARGET', services) || '人');
    const result = await services.vlmClient.detect(target, services.droneBridge.getFrameMeta());
    return result.found;
  }
  if (block.type === blockTypes.yoloCount) {
    const target = String(await readInputValue(block, 'TARGET', services) || '人');
    const result = await services.vlmClient.detect(target, services.droneBridge.getFrameMeta());
    return result.found ? 1 : 0;
  }
  if (block.type === blockTypes.yoloPosition) {
    const position = block.getFieldValue('POSITION') || '中';
    const meta = services.droneBridge.getFrameMeta();
    if (position === '左') return meta.lateral < -0.5;
    if (position === '右') return meta.lateral > 0.5;
    return Math.abs(meta.lateral) <= 0.5;
  }
  if (block.type === blockTypes.yoloNear) {
    const target = String(await readInputValue(block, 'TARGET', services) || '目标');
    const result = await services.vlmClient.detect(target, services.droneBridge.getFrameMeta());
    return result.found && services.droneBridge.getFrameMeta().distance < 2;
  }
  if (block.type === blockTypes.landingPadFound) {
    const result = await services.vlmClient.detect('降落垫', services.droneBridge.getFrameMeta());
    return result.found;
  }
  if (block.type === blockTypes.askVision) {
    const question = String(await readInputValue(block, 'QUESTION', services) || '');
    return services.vlmClient.describeFrame(question, services.droneBridge.getFrameMeta());
  }
  if (block.type === blockTypes.sceneSummary) {
    return services.vlmClient.describeFrame('画面里有什么？', services.droneBridge.getFrameMeta());
  }
  if (block.type === blockTypes.isSceneSafe) {
    const meta = services.droneBridge.getFrameMeta();
    return meta.battery > 18 && meta.altitude < 4 && Math.abs(meta.lateral) < 4;
  }
  if (block.type === blockTypes.canLand) {
    const meta = services.droneBridge.getFrameMeta();
    return meta.altitude <= 1.6 && /起降垫|降落垫/.test(meta.target);
  }
  if (block.type === blockTypes.taskDone) {
    const task = String(await readInputValue(block, 'TASK', services) || '');
    const meta = services.droneBridge.getFrameMeta();
    return task.includes(meta.target) || (/降落垫/.test(task) && /起降垫|降落垫/.test(meta.target));
  }
  if (block.type === blockTypes.chooseAction) {
    const meta = services.droneBridge.getFrameMeta();
    if (meta.battery < 25) return '返航';
    if (meta.altitude > 3.5) return '降落';
    if (meta.distance < 1) return '向前';
    return actionChoices[Math.abs(Math.round(meta.yaw / 90)) % actionChoices.length];
  }
  if (block.type === blockTypes.chat) {
    const text = String(await readInputValue(block, 'TEXT', services) || '');
    return services.vlmClient.chat(text);
  }
  if (block.type === blockTypes.createImage) {
    const prompt = String(await readInputValue(block, 'PROMPT', services) || '');
    return services.sdClient.createImage(prompt);
  }
  if (block.type === blockTypes.createFromFrame || block.type === blockTypes.transformFrame) {
    const style = block.getFieldValue('STYLE') || '卡通';
    const meta = services.droneBridge.getFrameMeta();
    return services.sdClient.createImage(`${meta.scene}，${style}风格`);
  }
  return undefined;
}

function isEventHat(type) {
  return [
    blockTypes.whenRun,
    blockTypes.whenDetected,
    blockTypes.whenBatteryLow,
    blockTypes.whenDistanceLess,
    blockTypes.whenHeard,
    blockTypes.whenTaskDone
  ].includes(type);
}

function blockLabel(block) {
  const match = flightBlocks.find(([type]) => type === block.type);
  if (match) return match[1];
  const labels = {
    [blockTypes.turn]: '转向',
    [blockTypes.yoloDetect]: 'YOLO 识别',
    [blockTypes.askVision]: '询问画面',
    [blockTypes.chat]: '问小助手',
    [blockTypes.createImage]: '创建图片',
    [blockTypes.battery]: '电量',
    [blockTypes.altitude]: '高度',
    [blockTypes.distance]: '距离',
    [blockTypes.hover]: '悬停',
    [blockTypes.land]: '降落',
    [blockTypes.returnHome]: '返航',
    [blockTypes.stopFlight]: '停止飞行',
    [blockTypes.yoloCount]: '目标数量',
    [blockTypes.yoloPosition]: '目标位置',
    [blockTypes.yoloNear]: '目标靠近',
    [blockTypes.followTarget]: '跟随目标',
    [blockTypes.avoidTarget]: '避开目标',
    [blockTypes.landingPadFound]: '找到降落垫',
    [blockTypes.sceneSummary]: '画面里有什么',
    [blockTypes.isSceneSafe]: '前方安全吗',
    [blockTypes.canLand]: '适合降落吗',
    [blockTypes.taskDone]: '任务完成了吗',
    [blockTypes.chooseAction]: '根据画面选择动作',
    [blockTypes.createFromFrame]: '当前画面生成图',
    [blockTypes.transformFrame]: '画面风格转换',
    [blockTypes.saveImage]: '保存生成图片',
    [blockTypes.showImage]: '显示生成图片',
    [blockTypes.whenRun]: '当点击运行',
    [blockTypes.whenDetected]: '当识别到目标',
    [blockTypes.whenBatteryLow]: '当电量低',
    [blockTypes.whenDistanceLess]: '当距离小于',
    [blockTypes.whenHeard]: '当听到指令',
    [blockTypes.whenTaskDone]: '当任务完成',
    [blockTypes.safetyBatteryReturn]: '电量低自动返航',
    [blockTypes.safetyTooCloseStop]: '距离太近停止',
    [blockTypes.safetyUnsafeHover]: '画面不安全悬停',
    [blockTypes.setMaxAltitude]: '设置最大高度',
    [blockTypes.setMaxSpeed]: '设置最大速度',
    [blockTypes.emergencyStop]: '紧急停止',
    [blockTypes.protectMode]: '保护模式',
    [blockTypes.moduleCall]: '调用模块'
  };
  return labels[block.type] || block.type;
}

function escapeXml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export default ScratchBlocksEditor;
