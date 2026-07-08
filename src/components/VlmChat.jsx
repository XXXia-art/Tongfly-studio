import React, {useEffect, useRef, useState} from 'react';

const createMessageId = () => {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `message-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

const outputSkillLabel = message => {
  if (message.type === 'vlm_vision_result') return '查看画面';
  if (message.type === 'vlm_chat_result') return '普通对话';
  return message.describe || '模型回复';
};

const skillLabels = {
  image: '创建图片',
  flight: '掌控飞行',
  vision: '查看画面',
  chat: '普通对话'
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
        skill: outputSkillLabel(message),
        text: outputText(message)
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
    if (!activeSkill) {
      addMessage({role: 'user', text: value});
      addMessage({id: pendingId, role: 'assistant', text: '请先从 + 选择需要使用的技能。', loading: false});
      return;
    }

    if (activeSkill === 'image' || activeSkill === 'flight') {
      setActiveSkill(null);
      addMessage({role: 'user', text: value, skill: skillLabels[activeSkill]});
      addMessage({id: pendingId, role: 'assistant', text: '当前模式不需要发送内容数据包。', loading: false});
      return;
    }

    if (activeSkill === 'vision') {
      setActiveSkill(null);
      addMessage({role: 'user', text: value, skill: '查看画面'});
      addMessage({id: pendingId, role: 'assistant', text: '正在发送查看画面内容', loading: true});
      setIsThinking(true);
      try {
        const imageBase64 = captureFrame ? captureFrame() : null;
        updateMessage(pendingId, {
          text: await vlmClient.describeFrame(value, bridge.getFrameMeta(), imageBase64),
          loading: false
        });
      } catch (error) {
        updateMessage(pendingId, {text: `图像理解失败：${error.message}`, error: true, loading: false});
      } finally {
        setIsThinking(false);
      }
      return;
    }

    setActiveSkill(null);
    addMessage({role: 'user', text: value, skill: '普通对话'});
    addMessage({id: pendingId, role: 'assistant', text: '正在发送到总控状态机', loading: true});
    setIsThinking(true);
    try {
      updateMessage(pendingId, {
        text: await vlmClient.chat(value, {mode: 7, describe: '普通对话'}),
        loading: false
      });
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
    onModeAction?.({mode: 4, describe: '创建图片'});
  };

  const chooseFlightSkill = () => {
    setActiveSkill('flight');
    setIsSkillMenuOpen(false);
    onModeAction?.({mode: 2, describe: '掌控飞行'});
  };

  const chooseVisionSkill = () => {
    setActiveSkill('vision');
    setIsSkillMenuOpen(false);
    onModeAction?.({mode: 6, describe: '查看画面'});
  };

  const chooseChatSkill = () => {
    setActiveSkill('chat');
    setIsSkillMenuOpen(false);
    onModeAction?.({mode: 7, describe: '普通对话'});
  };

  const startVoiceMode = () => {
    setIsSkillMenuOpen(false);
    if (activeSkill === 'image') {
      onModeAction?.({mode: 4, describe: '创建图片'});
      return;
    }
    if (activeSkill === 'flight') {
      onModeAction?.({mode: 2, describe: '掌控飞行'});
      return;
    }
    onModeAction?.({mode: 2, describe: '掌控飞行'});
  };

  const voiceTitle = activeSkill === 'image'
    ? '创建图片'
    : activeSkill === 'flight'
      ? '掌控飞行'
      : '掌控飞行';

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
                  <button type="button" onClick={chooseChatSkill} role="menuitem">
                    普通对话
                  </button>
                </div>
              )}
            </div>
            {activeSkill && (
              <span className="skill-chip">
                <span>{skillLabels[activeSkill]}</span>
                <button type="button" onClick={() => setActiveSkill(null)} aria-label="取消技能">×</button>
              </span>
            )}
            <input
              value={text}
              onChange={event => setText(event.target.value)}
              disabled={isThinking}
              placeholder={
                activeSkill === 'vision'
                  ? '输入想让 VLM 查看画面时回答的问题'
                  : activeSkill === 'chat'
                    ? '输入要和 VLM 对话的内容'
                    : activeSkill === 'image' || activeSkill === 'flight'
                      ? '该模式已发送，不需要发送内容'
                      : '请先从 + 选择技能'
              }
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

function outputText(message) {
  const text = message.text || message.answer || JSON.stringify(message);
  if (message.type === 'vlm_vision_result' && message.image_path) {
    return `${text}\n图片路径：${message.image_path}`;
  }
  return text;
}
