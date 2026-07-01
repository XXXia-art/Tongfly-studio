import React, {useState} from 'react';

export default function VlmChat({bridge, vlmClient, sdClient, captureFrame}) {
  const [text, setText] = useState('');
  const [activeSkill, setActiveSkill] = useState(null);
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
  const buildSdPrompt = async value => {
    const instruction = [
      '请把下面的中文图片描述改写成适合 Stable Diffusion v1.5 的英文提示词。',
      '要求：只返回英文提示词，不要解释，不要 Markdown，不要中文。',
      '风格适合少儿无人机编程软件：清晰、明亮、友好、构图干净。',
      `中文描述：${value}`
    ].join('\n');
    const translated = await vlmClient.chat(instruction);
    return translated
      .replace(/^["'`]+|["'`]+$/g, '')
      .replace(/^English prompt:\s*/i, '')
      .trim() || value;
  };

  const send = async event => {
    event.preventDefault();
    const value = text.trim();
    if (!value || isThinking) return;
    const pendingId = crypto.randomUUID();
    setText('');
    if (activeSkill === 'image') {
      setActiveSkill(null);
      addMessage({role: 'user', text: value, skill: '创建图片'});
      addMessage({id: pendingId, role: 'assistant', text: '正在理解描述并生成图片', loading: true});
      setIsThinking(true);
      try {
        const sdPrompt = await buildSdPrompt(value);
        const image = await sdClient.createImage(sdPrompt);
        updateMessage(pendingId, {text: `已生成图片：${value}`, image, loading: false});
      } catch (error) {
        updateMessage(pendingId, {text: `图片生成失败：${error.message}`, error: true, loading: false});
      } finally {
        setIsThinking(false);
      }
      return;
    }

    addMessage({role: 'user', text: value});
    addMessage({id: pendingId, role: 'assistant', text: '正在思考', loading: true});
    setIsThinking(true);
    try {
      updateMessage(pendingId, {text: await vlmClient.chat(value), loading: false});
    } catch (error) {
      updateMessage(pendingId, {text: `回答失败：${error.message}`, error: true, loading: false});
    } finally {
      setIsThinking(false);
    }
  };

  const askVision = async () => {
    if (isThinking) return;
    const question = text.trim() || '请帮我看一下当前画面';
    const pendingId = crypto.randomUUID();
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
          <button
            className={`skill-toggle ${activeSkill === 'image' ? 'active' : ''}`}
            type="button"
            onClick={() => setActiveSkill(activeSkill === 'image' ? null : 'image')}
            disabled={isThinking}
            aria-label="创建图片"
            title="创建图片"
          >
            +
          </button>
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
          <button className="vision-button" type="button" onClick={askVision} disabled={isThinking}>看画面</button>
          <button className="send-button" type="submit" disabled={isThinking || !text.trim()} aria-label="发送">↑</button>
        </div>
      </form>
    </section>
  );
}
