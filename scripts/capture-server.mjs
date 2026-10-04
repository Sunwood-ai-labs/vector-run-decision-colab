#!/usr/bin/env node
import { createServer } from 'node:http';
import { createReadStream } from 'node:fs';
import { realpath, stat } from 'node:fs/promises';
import { resolve, sep, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const args = process.argv.slice(2);
if (args.includes('--help')) {
  console.log('node scripts/capture-server.mjs [--port 8787] [--root .]\nServes comparison.html on http://127.0.0.1:8787/ (loopback only).');
  process.exit(0);
}
const options = {};
for (let i = 0; i < args.length; i += 2) {
  if (!['--port', '--root'].includes(args[i]) || !args[i + 1]) throw new Error(`Unknown or missing option: ${args[i]}`);
  options[args[i].slice(2)] = args[i + 1];
}
const root = await realpath(resolve(options.root || fileURLToPath(new URL('../', import.meta.url))));
const port = Number(options.port || 8787);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Port must be 1..65535.');
const mime = new Map([
  ['.html', 'text/html; charset=utf-8'], ['.js', 'text/javascript; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'], ['.css', 'text/css; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'], ['.png', 'image/png'], ['.jpg', 'image/jpeg'],
  ['.svg', 'image/svg+xml'], ['.webp', 'image/webp'], ['.mp4', 'video/mp4'], ['.webm', 'video/webm'],
]);
const insideRoot = path => path === root || path.startsWith(`${root}${sep}`);
const server = createServer(async (request, response) => {
  if (!['GET', 'HEAD'].includes(request.method)) {
    response.writeHead(405, { Allow: 'GET, HEAD' }).end();
    return;
  }
  try {
    let pathname = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname);
    if (pathname === '/') pathname = '/comparison.html';
    const candidate = resolve(root, `.${pathname}`);
    if (!insideRoot(candidate)) {
      response.writeHead(403).end('Forbidden');
      return;
    }
    const path = await realpath(candidate);
    if (!insideRoot(path)) {
      response.writeHead(403).end('Forbidden');
      return;
    }
    const info = await stat(path);
    if (!info.isFile()) {
      response.writeHead(404).end('Not found');
      return;
    }
    response.writeHead(200, {
      'Content-Type': mime.get(extname(path).toLowerCase()) || 'application/octet-stream',
      'Content-Length': info.size,
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    });
    if (request.method === 'HEAD') response.end();
    else createReadStream(path).on('error', () => response.destroy()).pipe(response);
  } catch (error) {
    const code = error.code === 'ENOENT' || error.code === 'ENOTDIR' ? 404 : error instanceof URIError ? 400 : 500;
    response.writeHead(code).end(code === 404 ? 'Not found' : 'Request failed');
  }
});
server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ url: `http://127.0.0.1:${port}/comparison.html`, root })));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit(0)));
