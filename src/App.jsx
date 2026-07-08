import React, {useMemo, useRef, useState} from 'react';
import {droneBridge} from './services/droneBridge.js';
import {vlmClient} from './services/vlmClient.js';
import {sdClient} from './services/sdClient.js';
import DroneStage from './components/DroneStage.jsx';
import VlmChat from './components/VlmChat.jsx';
import ScratchBlocksEditor from './components/ScratchBlocksEditor.jsx';

const modeButtons = ['编程积木', '语音控制', '创意喷绘', '手势控制'];

export default function App() {
  const [moduleName, setModuleName] = useState('阶梯式飞行');
  const [activeMode, setActiveMode] = useState(modeButtons[0]);
  const blocksEditorRef = useRef(null);
  const droneStageRef = useRef(null);
  const services = useMemo(() => ({droneBridge, vlmClient, sdClient}), []);

  const captureFrame = () => droneStageRef.current?.captureFrame();

  const addLog = text => {
    console.info(text);
  };

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
          {modeButtons.map(mode => (
            <button
              className={`mode-button ${activeMode === mode ? 'active' : ''}`}
              key={mode}
              type="button"
              onClick={() => setActiveMode(mode)}
            >
              {mode}
            </button>
          ))}
        </nav>
        <button className="run-button" onClick={runPreview}>运行</button>
      </header>

      <main className="scratch-layout">
        <section className="editor-stage scratch-blocks-stage">
          <div className="editor-toolbar">
            <div>
              <h1>我的飞行程序</h1>
              <p>官方 Scratch Blocks 工作区</p>
            </div>
            <input
              value={moduleName}
              onChange={event => setModuleName(event.target.value)}
              aria-label="模块名称"
            />
            <button type="button" onClick={saveModule}>封装模块</button>
          </div>
          <ScratchBlocksEditor
            ref={blocksEditorRef}
            services={services}
            onLog={addLog}
          />
        </section>

        <aside className="right-panel">
          <DroneStage ref={droneStageRef} bridge={droneBridge} />
          <VlmChat
            bridge={droneBridge}
            vlmClient={vlmClient}
            sdClient={sdClient}
            captureFrame={captureFrame}
          />
        </aside>
      </main>
    </div>
  );
}
