import React, {useState} from 'react';

export default function VlmChat({bridge, vlmClient, sdClient, captureFrame}) {
  const [text, setText] = useState('');
  const [messages, setMessages] = useState([
    {role: 'assistant', text: '你好，我是无人机小助手。只有点击「看画面」或运行图像理解积木时，我才会读取图传。'}
  ]);

  const addMessage = message => setMessages(current => [...current, message]);

  const send = async event => {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    setText('');
    addMessage({role: 'user', text: value});
    addMessage({role: 'assistant', text: await vlmClient.chat(value)});
  };

  const askVision = async () => {
    const question = text.trim() || '请帮我看一下当前画面';
    addMessage({role: 'user', text: `看画面：${question}`});
    const imageBase64 = captureFrame ? captureFrame() : null;
    addMessage({
      role: 'assistant',
      text: await vlmClient.describeFrame(question, bridge.getFrameMeta(), imageBase64)
    });
  };

  const createImage = async () => {
    const prompt = text.trim() || '儿童画风的无人机飞过操场';
    addMessage({role: 'user', text: `创建图片：${prompt}`});
    addMessage({role: 'assistant', text: `已生成图片：${prompt}`, image: await sdClient.createImage(prompt)});
  };

  return (
    <section className="vlm-chat">
      <header>
        <h2>无人机小助手</h2>
      </header>
      <div className="chat-feed">
        {messages.map((message, index) => (
          <div className={`message ${message.role}`} key={`${message.text}-${index}`}>
            <span>{message.text}</span>
            {message.image && <img src={message.image} alt="生成图" />}
          </div>
        ))}
      </div>
      <form className="chat-form" onSubmit={send}>
        <input
          value={text}
          onChange={event => setText(event.target.value)}
          placeholder="问小助手，或输入图片提示词"
        />
        <button type="button" onClick={askVision}>看画面</button>
        <button type="button" onClick={createImage}>创建图片</button>
        <button type="submit">发送</button>
      </form>
    </section>
  );
}
