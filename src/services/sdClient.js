class SDClientMock {
  async createImage(prompt) {
    await wait(500);
    if (typeof document === 'undefined') {
      return `mock://sd-image/${encodeURIComponent(prompt || 'drone')}`;
    }
    return createMockImage(prompt || '无人机看到的天空');
  }
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function createMockImage(prompt) {
  const canvas = document.createElement('canvas');
  canvas.width = 640;
  canvas.height = 400;
  const ctx = canvas.getContext('2d');
  const hash = Array.from(prompt).reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const sky = ctx.createLinearGradient(0, 0, 0, canvas.height);
  sky.addColorStop(0, `hsl(${190 + hash % 70}, 72%, 74%)`);
  sky.addColorStop(0.55, '#f8d894');
  sky.addColorStop(1, '#5d9b76');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'rgba(255,255,255,0.82)';
  for (let i = 0; i < 7; i += 1) {
    const x = (i * 94 + hash) % 680 - 40;
    const y = 34 + (i * 31 + hash) % 110;
    drawCloud(ctx, x, y, 42 + (hash + i * 9) % 34);
  }
  ctx.fillStyle = '#2f7fd2';
  ctx.strokeStyle = '#20313e';
  ctx.lineWidth = 7;
  ctx.beginPath();
  ctx.arc(330, 170, 42, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.strokeStyle = '#20313e';
  ctx.lineWidth = 8;
  ctx.beginPath();
  ctx.moveTo(245, 170);
  ctx.lineTo(415, 170);
  ctx.moveTo(330, 120);
  ctx.lineTo(330, 220);
  ctx.stroke();
  ctx.fillStyle = '#fffaf0';
  ctx.fillRect(28, 318, 584, 46);
  ctx.fillStyle = '#22313f';
  ctx.font = '700 22px Microsoft YaHei, sans-serif';
  ctx.fillText(prompt.slice(0, 22), 48, 348);
  return canvas.toDataURL('image/png');
}

function drawCloud(ctx, x, y, size) {
  ctx.beginPath();
  ctx.arc(x, y, size * 0.35, 0, Math.PI * 2);
  ctx.arc(x + size * 0.32, y - size * 0.2, size * 0.42, 0, Math.PI * 2);
  ctx.arc(x + size * 0.74, y, size * 0.33, 0, Math.PI * 2);
  ctx.rect(x, y - size * 0.04, size * 0.78, size * 0.32);
  ctx.fill();
}

export const sdClient = new SDClientMock();
export {SDClientMock};
