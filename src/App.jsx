import React, {useMemo, useRef, useState} from 'react';
import {droneBridge} from './services/droneBridge.js';
import {vlmClient} from './services/vlmClient.js';
import {sdClient} from './services/sdClient.js';
import DroneStage from './components/DroneStage.jsx';
import VlmChat from './components/VlmChat.jsx';
import ScratchBlocksEditor from './components/ScratchBlocksEditor.jsx';

export default function App() {
  const [moduleName, setModuleName] = useState('阶梯式飞行');
  const [lastMission, setLastMission] = useState(null);
  const [logs, setLogs] = useState([]);
  const blocksEditorRef = useRef(null);
  const droneStageRef = useRef(null);
  const services = useMemo(() => ({droneBridge, vlmClient, sdClient}), []);

  const captureFrame = () => droneStageRef.current?.captureFrame();

  const addLog = text => {
    console.info(text);
    setLogs(current => [...current.slice(-7), text]);
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
    const compiledMission = blocksEditorRef.current?.getMissionFile();
    if (compiledMission?.programs?.length) {
      setLastMission(compiledMission);
    }
    try {
      const missionFile = await blocksEditorRef.current?.runProgram();
      if (missionFile) setLastMission(missionFile);
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
        <div className="status-pill">图传模拟中</div>
        <div className="status-pill">VLM 待命</div>
        <div className="status-pill">SD 待命</div>
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
          <section className="compile-panel">
            <header>
              <h2>Flight JSON</h2>
              <span>{lastMission ? lastMission.id : 'waiting'}</span>
            </header>
            <pre>{lastMission
              ? JSON.stringify(lastMission.flightActions || [], null, 2)
              : 'Click Run to compile blocks into flightActions.'}</pre>
            <div className="compile-log">
              {logs.map((log, index) => <span key={`${log}-${index}`}>{log}</span>)}
            </div>
          </section>
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
