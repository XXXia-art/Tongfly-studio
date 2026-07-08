import React, {useState} from 'react';

const createMessageId = () => {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `message-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

export default function VlmChat({bridge, vlmClient, sdClient, captureFrame}) {
  const [text, setText] = useState('');
  const [activeSkill, setActiveSkill] = useState(null);
  const [isSkillMenuOpen, setIsSkillMenuOpen] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [messages, setMessages] = useState([
    {role: 'assistant', text: '你好，我是无人机小助手。只有点击「看画面」或运行图像理解积木时，我才会读取图传。'}
  ]);

  const addMessage = message => setMessages(current => [...current, message]);
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
        updateMessage(pendingId, {text: await vlmClient.chat(`创建图片：${value}`), loading: false});
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

  const chooseVisionSkill = () => {
    setIsSkillMenuOpen(false);
    askVision();
  };

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
        <div className="chat-composer">
          <div className="skill-menu-wrap">
            <button
              className={`skill-toggle ${activeSkill === 'image' || isSkillMenuOpen ? 'active' : ''}`}
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
                <button type="button" onClick={chooseVisionSkill} role="menuitem">
                  看画面
                </button>
              </div>
            )}
          </div>
          {activeSkill === 'image' && (
            <span className="skill-chip">
              <span>创建图片</span>
              <button type="button" onClick={() => setActiveSkill(null)} aria-label="取消创建图片">×</button>
            </span>
          )}
          <input
            value={text}
            onChange={event => setText(event.target.value)}
            disabled={isThinking}
            placeholder={activeSkill === 'image' ? '描述你想生成的图片' : '问小助手，或选择技能'}
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
      </form>
    </section>
  );
}
