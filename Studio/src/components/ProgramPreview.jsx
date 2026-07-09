import React, {useRef, useState} from 'react';
import {blockCatalog} from '../data/droneBlockCatalog.js';
import ScratchLikeBlock from './ScratchLikeBlock.jsx';

export default function ProgramPreview({program, onDropBlock, onMoveBlock}) {
  const canvasRef = useRef(null);
  const [draggingUid, setDraggingUid] = useState(null);
  const blocks = Object.values(blockCatalog).flatMap(group => group.blocks);

  const canvasPoint = event => {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left + canvas.scrollLeft,
      y: event.clientY - rect.top + canvas.scrollTop
    };
  };

  const handleDrop = event => {
    event.preventDefault();
    const payloadText = event.dataTransfer.getData('application/x-drone-block');
    if (!payloadText) return;
    const payload = JSON.parse(payloadText);
    if (payload.source !== 'palette') return;
    const point = canvasPoint(event);
    onDropBlock(payload.blockId, {
      x: Math.max(0, point.x - 24),
      y: Math.max(0, point.y - 22)
    });
  };

  const startBlockDrag = (event, step) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const origin = {x: event.clientX, y: event.clientY};
    const initial = {x: step.x || 0, y: step.y || 0};
    setDraggingUid(step.uid);
    event.currentTarget.setPointerCapture(event.pointerId);

    const move = moveEvent => {
      onMoveBlock(step.uid, {
        x: initial.x + moveEvent.clientX - origin.x,
        y: initial.y + moveEvent.clientY - origin.y
      });
    };

    const end = () => {
      setDraggingUid(null);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
  };

  return (
    <div
      className="program-canvas"
      ref={canvasRef}
      onDragOver={event => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
      }}
      onDrop={handleDrop}
    >
      {program.map((step, index) => {
        const definition = blocks.find(block => block.id === step.id) || {id: step.id, text: step.id};
        return (
          <div
            className={draggingUid === step.uid ? 'program-step dragging' : 'program-step'}
            key={step.uid || `${step.id}-${index}`}
            onPointerDown={event => startBlockDrag(event, step)}
            style={{
              left: `${step.x || 0}px`,
              top: `${step.y || 0}px`,
              zIndex: draggingUid === step.uid ? 20 : index + 1
            }}
          >
            <ScratchLikeBlock block={{...definition, defaults: step.params}} />
          </div>
        );
      })}
      <div className="canvas-drop-hint">从左侧拖积木到这里，或拖动画布里的积木重新摆放。</div>
    </div>
  );
}
