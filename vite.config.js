import react from '@vitejs/plugin-react';
import {defineConfig} from 'vite';
import dgram from 'node:dgram';

const MODE_UDP_HOST = process.env.TONGFLY_MODE_UDP_HOST || '127.0.0.1';
const MODE_UDP_PORT = Number(process.env.TONGFLY_MODE_UDP_PORT || 9100);
const CONTENT_UDP_HOST = process.env.TONGFLY_CONTENT_UDP_HOST || '127.0.0.1';
const CONTENT_UDP_PORT = Number(process.env.TONGFLY_CONTENT_UDP_PORT || 9200);

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

function sendUdp(payload, host, port) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(payload), 'utf8');
    const sock = dgram.createSocket('udp4');
    sock.send(data, port, host, error => {
      sock.close();
      if (error) {
        reject(error);
        return;
      }
      resolve({target: `${host}:${port}`, bytes: data.length});
    });
  });
}

function udpBridgePlugin() {
  return {
    name: 'tongfly-udp-bridge',
    configureServer(server) {
      server.middlewares.use('/bridge/mode', async (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405;
          res.end('Method Not Allowed');
          return;
        }
        try {
          const payload = await readJsonBody(req);
          const udp = await sendUdp(payload, MODE_UDP_HOST, MODE_UDP_PORT);
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ok: true, udp}));
        } catch (error) {
          res.statusCode = 502;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ok: false, error: error.message}));
        }
      });

      server.middlewares.use('/bridge/content', async (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405;
          res.end('Method Not Allowed');
          return;
        }
        try {
          const payload = await readJsonBody(req);
          const udp = await sendUdp(payload, CONTENT_UDP_HOST, CONTENT_UDP_PORT);
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ok: true, udp}));
        } catch (error) {
          res.statusCode = 502;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ok: false, error: error.message}));
        }
      });
    }
  };
}

export default defineConfig({
  plugins: [react(), udpBridgePlugin()],
  server: {
    port: 8610,
    strictPort: false
  }
});
