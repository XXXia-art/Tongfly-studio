import React, {useEffect, useRef, useState} from 'react';

const createMessageId = () => {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `message-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

export default function VlmChat({
  bridge,
  vlmClient,
  sdClient,
  captureFrame,
  outputMessages = [],
  onModeAction
}) {
  const [text, setText] = useState('');
  const [activeSkill, setActiveSkill] = useState(null);
  const [isSkillMenuOpen, setIsSkillMenuOpen] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const seenOutputIdsRef = useRef(new Set());
  const [messages, setMessages] = useState([
    {role: 'assistant', text: '你好，我是无人机小助手。可以选择技能后发送文字，或点击麦克风启动语音模式。'}
  ]);

  const addMessage = message => setMessages(current => [...current, message]);
  useEffect(() => {
    const incoming = outputMessages.filter(message => !seenOutputIdsRef.current.has(message.id));
    if (!incoming.length) return;
    incoming.forEach(message => seenOutputIdsRef.current.add(message.id));
    setMessages(current => [
      ...current,
      ...incoming.map(message => ({
        id: `output-${message.id}`,
        role: 'assistant',
        text: message.payload?.text || message.payload?.answer || JSON.stringify(message.payload ?? message)
      }))
    ]);
    setIsThinking(false);
  }, [outputMessages]);

  const updateMessage = (id, patch) => {
    setMessages(current => current.map(message => (
      message.id === id ? {...message, ...patch} : message
    )));
  };
  const send = async event => {
    event?.preventDefault?.();
    const value = text.trim();
    if (!value || isThinking) return;
    const pendingId = createMessageId();
    setText('');
    setIsSkillMenuOpen(false);
    if (activeSkill === 'image') {
      setActiveSkill(null);
      addMessage({role: 'user', text: value, skill: '创建图片'});
      addMessage({id: pendingId, role: 'assistant', text: '正在发送到总控状态机', loading: true});
      setIsThinking(true);
      try {
        updateMessage(pendingId, {text: await sdClient.createImage(value), loading: false});
      } catch (error) {
        updateMessage(pendingId, {text: `发送失败：${error.message}`, error: true, loading: false});
      } finally {
        setIsThinking(false);
      }
      return;
    }

    if (activeSkill === 'flight') {
      setActiveSkill(null);
      addMessage({role: 'user', text: value, skill: '掌控飞行'});
      addMessage({id: pendingId, role: 'assistant', text: '正在发送到总控状态机', loading: true});
      setIsThinking(true);
      try {
        updateMessage(pendingId, {text: await vlmClient.chat(`掌控飞行：${value}`), loading: false});
      } catch (error) {
        updateMessage(pendingId, {text: `发送失败：${error.message}`, error: true, loading: false});
      } finally {
        setIsThinking(false);
      }
      return;
    }

    addMessage({role: 'user', text: value});
    addMessage({id: pendingId, role: 'assistant', text: '正在发送到总控状态机', loading: true});
    setIsThinking(true);
    try {
      updateMessage(pendingId, {text: await vlmClient.chat(value), loading: false});
    } catch (error) {
      updateMessage(pendingId, {text: `发送失败：${error.message}`, error: true, loading: false});
    } finally {
      setIsThinking(false);
    }
  };

  const askVision = async () => {
    if (isThinking) return;
    const question = text.trim() || '请帮我看一下当前画面';
    const pendingId = createMessageId();
    setText('');
    addMessage({role: 'user', text: `看画面：${question}`});
    addMessage({id: pendingId, role: 'assistant', text: '正在看画面', loading: true});
    setIsThinking(true);
    try {
      const imageBase64 = captureFrame ? captureFrame() : null;
      updateMessage(pendingId, {
        text: await vlmClient.describeFrame(question, bridge.getFrameMeta(), imageBase64),
        loading: false
      });
    } catch (error) {
      updateMessage(pendingId, {text: `图像理解失败：${error.message}`, error: true, loading: false});
    } finally {
      setIsThinking(false);
    }
  };

  const chooseImageSkill = () => {
    setActiveSkill('image');
    setIsSkillMenuOpen(false);
  };

  const chooseFlightSkill = () => {
    setActiveSkill('flight');
    setIsSkillMenuOpen(false);
  };

  const chooseVisionSkill = () => {
    setIsSkillMenuOpen(false);
    onModeAction?.({mode: 5, describe: '查看画面'});
  };

  const startVoiceMode = () => {
    setIsSkillMenuOpen(false);
    if (activeSkill === 'image') {
      onModeAction?.({mode: 3, describe: '语音SD生成图片'});
      return;
    }
    if (activeSkill === 'flight') {
      onModeAction?.({mode: 2, describe: '语音掌控飞行'});
      return;
    }
    onModeAction?.({mode: 2, describe: '语音掌控飞行'});
  };

  const voiceTitle = activeSkill === 'image'
    ? '语音SD生成图片'
    : activeSkill === 'flight'
      ? '语音掌控飞行'
      : '语音掌控飞行';

  return (
    <section className="vlm-chat">
      <header>
        <h2>无人机小助手</h2>
      </header>
      <div className="chat-feed">
        {messages.map((message, index) => (
          <div
            className={`message ${message.role} ${message.error ? 'error' : ''}`}
            key={message.id || `${message.text}-${index}`}
          >
            {message.skill && <b className="message-skill">{message.skill}</b>}
            <span>{message.text}</span>
            {message.loading && <i className="thinking-dots" aria-label="模型推理中"><em /><em /><em /></i>}
            {message.image && <img src={message.image} alt="生成图" />}
          </div>
        ))}
      </div>
      <form className="chat-form" onSubmit={send}>
        <div className="chat-action-row">
          <div className="chat-composer">
            <div className="skill-menu-wrap">
              <button
                className={`skill-toggle ${activeSkill || isSkillMenuOpen ? 'active' : ''}`}
                type="button"
                onClick={() => setIsSkillMenuOpen(open => !open)}
                disabled={isThinking}
                aria-label="技能菜单"
                title="技能菜单"
                aria-expanded={isSkillMenuOpen}
              >
                +
              </button>
              {isSkillMenuOpen && (
                <div className="skill-menu" role="menu">
                  <button type="button" onClick={chooseImageSkill} role="menuitem">
                    创建图片
                  </button>
                  <button type="button" onClick={chooseFlightSkill} role="menuitem">
                    掌控飞行
                  </button>
                  <button type="button" onClick={chooseVisionSkill} role="menuitem">
                    查看画面
                  </button>
                </div>
              )}
            </div>
            {activeSkill && (
              <span className="skill-chip">
                <span>{activeSkill === 'image' ? '创建图片' : '掌控飞行'}</span>
                <button type="button" onClick={() => setActiveSkill(null)} aria-label="取消技能">×</button>
              </span>
            )}
            <input
              value={text}
              onChange={event => setText(event.target.value)}
              disabled={isThinking}
              placeholder={activeSkill === 'image' ? '描述你想生成的图片' : activeSkill === 'flight' ? '描述你想让无人机执行的动作' : '问小助手，或选择技能'}
            />
            <button
              className="send-button"
              type="button"
              onClick={() => send()}
              disabled={isThinking || !text.trim()}
              aria-label="发送"
            >
              ↑
            </button>
          </div>
          <button
            className={`voice-control-button ${activeSkill === 'image' || activeSkill === 'flight' ? 'active' : ''}`}
            type="button"
            onClick={startVoiceMode}
            aria-label={voiceTitle}
            title={voiceTitle}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 15c1.7 0 3-1.3 3-3V6c0-1.7-1.3-3-3-3S9 4.3 9 6v6c0 1.7 1.3 3 3 3Z" />
              <path d="M5 11.5a7 7 0 0 0 14 0" />
              <path d="M12 18.5V22" />
              <path d="M8 22h8" />
            </svg>
          </button>
        </div>
      </form>
    </section>
  );
}
