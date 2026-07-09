import react from '@vitejs/plugin-react';
import {defineConfig} from 'vite';
import dgram from 'node:dgram';
import fs from 'node:fs';
import path from 'node:path';

const MODE_UDP_HOST = process.env.TONGFLY_MODE_UDP_HOST || '127.0.0.1';
const MODE_UDP_PORT = Number(process.env.TONGFLY_MODE_UDP_PORT || 9100);
const CONTENT_UDP_HOST = process.env.TONGFLY_CONTENT_UDP_HOST || '127.0.0.1';
const CONTENT_UDP_PORT = Number(process.env.TONGFLY_CONTENT_UDP_PORT || 9200);
const OUTPUT_UDP_HOST = process.env.TONGFLY_OUTPUT_UDP_HOST || '127.0.0.1';
const OUTPUT_UDP_PORT = Number(process.env.TONGFLY_OUTPUT_UDP_PORT || 9300);
const OUTPUT_IMAGE_ROOT = path.resolve(process.env.TONGFLY_OUTPUT_IMAGE_ROOT || '/home/elf');
const OUTPUT_CACHE_LIMIT = 80;

const MIME_TYPES = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.bmp': 'image/bmp'
};

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

function parseOutputMessage(buffer, remote, id) {
  const raw = buffer.toString('utf8');
  try {
    return {
      id,
      receivedAt: new Date().toISOString(),
      remote: `${remote.address}:${remote.port}`,
      ...JSON.parse(raw)
    };
  } catch (error) {
    return {
      id,
      type: 'raw_output',
      receivedAt: new Date().toISOString(),
      remote: `${remote.address}:${remote.port}`,
      payload: {text: raw},
      parseError: error.message
    };
  }
}

function isPathInsideRoot(filePath) {
  const resolved = path.resolve(filePath);
  const relative = path.relative(OUTPUT_IMAGE_ROOT, resolved);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function normalizeOutputMessage(message) {
  const imagePath = message?.image_path || message?.payload?.image_path;
  if (!imagePath || !isPathInsideRoot(imagePath)) {
    return message;
  }
  const imageUrl = `/bridge/output-image?path=${encodeURIComponent(path.resolve(imagePath))}`;
  if (message?.image_path) {
    return {
      ...message,
      image_url: imageUrl
    };
  }
  return {
    ...message,
    payload: {
      ...message.payload,
      image_url: imageUrl
    }
  };
}

function udpBridgePlugin() {
  const outputMessages = [];
  let outputId = 0;
  let outputSocket = null;

  return {
    name: 'tongfly-udp-bridge',
    configureServer(server) {
      outputSocket = dgram.createSocket('udp4');
      outputSocket.on('message', (buffer, remote) => {
        const message = normalizeOutputMessage(parseOutputMessage(buffer, remote, ++outputId));
        outputMessages.push(message);
        if (outputMessages.length > OUTPUT_CACHE_LIMIT) {
          outputMessages.splice(0, outputMessages.length - OUTPUT_CACHE_LIMIT);
        }
        server.config.logger.info(`[tongfly] output UDP ${message.type || 'unknown'} from ${message.remote}`);
      });
      outputSocket.on('error', error => {
        server.config.logger.error(`[tongfly] output UDP error: ${error.message}`);
      });
      outputSocket.bind(OUTPUT_UDP_PORT, OUTPUT_UDP_HOST, () => {
        server.config.logger.info(`[tongfly] output UDP listening on ${OUTPUT_UDP_HOST}:${OUTPUT_UDP_PORT}`);
      });
      server.httpServer?.once('close', () => {
        outputSocket?.close();
        outputSocket = null;
      });

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

      server.middlewares.use('/bridge/output', (req, res) => {
        if (req.method !== 'GET') {
          res.statusCode = 405;
          res.end('Method Not Allowed');
          return;
        }
        const url = new URL(req.url || '/', 'http://localhost');
        const since = Number(url.searchParams.get('since') || 0);
        const messages = outputMessages.filter(message => message.id > since);
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({
          ok: true,
          listening: `${OUTPUT_UDP_HOST}:${OUTPUT_UDP_PORT}`,
          imageRoot: OUTPUT_IMAGE_ROOT,
          latestId: outputId,
          messages
        }));
      });

      server.middlewares.use('/bridge/output-image', (req, res) => {
        if (req.method !== 'GET') {
          res.statusCode = 405;
          res.end('Method Not Allowed');
          return;
        }
        const url = new URL(req.url || '/', 'http://localhost');
        const filePath = url.searchParams.get('path') || '';
        const resolved = path.resolve(filePath);
        if (!filePath || !isPathInsideRoot(resolved)) {
          res.statusCode = 403;
          res.end('Forbidden');
          return;
        }
        fs.stat(resolved, (statError, stat) => {
          if (statError || !stat.isFile()) {
            res.statusCode = 404;
            res.end('Not Found');
            return;
          }
          res.setHeader('Content-Type', MIME_TYPES[path.extname(resolved).toLowerCase()] || 'application/octet-stream');
          fs.createReadStream(resolved).pipe(res);
        });
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
