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
      const horizon = h * 0.52 + Math.sin(t * 0.8) * 8 - drone.altitude * 6;

      const sky = ctx.createLinearGradient(0, 0, 0, h);
      sky.addColorStop(0, '#8ec7dc');
      sky.addColorStop(0.58, '#d9e4c4');
      sky.addColorStop(1, '#6ca46c');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);

      ctx.fillStyle = '#75a96b';
      ctx.fillRect(0, horizon, w, h - horizon);
      ctx.strokeStyle = 'rgba(255,255,255,0.55)';
      ctx.lineWidth = 5;
      ctx.beginPath();
      ctx.moveTo(w * 0.34 + drone.lateral * 8, horizon);
      ctx.lineTo(w * 0.22, h);
      ctx.moveTo(w * 0.66 + drone.lateral * 8, horizon);
      ctx.lineTo(w * 0.78, h);
      ctx.stroke();

      ctx.strokeStyle = '#4c97ff';
      ctx.lineWidth = 9;
      ctx.beginPath();
      ctx.ellipse(w * 0.5 - drone.lateral * 12, horizon + 98 - drone.altitude * 3, 74, 28, 0, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = 'rgba(25, 38, 48, 0.52)';
      ctx.fillRect(16, 16, 182, 34);
      ctx.fillStyle = '#fff';
      ctx.font = '700 18px Microsoft YaHei, sans-serif';
      ctx.fillText('DRONE-CAM MOCK', 30, 39);
      frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [drone]);

  return (
    <section className="drone-stage">
      <header>
        <h2>无人机图传</h2>
        <span>DroneBridge mock</span>
      </header>
      <canvas ref={canvasRef} width="680" height="340" />
      <div className="hud">
        <strong>高度 {drone.altitude.toFixed(1)} m</strong>
        <strong>距离 {drone.distance.toFixed(1)} m</strong>
        <strong>航向 {Math.round(drone.yaw)}°</strong>
        <strong>目标 {drone.target}</strong>
      </div>
    </section>
  );
});

export default DroneStage;
