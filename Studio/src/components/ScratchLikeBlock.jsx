import React from 'react';

export default function ScratchLikeBlock({block}) {
  const text = block.text || block.id;
  const isControl = block.shape === 'control' || block.kind === 'loop';
  const color = block.color || (isControl ? '#FFAB19' : '#4C97FF');
  const className = ['scratch-block', isControl ? 'control-block' : '', block.kind ? `scratch-${block.kind}` : '']
    .filter(Boolean)
    .join(' ');

  return (
    <div
      className={className}
      data-block-kind={block.kind || 'command'}
      style={{'--block-color': color}}
    >
      <span className="block-tab" aria-hidden="true" />
      <span className="block-bottom-tab" aria-hidden="true" />
      <span className="block-content">
        {block.icon && <span className="block-icon">{block.icon}</span>}
        {renderText(text)}
      </span>
      {isControl && (
        <>
          <span className="control-slot" aria-hidden="true" />
          <span className="control-return" aria-hidden="true">↩</span>
        </>
      )}
    </div>
  );
}

function renderText(text) {
  const parts = String(text).split(/(\[[^\]]+\])/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith('[') && part.endsWith(']')) {
      const value = part.slice(1, -1);
      return <span className="block-input" key={`${part}-${index}`}>{defaultValue(value)}</span>;
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function defaultValue(name) {
  const defaults = {
    speed: '1',
    seconds: '2',
    times: '10',
    target: '人',
    question: '前方有什么？',
    text: '怎样飞得更稳？',
    prompt: '天空',
    condition: '识别到目标'
  };
  return defaults[name] || name;
}
