import React, {useEffect, useImperativeHandle, useRef, useState} from 'react';

const DroneStage = React.forwardRef(function DroneStage({bridge}, ref) {
  const canvasRef = useRef(null);
  const [drone, setDrone] = useState(bridge.getState());

  useEffect(() => bridge.subscribe(setDrone), [bridge]);

  useImperativeHandle(ref, () => ({
    captureFrame() {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      return canvas.toDataURL('image/png');
    }
  }));

  useEffect(() => {
    let frame;
    const draw = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const w = canvas.width;
      const h = canvas.height;
      const t = performance.now() / 1000;
      const glowX = w * 0.52 + Math.sin(t * 0.35) * 18;
      const glowY = h * 0.42 + Math.cos(t * 0.28) * 10;

      const backdrop = ctx.createLinearGradient(0, 0, w, h);
      backdrop.addColorStop(0, '#f7efe3');
      backdrop.addColorStop(0.42, '#d9ece8');
      backdrop.addColorStop(1, '#b8d0ed');
      ctx.fillStyle = backdrop;
      ctx.fillRect(0, 0, w, h);

      const framePad = 26;
      const frameW = w - framePad * 2;
      const frameH = h - framePad * 2;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.68)';
      ctx.fillRect(framePad, framePad, frameW, frameH);
      ctx.strokeStyle = 'rgba(52, 88, 69, 0.24)';
      ctx.lineWidth = 2;
      ctx.strokeRect(framePad + 1, framePad + 1, frameW - 2, frameH - 2);

      const glow = ctx.createRadialGradient(glowX, glowY, 12, glowX, glowY, 178);
      glow.addColorStop(0, 'rgba(255, 204, 51, 0.56)');
      glow.addColorStop(0.45, 'rgba(15, 140, 115, 0.22)');
      glow.addColorStop(1, 'rgba(76, 151, 255, 0)');
      ctx.fillStyle = glow;
      ctx.fillRect(framePad, framePad, frameW, frameH);

      ctx.strokeStyle = 'rgba(76, 151, 255, 0.42)';
      ctx.lineWidth = 3;
      for (let i = 0; i < 6; i += 1) {
        const x = framePad + 52 + i * 92;
        ctx.beginPath();
        ctx.moveTo(x, framePad + 24);
        ctx.lineTo(x + 90, framePad + frameH - 30);
        ctx.stroke();
      }

      ctx.fillStyle = 'rgba(25, 38, 48, 0.58)';
      ctx.fillRect(framePad + 18, framePad + 18, 172, 34);
      ctx.fillStyle = '#fff';
      ctx.font = '700 18px Microsoft YaHei, sans-serif';
      ctx.fillText('SD IMAGE PREVIEW', framePad + 32, framePad + 41);

      ctx.fillStyle = '#253542';
      ctx.font = '800 22px Microsoft YaHei, sans-serif';
      ctx.fillText('等待创意喷绘输出', framePad + 34, h - framePad - 48);
      ctx.fillStyle = 'rgba(37, 53, 66, 0.62)';
      ctx.font = '500 14px Microsoft YaHei, sans-serif';
      ctx.fillText('这里将显示总控返回的 SD 图片', framePad + 34, h - framePad - 24);
      frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [drone]);

  return (
    <section className="drone-stage">
      <header>
        <h2>SD 图片显示</h2>
        <span>Image preview</span>
      </header>
      <canvas ref={canvasRef} width="680" height="340" />
      <div className="hud">
        <strong>状态 待生成</strong>
        <strong>尺寸 预留</strong>
        <strong>来源 SD</strong>
        <strong>模式 创意喷绘</strong>
      </div>
    </section>
  );
});

export default DroneStage;
