import React, {useEffect, useMemo, useRef, useState} from 'react';
import {droneBridge} from './services/droneBridge.js';
import {vlmClient} from './services/vlmClient.js';
import {sdClient} from './services/sdClient.js';
import DroneStage from './components/DroneStage.jsx';
import VlmChat from './components/VlmChat.jsx';
import ScratchBlocksEditor from './components/ScratchBlocksEditor.jsx';
import {sendMode} from './services/controlBus.js';
import {readOutput} from './services/outputBus.js';

const vlmOutputTypes = new Set([
  'vlm_chat_result',
  'vlm_vision_result'
]);

const modeButtons = [
  {mode: 1, label: '编程积木', describe: '开始编程积木模型'},
  {mode: 3, label: '创意喷绘', describe: '开始创意喷绘模型'},
  {mode: 5, label: '手势识别', describe: '开始手势识别模型'}
];

export default function App() {
  const [moduleName, setModuleName] = useState('阶梯式飞行');
  const [activeMode, setActiveMode] = useState(modeButtons[0].mode);
  const [sdOutput, setSdOutput] = useState(null);
  const [vlmOutputs, setVlmOutputs] = useState([]);
  const blocksEditorRef = useRef(null);
  const droneStageRef = useRef(null);
  const outputIdRef = useRef(0);
  const services = useMemo(() => ({droneBridge, vlmClient, sdClient}), []);

  const captureFrame = () => droneStageRef.current?.captureFrame();

  const addLog = text => {
    console.info(text);
  };

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    const pollOutput = async () => {
      try {
        const result = await readOutput(outputIdRef.current);
        if (cancelled) return;
        outputIdRef.current = result.latestId || outputIdRef.current;
        for (const message of result.messages || []) {
          if (message.type === 'sd_result') {
            setSdOutput(message);
            setVlmOutputs(current => [...current.slice(-20), message]);
          } else if (vlmOutputTypes.has(message.type)) {
            setVlmOutputs(current => [...current.slice(-20), message]);
          }
        }
      } catch (error) {
        console.warn('read output failed', error);
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(pollOutput, 800);
        }
      }
    };

    pollOutput();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const saveModule = () => {
    const name = moduleName.trim() || '我的模块';
    const xml = blocksEditorRef.current?.getWorkspaceXml() || '';
    localStorage.setItem(`droneModule:${name}`, xml);
    blocksEditorRef.current?.refreshModules();
    addLog(`模块「${name}」已保存到本地。`);
  };

  const runPreview = async () => {
    addLog('开始运行 Scratch Blocks 工作区。');
    try {
      await blocksEditorRef.current?.runProgram();
    } catch (error) {
      addLog(`运行失败：${error.message}`);
    }
  };

  const chooseMode = async option => {
    setActiveMode(option.mode);
    try {
      const result = await sendMode({
        mode: option.mode,
        describe: option.describe
      });
      addLog(`模式 ${option.mode} 已发送到 ${result.udp?.target}`);
    } catch (error) {
      addLog(`模式发送失败：${error.message}`);
    }
  };

  const resetFlightControl = async () => {
    try {
      const result = await sendMode({
        mode: 0,
        describe: '重置飞控'
      });
      addLog(`重置飞控已发送到 ${result.udp?.target}`);
    } catch (error) {
      addLog(`重置飞控发送失败：${error.message}`);
    }
  };

  const sendModeAction = async ({mode = 2, describe = '掌控飞行'} = {}) => {
    setActiveMode(mode);
    try {
      const result = await sendMode({
        mode,
        describe
      });
      addLog(`${describe} 已发送到 ${result.udp?.target}`);
    } catch (error) {
      addLog(`语音控制发送失败：${error.message}`);
    }
  };

  return (
    <div className="scratch-app">
      <header className="scratch-topbar">
        <div className="brand">
          <img className="brand-mark" src="/brand/tongfei-workshop-icon.png" alt="童飞工坊" />
          <div>
            <strong>童飞工坊</strong>
            <span>Scratch GUI 迁移版</span>
          </div>
        </div>
        <nav className="mode-switcher" aria-label="功能模式">
          {modeButtons.map(option => (
            <button
              className={`mode-button ${activeMode === option.mode ? 'active' : ''}`}
              key={option.mode}
              type="button"
              onClick={() => chooseMode(option)}
            >
              {option.label}
            </button>
          ))}
        </nav>
        <button className="reset-control-button" type="button" onClick={resetFlightControl}>
          重置飞控
        </button>
      </header>

      <main className="scratch-layout">
        <section className="editor-stage scratch-blocks-stage">
          <div className="editor-toolbar">
            <div className="module-toolbar-group">
              <input
                value={moduleName}
                onChange={event => setModuleName(event.target.value)}
                aria-label="模块名称"
              />
              <button className="module-save-button" type="button" onClick={saveModule}>封装模块</button>
            </div>
            <button className="run-button editor-run-button" type="button" onClick={runPreview}>运行</button>
          </div>
          <ScratchBlocksEditor
            ref={blocksEditorRef}
            services={services}
            onLog={addLog}
          />
        </section>

        <aside className="right-panel">
          <DroneStage ref={droneStageRef} bridge={droneBridge} sdOutput={sdOutput} />
          <VlmChat
            bridge={droneBridge}
            vlmClient={vlmClient}
            sdClient={sdClient}
            captureFrame={captureFrame}
            outputMessages={vlmOutputs}
            onModeAction={sendModeAction}
          />
        </aside>
      </main>
    </div>
  );
}
