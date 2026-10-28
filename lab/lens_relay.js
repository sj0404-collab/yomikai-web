#!/usr/bin/env node
/**
 * Релей для ПРЯМОГО Google Lens — чтобы читалка распознавала без сайта.
 *
 * Зачем: в АПК Lens — это движок (приложение само отправляет кадр и забирает
 * текст). В обычной вкладке браузера так нельзя: Google не отдаёт
 * CORS-заголовки, и страница не имеет права прочитать ответ. Релей — это ваш
 * сервер, который делает запрос сам и возвращает странице готовый текст.
 *
 * КОНТРАКТ (на него рассчитана читалка, RULES.lensRelay):
 *   POST <адрес релея>
 *     Content-Type: multipart/form-data, поле encoded_image (image/jpeg)
 *   ответ: 200 и любой из вариантов
 *     {"lines": ["реплика 1", "реплика 2"]}
 *     {"text": "реплика 1\nреплика 2"}
 *     text/plain — по строке на реплику
 *   обязательные заголовки ответа, иначе браузер не даст его прочитать:
 *     Access-Control-Allow-Origin: *
 *     Access-Control-Allow-Headers: content-type
 *
 * Запуск:
 *   node lab/lens_relay.js --port 8787
 *   node lab/lens_relay.js --port 8787 --origin https://ваш-сайт
 *
 * Внутри — три режима:
 *   glens    (по умолчанию) — шлёт кадр в lens.google.com/v3/upload и разбирает
 *            ответ. Внимание: с «чистого» адреса Google отдаёт страницу
 *            «включите JavaScript» (проверено 28.10.2026), поэтому этот режим
 *            имеет смысл, если у вас не заблокирован доступ или вы передаёте
 *            свои cookie через --cookie.
 *   command  — вызов вашей программы: --cmd "python3 ocr.py" (кадр в stdin,
 *            текст в stdout). Так подключается что угодно: свой движок,
 *            headless-браузер, другая служба.
 *   echo     — для проверки связки: возвращает 3 строки-заглушки.
 */
'use strict';
const http = require('http');
const { spawn } = require('child_process');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 ? process.argv[i + 1] : def;
}
const PORT = Number(arg('port', 8787));
const ORIGIN = arg('origin', '*');
const ENGINE = arg('engine', 'glens');
const CMD = arg('cmd', '');
const COOKIE = arg('cookie', '');

const CORS = {
  'Access-Control-Allow-Origin': ORIGIN,
  'Access-Control-Allow-Headers': 'content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

/** Разбор multipart: возвращаем { name, filename, type, data } для каждого файла
 *  и поля encoded_image первым. Без внешних зависимостей: только Buffer. */
function parseMultipart(body, boundary) {
  const parts = [];
  const sep = Buffer.from('--' + boundary);
  let idx = body.indexOf(sep);
  while (idx >= 0) {
    const next = body.indexOf(sep, idx + sep.length);
    if (next < 0) break;
    const chunk = body.slice(idx + sep.length + 2, next - 2);
    const headEnd = chunk.indexOf('\r\n\r\n');
    if (headEnd > 0) {
      const head = chunk.slice(0, headEnd).toString('utf8');
      const data = chunk.slice(headEnd + 4);
      const name = (head.match(/name="([^"]+)"/) || [])[1] || '';
      const filename = (head.match(/filename="([^"]*)"/) || [])[1] || '';
      const type = (head.match(/Content-Type:\s*([^\r\n]+)/i) || [])[1] || '';
      parts.push({ name, filename, type, data });
    }
    idx = next;
  }
  return parts;
}

/** Разбор ответа Google: текст лежит в AF_initDataCallback; берём строки, в
 *  которых буквы преобладают над прочим — это и есть реплики страницы. */
function textFromHtml(html) {
  const best = [];
  for (const chunk of String(html).split('AF_initDataCallback')) {
    const strs = [...chunk.matchAll(/"([^"\\]{2,160})"/g)].map(m => m[1]);
    const cyr = strs.filter(t => {
      const letters = (t.match(/\p{L}/gu) || []).length;
      return letters >= 3 && letters / t.length > 0.55;
    });
    if (cyr.length > best.length) best.splice(0, best.length, ...cyr);
  }
  return best.map(t => t.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16))));
}

