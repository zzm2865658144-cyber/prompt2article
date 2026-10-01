/* prompt2article web UI -- no frameworks, no external requests. */
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  config: null,
  style: null,
  markdown: '',
  running: false,
  controller: null,
};

/* ------------------------------------------------------------------ utils */
const escapeHtml = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function inline(text) {
  // Escape first, then extract code spans so ** inside `code` is left alone.
  let s = escapeHtml(text);
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[Number(i)]}</code>`);
  return s;
}

/** Minimal Markdown -> HTML. Everything is escaped before any tag is emitted. */
function renderMarkdown(md) {
  const lines = String(md).replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let i = 0, list = null, para = [], quote = [];

  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${inline(quote.join(' '))}</blockquote>`); quote = []; } };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };

  while (i < lines.length) {
    const line = lines[i];

    if (/^```/.test(line)) {
      flushAll();
      const buf = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++;
      out.push(`<pre><code>${escapeHtml(buf.join('\n'))}</code></pre>`);
      continue;
    }
    if (!line.trim()) { flushAll(); i++; continue; }

    let m;
    if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
      flushAll();
      const lvl = Math.min(m[1].length, 6);
      out.push(`<h${lvl}>${inline(m[2])}</h${lvl}>`);
      i++; continue;
    }
    if (/^\s*(?:[-*_]\s*){3,}$/.test(line)) { flushAll(); out.push('<hr>'); i++; continue; }
    if ((m = /^\s*[-*+]\s+(.*)$/.exec(line))) {
      flushPara(); flushQuote();
      if (list !== 'ul') { flushList(); out.push('<ul>'); list = 'ul'; }
      out.push(`<li>${inline(m[1])}</li>`); i++; continue;
    }
    if ((m = /^\s*\d+[.)]\s+(.*)$/.exec(line))) {
      flushPara(); flushQuote();
      if (list !== 'ol') { flushList(); out.push('<ol>'); list = 'ol'; }
      out.push(`<li>${inline(m[1])}</li>`); i++; continue;
    }
    if ((m = /^>\s?(.*)$/.exec(line))) {
      flushPara(); flushList();
      quote.push(m[1]); i++; continue;
    }
    flushList(); flushQuote();
    para.push(line.trim()); i++;
  }
  flushAll();
  return out.join('\n');
}

function splitFrontMatter(md) {
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(md);
  if (!m) return { meta: null, body: md };
  const meta = {};
  for (const line of m[1].split('\n')) {
    const at = line.indexOf(':');
    if (at > 0) meta[line.slice(0, at).trim()] = line.slice(at + 1).trim().replace(/^"|"$/g, '');
  }
  return { meta, body: md.slice(m[0].length) };
}

function showTab(name) {
  for (const t of document.querySelectorAll('.tab')) t.classList.toggle('active', t.dataset.tab === name);
  $('viewPreview').hidden = name !== 'preview';
  $('viewMarkdown').hidden = name !== 'markdown';
  $('viewLog').hidden = name !== 'log';
}

function setStatus(text, cls) {
  $('statusText').textContent = text;
  $('status').className = 'status' + (cls ? ' ' + cls : '');
}

function logLine(text, cls) {
  const box = $('viewLog');
  const empty = box.querySelector('.placeholder');
  if (empty) empty.remove();
  const el = document.createElement('div');
  el.className = 'line' + (cls ? ' ' + cls : '');
  el.textContent = text;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

function clearLog() {
  $('viewLog').innerHTML = '<p class="placeholder">正在运行…</p>';
}

/* ----------------------------------------------------------------- config */
async function loadConfig() {
  const res = await fetch('/api/config');
  const cfg = await res.json();
  state.config = cfg;
  state.style = cfg.defaultStyle;

  const box = $('styles');
  box.innerHTML = '';
  for (const s of cfg.styles) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'style' + (s.key === cfg.defaultStyle ? ' on' : '');
    b.dataset.key = s.key;
    b.innerHTML = `<b>${escapeHtml(s.name)}</b><span>${escapeHtml(s.summary)}</span>`;
    b.addEventListener('click', () => {
      state.style = s.key;
      for (const o of box.children) o.classList.toggle('on', o.dataset.key === s.key);
      if (!Number($('words').dataset.touched)) $('words').value = s.words;
    });
    box.appendChild(b);
  }

  const lang = $('language');
  lang.innerHTML = '';
  for (const [code, name] of Object.entries(cfg.languages)) {
    const o = document.createElement('option');
    o.value = code; o.textContent = name;
    if (code === 'zh') o.selected = true;
    lang.appendChild(o);
  }

  $('words').value = cfg.defaultWords;

  if (cfg.hasKey) {
    setStatus(`模型 ${cfg.model} · Key 已配置`);
    $('offline').checked = false;
  } else {
    setStatus('没有配置 API Key —— 已切到离线模拟模式', 'warn');
    $('offline').checked = true;
    logLine('没有找到 .env 或 API Key，默认用离线模拟模式（内容是占位文字）', 'err');
    logLine('要生成真实文章：把 .env.example 复制为 .env，填入 P2A_API_KEY，然后重启本服务');
  }
}

/* -------------------------------------------------------------- file list */
async function loadFiles() {
  const res = await fetch('/api/articles');
  const { articles } = await res.json();
  const ul = $('files');
  ul.innerHTML = '';
  if (!articles.length) {
    ul.innerHTML = '<li class="empty">还没有生成过文章</li>';
    return;
  }
  for (const a of articles) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = `${escapeHtml(a.name)}<em>${a.mtime} · ${(a.size / 1024).toFixed(1)} KB</em>`;
    b.addEventListener('click', () => openArticle(a.name));
    li.appendChild(b);
    ul.appendChild(li);
  }
}

async function openArticle(name) {
  const res = await fetch('/api/article?name=' + encodeURIComponent(name));
  if (!res.ok) { setStatus('读取文件失败', 'err'); return; }
  const md = await res.text();
  state.markdown = md;
  showArticle(md, {});
  showTab('preview');
  $('copy').disabled = false;
  $('download').disabled = false;
  setStatus('已载入 ' + name);
}

/* --------------------------------------------------------------- rendering */
function showArticle(markdown, extra) {
  const { meta, body } = splitFrontMatter(markdown);
  let head = '';
  const title = (extra && extra.title) || (meta && meta.title) || '';
  if (title) head += `<h1>${escapeHtml(title)}</h1>`;

  const bits = [];
  if (extra && extra.words) bits.push(`<span>实际 <b>${extra.words}</b> 字</span>`);
  if (extra && extra.targetWords) bits.push(`<span>目标 <b>${extra.targetWords}</b> 字</span>`);
  if (meta) {
    if (meta.style) bits.push(`<span>风格 <b>${escapeHtml(meta.style)}</b></span>`);
    if (meta.model) bits.push(`<span>模型 <b>${escapeHtml(meta.model)}</b></span>`);
    if (meta.generated_at) bits.push(`<span>${escapeHtml(meta.generated_at)}</span>`);
  }
  if (extra && extra.path) bits.push(`<span>已保存到 <b>${escapeHtml(extra.path)}</b></span>`);
  if (bits.length) head += `<div class="meta">${bits.join('')}</div>`;

  $('viewPreview').innerHTML = `<article class="article">${head}${renderMarkdown(body)}</article>`;
  $('viewMarkdown').textContent = markdown;
}

/* -------------------------------------------------------------- generation */
function payload() {
  return {
    prompt: $('prompt').value.trim(),
    style: state.style,
    words: Number($('words').value) || 1200,
    sections: Number($('sections').value) || 8,
    language: $('language').value,
    title: $('title').value.trim(),
    audience: $('audience').value.trim(),
    polish: $('polish').checked,
    offline: $('offline').checked,
    save: $('save').checked,
  };
}

function handleEvent(ev) {
  if (ev.type === 'start') {
    logLine(`开始：风格=${ev.style} 模型=${ev.model} 目标≈${ev.words} 字`);
  } else if (ev.type === 'progress') {
    logLine(ev.message);
    setStatus(ev.message);
  } else if (ev.type === 'done') {
    state.markdown = ev.markdown;
    showArticle(ev.markdown, { title: ev.title, words: ev.words, targetWords: ev.targetWords, path: ev.path });
    showTab('preview');
    logLine(`完成：${ev.words} 字`, 'ok');
    if (ev.path) logLine('已保存 ' + ev.path, 'ok');
    setStatus(`完成 · ${ev.words} 字`);
    $('copy').disabled = false;
    $('download').disabled = false;
    loadFiles();
  } else if (ev.type === 'error') {
    logLine(ev.message, 'err');
    setStatus('生成失败', 'err');
    showTab('log');
  }
}

async function generate() {
  if (state.running) return;
  const body = payload();
  if (!body.prompt) {
    setStatus('请先填写文章主题', 'err');
    $('prompt').focus();
    return;
  }

  state.running = true;
  $('go').disabled = true;
  $('stop').hidden = false;
  $('copy').disabled = true;
  $('download').disabled = true;
  clearLog();
  showTab('log');
  setStatus('正在生成…');

  const controller = new AbortController();
  state.controller = controller;
  let finished = false;

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let at;
      while ((at = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, at);
        buf = buf.slice(at + 2);
        const data = block.split('\n')
          .filter((l) => l.startsWith('data: '))
          .map((l) => l.slice(6))
          .join('\n');
        if (!data) continue;
        try {
          const ev = JSON.parse(data);
          handleEvent(ev);
          if (ev.type === 'done' || ev.type === 'error') finished = true;
        } catch (e) { /* ignore a malformed frame */ }
      }
    }
    if (!finished) {
      logLine('连接结束了，但没有收到完成事件。', 'err');
      setStatus('意外中断', 'err');
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      logLine('已手动停止。', 'err');
      setStatus('已停止');
    } else {
      logLine(String(err.message || err), 'err');
      setStatus('生成失败', 'err');
    }
  } finally {
    state.running = false;
    state.controller = null;
    $('go').disabled = false;
    $('stop').hidden = true;
  }
}

/* ------------------------------------------------------------------ wiring */
function download() {
  const blob = new Blob([state.markdown], { type: 'text/markdown;charset=utf-8' });
  const a = document.createElement('a');
  const first = (state.markdown.match(/^#\s+(.+)$/m) || [, 'article'])[1];
  a.href = URL.createObjectURL(blob);
  a.download = first.replace(/[\\/:*?"<>|]/g, '').slice(0, 40) + '.md';
  a.click();
  URL.revokeObjectURL(a.href);
}

async function copy() {
  try {
    await navigator.clipboard.writeText(state.markdown);
    setStatus('已复制到剪贴板');
  } catch {
    setStatus('复制失败，请手动选中', 'err');
  }
}

$('go').addEventListener('click', generate);
$('stop').addEventListener('click', () => state.controller && state.controller.abort());
$('copy').addEventListener('click', copy);
$('download').addEventListener('click', download);
$('words').addEventListener('input', (e) => { e.target.dataset.touched = '1'; });
$('prompt').addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') generate();
});
for (const t of document.querySelectorAll('.tab')) {
  t.addEventListener('click', () => showTab(t.dataset.tab));
}

loadConfig().catch((e) => setStatus('读不到配置：' + e.message, 'err'));
loadFiles().catch(() => {});
