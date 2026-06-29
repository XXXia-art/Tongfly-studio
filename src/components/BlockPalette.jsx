import React from 'react';
import ScratchLikeBlock from './ScratchLikeBlock.jsx';

export default function BlockPalette({blocks, category, onAddBlock}) {
  const startDrag = (event, block) => {
    event.dataTransfer.effectAllowed = 'copy';
    event.dataTransfer.setData('application/x-drone-block', JSON.stringify({
      source: 'palette',
      blockId: block.id
    }));
  };

  return (
    <aside className="block-palette">
      <div className="palette-heading">
        <h2>{category.label}</h2>
        <span>拖到画布</span>
      </div>
      {category.note && <p className="palette-note">{category.note}</p>}
      <div className="palette-list">
        {blocks.map(block => (
          <button
            className="palette-button"
            key={block.id}
            draggable
            onClick={() => onAddBlock(block)}
            onDragStart={event => startDrag(event, block)}
            type="button"
          >
            <ScratchLikeBlock block={block} />
          </button>
        ))}
      </div>
    </aside>
  );
}