async function glens(image) {
  const boundary = '----KomaRelay' + Math.random().toString(16).slice(2);
  const head = Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="encoded_image"; filename="page.jpg"\r\n`
    + `Content-Type: image/jpeg\r\n\r\n`);
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
  const res = await fetch('https://lens.google.com/v3/upload?hl=ru&ep=ccm', {
    method: 'POST',
    headers: {
      'Content-Type': `multipart/form-data; boundary=${boundary}`,
      'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/122 Mobile Safari/537.36',
      ...(COOKIE ? { Cookie: COOKIE } : {}),
    },
    body: Buffer.concat([head, image, tail]),
  });
  const html = await res.text();
  if (/enablejs/i.test(html) && !/AF_initDataCallback/.test(html)) {
    throw new Error('Google отдал страницу «включите JavaScript» — с этого адреса прямой запрос '
      + 'блокируется. Используйте --cmd со своим движком/headless-браузером.');
  }
  const lines = textFromHtml(html);
  if (!lines.length) throw new Error('в ответе Lens не нашлось текста');
  return lines;
}

function runCommand(image) {
  return new Promise((resolve, reject) => {
    const p = spawn(CMD, { shell: true });
    const out = [];
    const err = [];
    p.stdout.on('data', d => out.push(d));
    p.stderr.on('data', d => err.push(d));
    p.on('error', reject);
    p.on('close', code => {
      if (code !== 0) return reject(new Error('команда вернула ' + code + ': ' + Buffer.concat(err).toString('utf8').slice(0, 300)));
      const text = Buffer.concat(out).toString('utf8');
      try {
        const j = JSON.parse(text);
        if (Array.isArray(j.lines)) return resolve(j.lines);
        if (j.text) return resolve(String(j.text).split(/\r?\n/).filter(Boolean));
      } catch (e) { /* не JSON — это обычный текст */ }
      resolve(text.split(/\r?\n/).map(s => s.trim()).filter(Boolean));
    });
    p.stdin.end(image);
  });
}

const server = http.createServer((req, res) => {
  if (req.method === 'OPTIONS') { res.writeHead(204, CORS); return res.end(); }
  if (req.method !== 'POST') {
    res.writeHead(405, { ...CORS, 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ error: 'только POST' }));
  }
  const chunks = [];
  req.on('data', c => chunks.push(c));
  req.on('end', async () => {
    try {
      const body = Buffer.concat(chunks);
      const boundary = (String(req.headers['content-type'] || '').match(/boundary=(.+)$/) || [])[1];
      if (!boundary) throw new Error('нужен multipart/form-data с полем encoded_image');
      const parts = parseMultipart(body, boundary.trim());
      const img = parts.find(p => p.name === 'encoded_image') || parts.find(p => p.data && p.data.length > 1000);
      if (!img || !img.data || !img.data.length) throw new Error('картинки в запросе нет');
      let lines;
      if (ENGINE === 'echo') lines = ['Проверка релея', 'Вторая строка', 'Третья строка'];
      else if (ENGINE === 'command') {
        if (!CMD) throw new Error('для --engine command нужен --cmd');
        lines = await runCommand(img.data);
      } else lines = await glens(img.data);
      lines = (lines || []).map(s => String(s).trim()).filter(Boolean);
      res.writeHead(200, { ...CORS, 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ lines }));
    } catch (e) {
      res.writeHead(502, { ...CORS, 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: String((e && e.message) || e) }));
    }
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`релей Lens на http://0.0.0.0:${PORT} · режим ${ENGINE} · CORS ${ORIGIN}`);
  console.log('в читалке: «Голос и чтение» → «Прямое распознавание без сайта» → адрес этого сервера');
});
