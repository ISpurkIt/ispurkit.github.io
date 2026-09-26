'use strict';

/* ================= helpers ================= */
const TOKEN = document.querySelector('meta[name=token]').content;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = (name, cls = 'ic') => `<svg class="${cls}"><use href="#i-${name}"/></svg>`;
const isUrl = (s) => /^https?:\/\/\S+$/i.test(String(s || '').trim());
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const store = {
  get(k, d) { try { const v = localStorage.getItem('ytg.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('ytg.' + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

async function api(path, body) {
  const res = await fetch('/api/' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-Token': TOKEN, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new Error(data.error || `Ошибка ${res.status}`);
  return data;
}

function plural(n, forms) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}
function fmtBytes(b) {
  if (!b) return '—';
  const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(b >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}
const fmtSpeed = (b) => (b ? fmtBytes(b) + '/с' : '');
function fmtDuration(s) {
  if (s == null || isNaN(s)) return '';
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}
function fmtCount(n) {
  if (n == null) return '';
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace('.0', '') + ' млрд';
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.0', '') + ' млн';
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace('.0', '') + ' тыс.';
  return String(n);
}
function fmtDate(d) {
  if (!d || d.length !== 8) return '';
  const date = new Date(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8));
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
}
const basename = (p) => String(p || '').split(/[\\/]/).pop();

/* ================= state ================= */
const S = {
  opts: {}, app: {}, defaults: {},
  tasks: [], history: [], historyCount: 0,
  info: null, infoUrl: '', tab: 'formats', fmtFilter: 'all',
  sel: { v: null, a: null }, prevMode: 'video', fromTable: false,
  entrySel: new Set(), splitEntries: true, autoSearch: '',
  batch: false, env: {}, prevStatus: {}, lastClip: '',
};

/* ================= toasts ================= */
function toast(text, { type = 'ok', sub = '', action = null, timeout = 4200 } = {}) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const ic = { ok: 'check', error: 'alert', warn: 'alert', info: 'info' }[type] || 'info';
  el.innerHTML = `<div class="t-ic">${icon(ic)}</div><div class="t-text"><b>${esc(text)}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</div>`;
  if (action) {
    const b = document.createElement('button');
    b.className = 'btn ghost small';
    b.textContent = action.label;
    b.onclick = () => { action.run(); close(); };
    el.append(b);
  }
  $('#toasts').append(el);
  let timer;
  function close() { clearTimeout(timer); el.classList.add('out'); setTimeout(() => el.remove(), 300); }
  el.addEventListener('mouseenter', () => clearTimeout(timer));
  el.addEventListener('mouseleave', () => { timer = setTimeout(close, 1800); });
  timer = setTimeout(close, timeout);
  return close;
}
const toastError = (e) => toast(e.message || String(e), { type: 'error', timeout: 7000 });

/* ================= navigation ================= */
function showPage(page) {
  $$('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  $$('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + page));
  store.set('page', page);
  requestAnimationFrame(syncGliders);
}

/* ================= theme / app settings ================= */
const media = window.matchMedia('(prefers-color-scheme: light)');
function applyApp() {
  const theme = S.app.theme === 'system' ? (media.matches ? 'light' : 'dark') : S.app.theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.accent = S.app.accent || 'sunset';
  $('#theme-toggle use').setAttribute('href', theme === 'dark' ? '#i-sun' : '#i-moon');
  $$('[data-app]').forEach((el) => {
    const v = S.app[el.dataset.app];
    if (el.matches('.seg, .swatches')) {
      $$('button', el).forEach((b) => b.classList.toggle('active', b.dataset.v === String(v)));
    } else if (el.type === 'checkbox') el.checked = !!v;
    else el.value = v;
  });
  $$('[data-show-app]').forEach((el) => { el.textContent = S.app[el.dataset.showApp]; });
  syncGliders();
}
media.addEventListener?.('change', applyApp);
const saveApp = debounce(() => api('settings', { app: S.app }).catch(toastError), 300);
function setApp(key, value) {
  S.app[key] = value;
  applyApp();
  saveApp();
  if (key === 'notify' && value && 'Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

/* ================= options binding ================= */
const saveOpts = debounce(() => api('settings', { options: S.opts }).catch(toastError), 400);
const refreshCommand = debounce(updateCommand, 200);

function setOpt(key, value, { sync = true } = {}) {
  S.opts[key] = value;
  if (key === 'mode' && value !== 'custom') { S.sel = { v: null, a: null }; S.prevMode = value; if (S.info) renderPreview(); }
  saveOpts();
  refreshCommand();
  if (sync) syncOptions();
  else { syncSummaries(); syncDependents(); }
}

function bindOptions() {
  $$('input[data-opt], select[data-opt], textarea[data-opt]').forEach((el) => {
    const handler = () => {
      const v = el.type === 'checkbox' ? el.checked : el.value;
      if (el.dataset.opt === 'custom_format') S.fromTable = false;
      setOpt(el.dataset.opt, v, { sync: el.type === 'checkbox' || el.tagName === 'SELECT' });
      $$(`[data-show="${el.dataset.opt}"]`).forEach((s) => { s.textContent = v; });
    };
    el.addEventListener(el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input', handler);
  });
  $$('.chips[data-opt], .seg[data-opt]').forEach((group) => {
    group.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]');
      if (b) setOpt(group.dataset.opt, b.dataset.v);
    });
  });
  $$('[data-multi]').forEach((group) => {
    group.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]');
      if (!b) return;
      const key = group.dataset.multi;
      const set = new Set(S.opts[key] || []);
      set.has(b.dataset.v) ? set.delete(b.dataset.v) : set.add(b.dataset.v);
      setOpt(key, [...set]);
    });
  });
  $$('[data-fill]').forEach((b) => b.addEventListener('click', () => setOpt(b.dataset.fill, b.dataset.val)));

  // filename template helpers
  const tpl = $('#tpl-input');
  $$('[data-token]').forEach((b) => b.addEventListener('click', () => {
    const t = b.dataset.token, s = tpl.selectionStart ?? tpl.value.length, e = tpl.selectionEnd ?? s;
    tpl.value = tpl.value.slice(0, s) + t + tpl.value.slice(e);
    tpl.focus();
    tpl.setSelectionRange(s + t.length, s + t.length);
    setOpt('filename_template', tpl.value, { sync: false });
  }));
  $('#tpl-presets').addEventListener('change', (e) => {
    if (e.target.value) setOpt('filename_template', e.target.value);
    e.target.value = '';
  });

  // subtitle language quick chips
  $('#sub-lang-quick').addEventListener('click', (e) => {
    const b = e.target.closest('[data-lang]');
    if (b) toggleSubLang(b.dataset.lang);
  });

  // native pickers
  $$('[data-pick]').forEach((b) => b.addEventListener('click', async () => {
    b.classList.add('loading');
    try {
      const { path } = await api('pick', { kind: b.dataset.kind, initial: S.opts[b.dataset.pick] });
      if (path) setOpt(b.dataset.pick, path);
    } catch (e) { toastError(e); } finally { b.classList.remove('loading'); }
  }));
  $('#btn-open-outdir').addEventListener('click', () => api('open', { path: S.opts.output_dir }).catch(toastError));
  $('#btn-clear-range').addEventListener('click', () => { S.opts.section_start = ''; setOpt('section_end', ''); });

  // app settings
  $$('[data-app]').forEach((el) => {
    if (el.matches('.seg, .swatches')) {
      el.addEventListener('click', (e) => { const b = e.target.closest('button[data-v]'); if (b) setApp(el.dataset.app, b.dataset.v); });
    } else {
      el.addEventListener(el.type === 'range' ? 'input' : 'change', () => {
        setApp(el.dataset.app, el.type === 'checkbox' ? el.checked : el.type === 'range' ? +el.value : el.value);
      });
    }
  });

  $$('details.acc').forEach((d) => {
    const open = store.get('acc.' + d.dataset.acc, null);
    if (open !== null) d.open = open;
    d.addEventListener('toggle', () => { store.set('acc.' + d.dataset.acc, d.open); syncGliders(); });
  });
}

function toggleSubLang(lang, { auto = false } = {}) {
  let langs = String(S.opts.sub_langs || '').split(',').map((s) => s.trim()).filter(Boolean);
  if (lang === 'all') langs = langs.includes('all') ? [] : ['all'];
  else {
    langs = langs.filter((l) => l !== 'all');
    langs = langs.includes(lang) ? langs.filter((l) => l !== lang) : [...langs, lang];
  }
  S.opts.subtitles = langs.length > 0 || S.opts.subtitles;
  if (auto) S.opts.auto_subs = true;
  setOpt('sub_langs', langs.join(','));
  if (S.info) renderPreview();
}

function syncOptions() {
  const o = S.opts;
  $$('input[data-opt], select[data-opt], textarea[data-opt]').forEach((el) => {
    if (el === document.activeElement && el.type !== 'checkbox') return;
    const v = o[el.dataset.opt];
    if (el.type === 'checkbox') el.checked = !!v;
    else el.value = v ?? '';
  });
  $$('.chips[data-opt], .seg[data-opt]').forEach((g) => {
    $$('button[data-v]', g).forEach((b) => b.classList.toggle('active', String(o[g.dataset.opt]) === b.dataset.v));
  });
  $$('[data-multi]').forEach((g) => {
    const set = new Set(o[g.dataset.multi] || []);
    $$('button[data-v]', g).forEach((b) => b.classList.toggle('active', set.has(b.dataset.v)));
  });
  $$('[data-show]').forEach((s) => { s.textContent = o[s.dataset.show]; });
  $$('.mode-panel').forEach((p) => p.classList.toggle('active', p.dataset.mode === o.mode));
  const langs = String(o.sub_langs || '').split(',').map((s) => s.trim());
  $$('#sub-lang-quick [data-lang]').forEach((b) => b.classList.toggle('active', langs.includes(b.dataset.lang)));
  $('#audio-quality-field .chips').classList.toggle('disabled', ['flac', 'wav', 'best'].includes(o.audio_format));
  syncDependents();
  syncSummaries();
  syncGliders();
}

function syncDependents() {
  $$('[data-when]').forEach((el) => {
    const v = S.opts[el.dataset.when];
    el.classList.toggle('off', !v || v === 'off');
  });
}

function syncGliders() {
  $$('.seg').forEach((seg) => {
    const glider = $('.seg-glider', seg);
    const active = $('button.active', seg);
    if (!glider) return;
    if (!active || !active.offsetWidth) { glider.style.opacity = active ? glider.style.opacity : '0'; return; }
    glider.style.opacity = '1';
    glider.style.width = active.offsetWidth + 'px';
    glider.style.transform = `translateX(${active.offsetLeft}px)`;
  });
}
window.addEventListener('resize', debounce(syncGliders, 100));

function syncSummaries() {
  const o = S.opts, d = S.defaults;
  const post = [
    o.embed_thumbnail && 'обложка', o.embed_metadata && 'метаданные', o.embed_chapters && 'главы',
    o.split_chapters && 'разделение', o.write_thumbnail && 'файл обложки', o.write_description && 'описание', o.write_info_json && 'json',
  ].filter(Boolean);
  const dir = String(o.output_dir || '').split(/[\\/]/).filter(Boolean).slice(-2).join('/');
  const range = [
    (o.section_start || o.section_end) && `${o.section_start || '0:00'} – ${o.section_end || 'конец'}`,
    o.no_playlist && 'без плейлиста', o.playlist_items && `элементы ${o.playlist_items}`,
    o.playlist_reverse && 'обратный порядок', o.playlist_random && 'случайный порядок',
  ].filter(Boolean);
  const net = [
    o.cookies_browser && `cookies: ${o.cookies_browser}`, o.cookies_file && 'cookies.txt', o.proxy && 'прокси',
    o.rate_limit && `≤ ${o.rate_limit}/с`, o.geo_bypass_country && `гео: ${o.geo_bypass_country}`, o.impersonate && `как ${o.impersonate}`,
  ].filter(Boolean);
  const sums = {
    output: [dir ? '…/' + dir : '', o.use_archive ? 'архив' : ''].filter(Boolean).join(' · '),
    subs: o.subtitles ? `${o.sub_langs || 'все'}${o.auto_subs ? ' + авто' : ''}${o.embed_subs ? ' · встроить' : ''}` : 'выключены',
    post: post.length ? post.join(' · ') : 'ничего',
    sponsor: o.sponsorblock === 'off' ? 'выключен'
      : `${o.sponsorblock === 'remove' ? 'вырезать' : 'отметить'}: ${(o.sponsorblock_categories || []).length} ${plural((o.sponsorblock_categories || []).length, ['категория', 'категории', 'категорий'])}`,
    range: range.length ? range.join(' · ') : 'всё целиком',
    net: net.length ? net.join(' · ') : 'по умолчанию',
    pro: [o.extra_args && o.extra_args.trim() && 'свои аргументы', o.use_config && 'конфиг yt-dlp'].filter(Boolean).join(' · ') || 'не заданы',
  };
  const on = {
    output: o.use_archive || o.restrict_filenames, subs: o.subtitles, post: post.length > 0, sponsor: o.sponsorblock !== 'off',
    range: range.length > 0, net: net.length > 0, pro: !!(String(o.extra_args || '').trim() || o.use_config),
  };
  $$('[data-sum]').forEach((el) => {
    el.textContent = sums[el.dataset.sum] || '';
    el.classList.toggle('on', !!on[el.dataset.sum]);
  });
  void d;
}

/* ================= command preview ================= */
function currentUrls() {
  if (S.batch) return $('#urls').value.split(/\s+/).filter(isUrl);
  const u = $('#url').value.trim();
  return u ? [u] : [];
}
const shellQuote = (a) => (/^[\w@%+=:,./\-]+$/.test(a) ? a : `'${a.replace(/'/g, `'\\''`)}'`);

async function updateCommand() {
  try {
    const urls = currentUrls();
    const r = await api('command', { options: S.opts, urls: urls.length ? urls.slice(0, 3) : ['URL'] });
    S.command = r.command;
    const parts = ['<span class="p">yt-dlp</span>'];
    for (const a of r.args) parts.push(a.startsWith('-') ? `<span class="k">${esc(a)}</span>` : esc(shellQuote(a)));
    for (const u of (urls.length ? urls.slice(0, 3) : ['URL'])) parts.push(`<span class="u">${esc(shellQuote(u))}</span>`);
    if (urls.length > 3) parts.push(`<span class="u">… ещё ${urls.length - 3}</span>`);
    $('#cmd').innerHTML = parts.join(' ');
    $('#cmd-error').hidden = !r.error;
    if (r.error) $('#cmd-error').innerHTML = `${icon('alert')} ${esc(r.error)}`;
  } catch (e) {
    $('#cmd-error').hidden = false;
    $('#cmd-error').textContent = e.message;
  }
}

/* ================= analysis & preview ================= */
let analyzeSeq = 0;
async function analyze() {
  if (S.batch) { download(); return; }
  const url = $('#url').value.trim();
  if (!url) { $('#url').focus(); shake($('#url-card')); return; }
  const seq = ++analyzeSeq;
  const btn = $('#btn-analyze');
  btn.classList.add('loading');
  const pv = $('#preview');
  pv.hidden = false;
  pv.innerHTML = `<div class="skeleton"><div class="sk img"></div><div class="sk-lines">
    <div class="sk l" style="width:30%"></div><div class="sk l" style="width:90%;height:22px"></div>
    <div class="sk l" style="width:70%;height:22px"></div><div class="sk l" style="width:50%"></div></div></div>`;
  try {
    const info = await api('info', { url, options: S.opts });
    if (seq !== analyzeSeq) return;
    S.info = info;
    S.infoUrl = url;
    S.sel = { v: null, a: null };
    S.fmtFilter = 'all';
    S.autoSearch = '';
    S.entrySel = new Set((info.entries || []).map((e) => e.index));
    S.tab = info.is_playlist ? 'entries' : 'formats';
    // a stream picked in the previous video's format table means nothing for this one
    if (S.opts.mode === 'custom' && (S.fromTable || !S.opts.custom_format)) {
      S.opts.custom_format = '';
      setOpt('mode', S.prevMode || 'video');
    }
    S.fromTable = false;
    renderPreview();
  } catch (e) {
    if (seq !== analyzeSeq) return;
    pv.hidden = true;
    S.info = null;
    toast('Не удалось получить информацию', { type: 'error', sub: e.message, timeout: 9000 });
  } finally {
    if (seq === analyzeSeq) btn.classList.remove('loading');
  }
}

function shake(el) {
  el.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-8px)' }, { transform: 'translateX(8px)' }, { transform: 'translateX(-4px)' }, { transform: 'translateX(0)' }], { duration: 350 });
}

function sortedFormats() {
  const f = S.info.formats || [];
  const score = (x) => [(x.height || 0), (x.fps || 0), (x.tbr || x.abr || 0)];
  return [...f].sort((a, b) => {
    const kind = (x) => (x.has_video ? 0 : 1);
    if (kind(a) !== kind(b)) return kind(a) - kind(b);
    const sa = score(a), sb = score(b);
    for (let i = 0; i < 3; i++) if (sb[i] !== sa[i]) return sb[i] - sa[i];
    return 0;
  });
}
const fmtSize = (f) => (f.filesize ? fmtBytes(f.filesize) : f.filesize_approx ? '≈ ' + fmtBytes(f.filesize_approx) : '—');
const shortCodec = (c) => (!c || c === 'none' ? '' : c.split('.')[0].replace('avc1', 'h264').replace('mp4a', 'aac'));

function selectionText() {
  const f = S.info?.formats || [];
  const v = f.find((x) => x.id === S.sel.v), a = f.find((x) => x.id === S.sel.a);
  if (!v && !a) return '';
  const size = [v, a].reduce((s, x) => s + (x ? x.filesize || x.filesize_approx || 0 : 0), 0);
  const parts = [];
  if (v) parts.push(`${v.height ? v.height + 'p' : v.id} ${v.ext}`);
  if (a) parts.push(`${a.abr ? Math.round(a.abr) + 'k' : a.id} ${a.ext}`);
  else if (v && !v.has_audio) parts.push('лучшее аудио');
  return `${parts.join(' + ')}${size ? ' · ' + fmtBytes(size) : ''}`;
}

function applyFormatSelection() {
  const f = S.info.formats || [];
  const v = f.find((x) => x.id === S.sel.v);
  let fmt = '';
  if (S.sel.v && S.sel.a) fmt = `${S.sel.v}+${S.sel.a}`;
  else if (S.sel.v) fmt = v && !v.has_audio ? `${S.sel.v}+ba/${S.sel.v}` : S.sel.v;
  else if (S.sel.a) fmt = S.sel.a;
  if (fmt) {
    if (S.opts.mode !== 'custom') S.prevMode = S.opts.mode;
    S.opts.custom_format = fmt;
    S.opts.format_sort = '';
    S.fromTable = true;
    setOpt('mode', 'custom');
  } else {
    S.opts.custom_format = '';
    S.fromTable = false;
    setOpt('mode', S.prevMode || 'video');
  }
}

function renderPreview() {
  const info = S.info, pv = $('#preview');
  if (!info) { pv.hidden = true; return; }
  pv.hidden = false;
  const meta = [];
  if (info.uploader) meta.push(`<span>${icon('film')}${esc(info.uploader)}</span>`);
  if (info.view_count != null) meta.push(`<span>${icon('search')}${fmtCount(info.view_count)} ${info.view_count >= 1000 ? 'просмотров' : plural(info.view_count, ['просмотр', 'просмотра', 'просмотров'])}</span>`);
  if (info.upload_date) meta.push(`<span>${icon('clock')}${fmtDate(info.upload_date)}</span>`);
  if (info.like_count != null) meta.push(`<span>♥ ${fmtCount(info.like_count)}</span>`);
  if (info.is_playlist) meta.push(`<span>${icon('layers')}${info.count} ${plural(info.count, ['видео', 'видео', 'видео'])}</span>`);

  const tabs = [];
  if (info.is_playlist) tabs.push(['entries', 'Видео', info.entries.length]);
  else {
    tabs.push(['formats', 'Форматы', (info.formats || []).length]);
    tabs.push(['subs', 'Субтитры', (info.subtitles || []).length + (info.auto_subtitles || []).length]);
    if ((info.chapters || []).length) tabs.push(['chapters', 'Главы', info.chapters.length]);
    if (info.description) tabs.push(['desc', 'Описание', null]);
  }
  if (!tabs.some((t) => t[0] === S.tab)) S.tab = tabs[0][0];
  const sel = selectionText();

  pv.innerHTML = `
    <div class="pv-top">
      <div class="pv-thumb">
        ${icon(info.is_playlist ? 'layers' : 'film')}
        ${info.thumbnail ? `<img src="${esc(info.thumbnail)}" alt="" referrerpolicy="no-referrer">` : ''}
        ${info.duration ? `<span class="dur">${fmtDuration(info.duration)}</span>` : ''}
        ${info.is_live ? '<span class="live">LIVE</span>' : ''}
        ${info.is_playlist ? `<div class="pl-badge">${icon('layers')} Плейлист · ${info.count}</div>` : ''}
      </div>
      <div class="pv-info">
        ${info.extractor ? `<span class="pv-site">${esc(info.extractor)}</span>` : ''}
        <h2 class="pv-title" title="${esc(info.title)}">${esc(info.title)}</h2>
        <div class="pv-meta">${meta.join('')}</div>
        <div class="pv-actions">
          ${sel ? `<span class="pv-selection">${icon('check')} Выбрано: <b>${esc(sel)}</b> <button class="icon-btn ghost" data-act="clear-sel" title="Сбросить выбор" style="width:24px;height:24px">${icon('x')}</button></span>` : ''}
          ${info.url ? `<a class="btn ghost small" href="${esc(info.url)}" target="_blank" rel="noreferrer">${icon('external')}<span>Открыть</span></a>` : ''}
          <button class="btn ghost small" data-act="copy-title">${icon('copy')}<span>Название</span></button>
          <button class="btn ghost small" data-act="close-preview">${icon('x')}<span>Закрыть</span></button>
        </div>
      </div>
    </div>
    <div class="tabs">${tabs.map(([id, name, n]) => `<button class="tab ${id === S.tab ? 'active' : ''}" data-tab="${id}">${name}${n != null ? `<span class="count">${n}</span>` : ''}</button>`).join('')}</div>
    <div class="tab-body">${renderTab()}</div>`;
}

function renderTab() {
  const info = S.info;
  if (S.tab === 'formats') {
    const filters = [['all', 'Все'], ['av', 'Видео + звук'], ['v', 'Только видео'], ['a', 'Только аудио']];
    const rows = sortedFormats().filter((f) => (
      S.fmtFilter === 'all' || (S.fmtFilter === 'av' && f.has_video && f.has_audio)
      || (S.fmtFilter === 'v' && f.has_video && !f.has_audio) || (S.fmtFilter === 'a' && !f.has_video && f.has_audio)));
    return `
      <div class="tab-tools">
        <div class="chips small" data-fmt-filter>${filters.map(([k, n]) => `<button data-v="${k}" class="${S.fmtFilter === k ? 'active' : ''}">${n}</button>`).join('')}</div>
        <span class="grow"></span>
        <span class="muted small">Кликните видео‑поток и аудио‑поток, чтобы собрать свой формат</span>
      </div>
      ${rows.length ? `<table class="fmt-table">
        <thead><tr><th></th><th>ID</th><th>Тип</th><th>Разрешение</th><th>Кодеки</th><th>Битрейт</th><th>Размер</th><th>Примечание</th></tr></thead>
        <tbody>${rows.map((f) => `
          <tr class="fmt ${f.id === S.sel.v || f.id === S.sel.a ? 'sel' : ''}" data-fmt="${esc(f.id)}">
            <td><span class="radio"></span></td>
            <td class="mono">${esc(f.id)}</td>
            <td>${f.has_video ? '<span class="tag v">ВИДЕО</span>' : ''}${f.has_audio ? '<span class="tag a">АУДИО</span>' : ''}${f.hdr ? `<span class="tag hdr">${esc(f.hdr)}</span>` : ''}</td>
            <td class="res">${f.has_video ? `${f.height ? f.height + 'p' : esc(f.width ? f.width + 'w' : '—')}${f.fps && f.fps > 30 ? `<small class="muted">${Math.round(f.fps)}</small>` : ''}` : `<span class="muted">${f.asr ? (f.asr / 1000).toFixed(1) + ' кГц' : '—'}</span>`} <span class="muted small">${esc(f.ext)}</span></td>
            <td class="codec">${esc([shortCodec(f.vcodec), shortCodec(f.acodec)].filter(Boolean).join(' · ') || '—')}</td>
            <td class="mono">${f.tbr ? Math.round(f.tbr) + 'k' : f.abr ? Math.round(f.abr) + 'k' : '—'}</td>
            <td class="mono">${fmtSize(f)}</td>
            <td class="muted">${esc([f.note, f.language, f.protocol && f.protocol.includes('m3u8') ? 'HLS' : ''].filter(Boolean).join(' · '))}</td>
          </tr>`).join('')}</tbody></table>` : '<p class="hint">Нет форматов под этот фильтр.</p>'}`;
  }
  if (S.tab === 'entries') {
    const n = S.entrySel.size, total = info.entries.length;
    return `
      <div class="tab-tools">
        <button class="btn ghost small" data-act="sel-all">${icon('check')}<span>Все</span></button>
        <button class="btn ghost small" data-act="sel-none">${icon('x')}<span>Ни одного</span></button>
        <button class="btn ghost small" data-act="sel-invert">${icon('retry')}<span>Инвертировать</span></button>
        <span class="muted small">Выбрано ${n} из ${total}</span>
        <span class="grow"></span>
        <label class="mini-switch"><input type="checkbox" data-act="split" ${S.splitEntries ? 'checked' : ''}><i></i><span>Каждое видео — отдельной задачей</span></label>
      </div>
      <div class="entries">${info.entries.map((e) => `
        <div class="entry ${S.entrySel.has(e.index) ? 'on' : 'off'}" data-entry="${e.index}">
          <span class="check">${icon('check')}</span>
          <span class="num">${e.index}</span>
          ${e.thumbnail ? `<img src="${esc(e.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '<span class="noimg"></span>'}
          <div class="t"><b title="${esc(e.title)}">${esc(e.title)}</b>${e.uploader ? `<small>${esc(e.uploader)}</small>` : ''}</div>
          <span class="d">${fmtDuration(e.duration)}</span>
        </div>`).join('')}</div>`;
  }
  if (S.tab === 'subs') {
    const langs = String(S.opts.sub_langs || '').split(',').map((s) => s.trim());
    const chip = (s, auto) => `<button data-sublang="${esc(s.lang)}" data-auto="${auto ? 1 : ''}" class="${S.opts.subtitles && langs.includes(s.lang) ? 'active' : ''}" title="${esc(s.name)}">${esc(s.lang)}${s.name && s.name !== s.lang ? ` <span class="muted">· ${esc(s.name)}</span>` : ''}</button>`;
    const q = S.autoSearch.toLowerCase();
    const autos = (info.auto_subtitles || []).filter((s) => !q || s.lang.toLowerCase().includes(q) || s.name.toLowerCase().includes(q));
    return `
      <div class="field"><label>Субтитры автора</label>
        ${(info.subtitles || []).length ? `<div class="chips small">${info.subtitles.map((s) => chip(s, false)).join('')}</div>` : '<p class="hint">Нет загруженных автором субтитров.</p>'}
      </div>
      <div class="field" style="margin-top:14px"><label>Автоматические (${(info.auto_subtitles || []).length})</label>
        ${(info.auto_subtitles || []).length ? `
          <div class="search" style="align-self:flex-start;margin-bottom:6px">${icon('search')}<input data-act="auto-search" placeholder="Язык…" value="${esc(S.autoSearch)}"></div>
          <div class="chips small" data-auto-chips>${autos.slice(0, q ? 200 : 40).map((s) => chip(s, true)).join('')}</div>
          ${!q && autos.length > 40 ? `<p class="hint">…и ещё ${autos.length - 40}. Воспользуйтесь поиском.</p>` : ''}` : '<p class="hint">Нет автоматических субтитров.</p>'}
      </div>`;
  }
  if (S.tab === 'chapters') {
    return `<p class="hint" style="margin-bottom:10px">Кликните главу, чтобы скачать только её.</p>
      <div class="chapter-list">${info.chapters.map((c, i) => `
        <div class="chapter" data-chapter="${i}"><span class="tm">${fmtDuration(c.start)} – ${fmtDuration(c.end)}</span><span>${esc(c.title)}</span><span class="go">${icon('scissors')}</span></div>`).join('')}</div>`;
  }
  if (S.tab === 'desc') return `<div class="desc">${esc(info.description)}</div>`;
  return '';
}

function bindPreview() {
  const pv = $('#preview');
  pv.addEventListener('click', (e) => {
    const t = e.target;
    const tab = t.closest('[data-tab]');
    if (tab) { S.tab = tab.dataset.tab; renderPreview(); return; }
    const filter = t.closest('[data-fmt-filter] button');
    if (filter) { S.fmtFilter = filter.dataset.v; renderPreview(); return; }
    const row = t.closest('tr[data-fmt]');
    if (row) {
      const f = S.info.formats.find((x) => x.id === row.dataset.fmt);
      if (f.has_video && !f.has_audio) S.sel.v = S.sel.v === f.id ? null : f.id;
      else if (!f.has_video) S.sel.a = S.sel.a === f.id ? null : f.id;
      else { S.sel.v = S.sel.v === f.id ? null : f.id; S.sel.a = null; }
      const v = S.info.formats.find((x) => x.id === S.sel.v);
      if (v && v.has_audio) S.sel.a = null;
      applyFormatSelection();
      renderPreview();
      return;
    }
    const entry = t.closest('[data-entry]');
    if (entry) {
      const i = +entry.dataset.entry;
      S.entrySel.has(i) ? S.entrySel.delete(i) : S.entrySel.add(i);
      renderPreview();
      return;
    }
    const sub = t.closest('[data-sublang]');
    if (sub) { toggleSubLang(sub.dataset.sublang, { auto: !!sub.dataset.auto }); return; }
    const ch = t.closest('[data-chapter]');
    if (ch) {
      const c = S.info.chapters[+ch.dataset.chapter];
      S.opts.section_start = fmtDuration(c.start);
      setOpt('section_end', fmtDuration(c.end));
      const acc = $('details[data-acc="range"]');
      acc.open = true;
      toast('Будет скачан только фрагмент', { sub: `${c.title} · ${fmtDuration(c.start)} – ${fmtDuration(c.end)}` });
      return;
    }
    const act = t.closest('[data-act]')?.dataset.act;
    const entries = S.info?.entries || [];
    if (act === 'sel-all') { S.entrySel = new Set(entries.map((x) => x.index)); renderPreview(); }
    if (act === 'sel-none') { S.entrySel = new Set(); renderPreview(); }
    if (act === 'sel-invert') { S.entrySel = new Set(entries.map((x) => x.index).filter((i) => !S.entrySel.has(i))); renderPreview(); }
    if (act === 'clear-sel') { S.sel = { v: null, a: null }; applyFormatSelection(); renderPreview(); }
    if (act === 'close-preview') { S.info = null; renderPreview(); }
    if (act === 'copy-title') copyText(S.info.title, 'Название скопировано');
  });
  pv.addEventListener('change', (e) => {
    if (e.target.dataset.act === 'split') S.splitEntries = e.target.checked;
  });
  pv.addEventListener('input', (e) => {
    if (e.target.dataset.act !== 'auto-search') return;
    S.autoSearch = e.target.value;
    const box = $('[data-auto-chips]', pv);
    const html = renderTab();
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const fresh = $('[data-auto-chips]', tmp);
    if (box && fresh) box.innerHTML = fresh.innerHTML;
  });
}

function compressIndices(list) {
  const out = [];
  const sorted = [...list].sort((a, b) => a - b);
  for (let i = 0; i < sorted.length; i++) {
    const start = sorted[i];
    let end = start;
    while (sorted[i + 1] === end + 1) { end = sorted[++i]; }
    out.push(start === end ? `${start}` : `${start}-${end}`);
  }
  return out.join(',');
}

/* ================= download ================= */
async function download() {
  let items = [];
  let options = { ...S.opts };
  if (S.batch) {
    const urls = [...new Set($('#urls').value.split(/\s+/).filter(isUrl))];
    if (!urls.length) { shake($('#url-card')); toast('Добавьте хотя бы одну ссылку', { type: 'warn' }); return; }
    items = urls.map((url) => ({ url }));
  } else {
    const url = $('#url').value.trim();
    if (!url) { $('#url').focus(); shake($('#url-card')); return; }
    const info = S.info && S.infoUrl === url ? S.info : null;
    if (info && info.is_playlist) {
      const chosen = info.entries.filter((e) => S.entrySel.has(e.index));
      if (!chosen.length) { toast('Выберите хотя бы одно видео', { type: 'warn' }); return; }
      if (S.splitEntries && chosen.every((e) => e.url)) {
        items = chosen.map((e) => ({
          url: e.url,
          meta: { title: e.title, thumbnail: e.thumbnail, duration: e.duration, uploader: e.uploader },
          playlist_title: info.title, playlist_index: e.index, playlist_count: info.count,
        }));
      } else {
        if (chosen.length < info.entries.length) options.playlist_items = compressIndices(chosen.map((e) => e.index));
        items = [{ url, meta: { title: info.title, thumbnail: info.thumbnail, uploader: info.uploader, kind: 'playlist' } }];
      }
    } else if (info) {
      items = [{ url, meta: { title: info.title, thumbnail: info.thumbnail, duration: info.duration, uploader: info.uploader } }];
    } else items = [{ url }];
  }
  const btn = $('#btn-download');
  btn.classList.add('loading');
  try {
    const r = await api('download', { items, options });
    const n = r.created.length;
    toast(n === 1 ? 'Добавлено в очередь' : `Добавлено ${n} ${plural(n, ['задача', 'задачи', 'задач'])}`, {
      sub: items.length === 1 ? (items[0].meta?.title || items[0].url) : '',
      action: { label: 'Очередь', run: () => showPage('queue') },
    });
    burst(btn);
  } catch (e) { toastError(e); } finally { btn.classList.remove('loading'); }
}

function burst(el) {
  const r = el.getBoundingClientRect();
  const colors = ['var(--a1)', 'var(--a2)', 'var(--a3)'];
  for (let i = 0; i < 18; i++) {
    const p = document.createElement('i');
    const size = 5 + Math.random() * 6;
    Object.assign(p.style, {
      position: 'fixed', left: r.left + r.width / 2 + 'px', top: r.top + r.height / 2 + 'px', width: size + 'px', height: size + 'px',
      borderRadius: '50%', background: colors[i % 3], zIndex: 80, pointerEvents: 'none',
    });
    document.body.append(p);
    const a = Math.random() * Math.PI * 2, d = 50 + Math.random() * 90;
    p.animate([{ transform: 'translate(-50%,-50%) scale(1)', opacity: 1 },
      { transform: `translate(calc(-50% + ${Math.cos(a) * d}px), calc(-50% + ${Math.sin(a) * d - 30}px)) scale(.3)`, opacity: 0 }],
    { duration: 650 + Math.random() * 300, easing: 'cubic-bezier(.2,.8,.3,1)' }).onfinish = () => p.remove();
  }
}

/* ================= queue ================= */
const STATUS = {
  queued: 'В очереди', starting: 'Запуск', downloading: 'Загрузка', processing: 'Обработка',
  done: 'Готово', error: 'Ошибка', paused: 'Пауза', cancelled: 'Отменено',
};
const ACTIVE = new Set(['starting', 'downloading', 'processing']);

function taskActions(t) {
  const b = (act, ic, title, cls = '') => `<button class="icon-btn ${cls}" data-act="${act}" title="${title}">${icon(ic)}</button>`;
  const out = [];
  if (t.status === 'done') {
    if (t.files.length) out.push(b('open-file', 'play', 'Открыть файл', 'accent'), b('reveal', 'folder', 'Показать в папке'));
  }
  if (ACTIVE.has(t.status) || t.status === 'queued') out.push(b('pause', 'pause', 'Пауза'));
  if (t.status === 'paused') out.push(b('resume', 'play', 'Продолжить', 'accent'));
  if (t.status === 'error' || t.status === 'cancelled') out.push(b('retry', 'retry', 'Повторить', 'accent'));
  out.push(b('log', 'terminal', 'Журнал'));
  if (ACTIVE.has(t.status) || t.status === 'queued' || t.status === 'paused') out.push(b('cancel', 'x', 'Отменить', 'danger'));
  else out.push(b('remove', 'trash', 'Убрать из списка', 'danger'));
  return out.join('');
}

function createTaskEl(t) {
  const el = document.createElement('div');
  el.dataset.id = t.id;
  el.innerHTML = `
    <div class="thumb">${icon(t.kind === 'audio' ? 'music' : 'film')}<img alt="" referrerpolicy="no-referrer" hidden><span class="kind">${icon(t.kind === 'audio' ? 'music' : t.kind === 'playlist' ? 'layers' : 'film')}</span><span class="pct"></span></div>
    <div class="task-body">
      <div class="task-title"></div>
      <div class="task-meta"><span class="status"></span><span class="stage"></span></div>
      <div class="bar"><div class="fill"></div></div>
      <div class="task-stats"></div>
      <div class="task-error" hidden></div>
    </div>
    <div class="task-actions"></div>`;
  const img = $('img', el);
  img.onload = () => { img.hidden = false; };
  img.onerror = () => { img.hidden = true; };
  return el;
}

function updateTaskEl(el, t) {
  el.className = `task s-${t.status}`;
  const img = $('img', el);
  if (t.thumbnail && img.dataset.src !== t.thumbnail) { img.dataset.src = t.thumbnail; img.src = t.thumbnail; }
  const title = $('.task-title', el);
  if (title.textContent !== t.title) { title.textContent = t.title; title.title = t.title; }
  $('.status', el).textContent = STATUS[t.status] || t.status;
  const bits = [];
  if (t.stage && t.stage !== STATUS[t.status]) bits.push(t.stage);
  if (t.playlist_index) bits.push(`#${t.playlist_index}${t.playlist_count ? ' из ' + t.playlist_count : ''}`);
  if (t.uploader) bits.push(t.uploader);
  $('.stage', el).textContent = bits.join(' · ');
  const pct = t.status === 'done' ? 100 : t.progress;
  $('.fill', el).style.width = `${pct}%`;
  $('.pct', el).textContent = t.status === 'processing' ? '⚙' : `${Math.floor(pct)}%`;
  const stats = [];
  if (t.status === 'downloading') {
    if (t.total) stats.push(`<span>${icon('download')}${fmtBytes(t.downloaded)} / ${fmtBytes(t.total)}</span>`);
    if (t.speed) stats.push(`<span>${icon('zap')}${fmtSpeed(t.speed)}</span>`);
    if (t.eta != null) stats.push(`<span>${icon('clock')}${fmtDuration(t.eta)}</span>`);
  } else if (t.status === 'done') {
    if (t.files.length) stats.push(`<span>${icon('folder')}${esc(basename(t.files[t.files.length - 1]))}${t.files.length > 1 ? ` <span class="muted">+${t.files.length - 1}</span>` : ''}</span>`);
    if (t.started && t.finished) stats.push(`<span>${icon('clock')}${fmtDuration(t.finished - t.started)}</span>`);
  } else if (t.duration) stats.push(`<span>${icon('clock')}${fmtDuration(t.duration)}</span>`);
  const statsHtml = stats.join('');
  const statsEl = $('.task-stats', el);
  if (statsEl.innerHTML !== statsHtml) statsEl.innerHTML = statsHtml;
  const err = $('.task-error', el);
  err.hidden = !(t.status === 'error' && t.error);
  err.textContent = t.error || '';
  const actions = $('.task-actions', el);
  const key = `${t.status}|${t.files.length}`;
  if (actions.dataset.key !== key) { actions.dataset.key = key; actions.innerHTML = taskActions(t); }
}

function renderTasks() {
  const list = $('#task-list');
  const tasks = [...S.tasks].sort((a, b) => b.created - a.created);
  const ids = new Set(tasks.map((t) => t.id));
  [...list.children].forEach((el) => { if (!ids.has(el.dataset.id)) el.remove(); });
  const existing = new Map([...list.children].map((el) => [el.dataset.id, el]));
  tasks.forEach((t, i) => {
    let el = existing.get(t.id);
    if (!el) el = createTaskEl(t);
    updateTaskEl(el, t);
    if (list.children[i] !== el) list.insertBefore(el, list.children[i] || null);
  });

  $('#queue-empty').hidden = tasks.length > 0;
  const active = tasks.filter((t) => ACTIVE.has(t.status));
  const queued = tasks.filter((t) => t.status === 'queued');
  const done = tasks.filter((t) => t.status === 'done');
  const pending = active.length + queued.length;
  const badge = $('#badge-queue');
  badge.hidden = pending === 0;
  badge.textContent = pending;
  $('#queue-summary').textContent = tasks.length
    ? [active.length && `${active.length} активн.`, queued.length && `${queued.length} ждут`, done.length && `${done.length} готово`].filter(Boolean).join(' · ') || `${tasks.length} ${plural(tasks.length, ['задача', 'задачи', 'задач'])}`
    : 'Пока пусто';

  // sidebar live activity
  const side = $('#side-activity');
  side.hidden = active.length === 0;
  const speed = active.reduce((s, t) => s + (t.speed || 0), 0);
  $('#side-speed').textContent = speed ? fmtSpeed(speed) : '';
  $('#side-list').innerHTML = active.slice(0, 4).map((t) => `
    <div class="side-item s-${t.status}" data-goto="queue"><span>${esc(t.title)}</span><div class="bar"><div class="fill" style="width:${t.status === 'starting' ? 8 : t.progress}%"></div></div></div>`).join('');
  document.title = active.length ? `${Math.round(active.reduce((s, t) => s + t.progress, 0) / active.length)}% · YT-DLP Studio` : 'YT-DLP Studio';
}

function handleTasks(tasks) {
  for (const t of tasks) {
    const prev = S.prevStatus[t.id];
    if (prev && prev !== t.status) {
      if (t.status === 'done') notifyDone(t);
      if (t.status === 'error') {
        toast('Ошибка загрузки', { type: 'error', sub: `${t.title}: ${t.error || ''}`, timeout: 8000, action: { label: 'Журнал', run: () => openLog(t.id) } });
      }
    }
    S.prevStatus[t.id] = t.status;
  }
  S.tasks = tasks;
  renderTasks();
}

function notifyDone(t) {
  toast('Загрузка завершена', {
    sub: t.title,
    action: t.files.length ? { label: 'Показать', run: () => api('open', { path: t.files[t.files.length - 1], reveal: true }).catch(toastError) } : null,
  });
  if (S.app.notify && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
    try { new Notification('Загрузка завершена', { body: t.title, icon: 'icon.svg', silent: false }); } catch { /* ignore */ }
  }
}

async function taskAction(id, act) {
  const t = S.tasks.find((x) => x.id === id);
  try {
    if (act === 'open-file') await api('open', { path: t.files[t.files.length - 1] });
    else if (act === 'reveal') await api('open', { path: t.files[t.files.length - 1], reveal: true });
    else if (act === 'log') await openLog(id);
    else await api(`tasks/${id}/${act}`, {});
  } catch (e) { toastError(e); }
}

/* ================= log modal ================= */
let logTimer = null;
async function openLog(id) {
  const modal = $('#modal');
  const load = async () => {
    const t = await api(`tasks/${id}/log`);
    $('#modal-title').textContent = t.title;
    $('#modal-sub').textContent = `${STATUS[t.status] || t.status} · ${t.url}`;
    const body = $('#modal-body');
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    body.innerHTML = t.log.map((l) => {
      const msg = esc(l.msg).replace(/^\[([\w:+-]+)\]/, '<span class="tg">[$1]</span>');
      return `<div class="log-line ${l.level}">${msg}</div>`;
    }).join('') || '<div class="log-line">Журнал пуст</div>';
    if (atBottom) body.scrollTop = body.scrollHeight;
    S.logText = t.log.map((l) => l.msg).join('\n');
    return t;
  };
  const t = await load();
  modal.hidden = false;
  $('#modal-body').scrollTop = $('#modal-body').scrollHeight;
  clearInterval(logTimer);
  if (ACTIVE.has(t.status) || t.status === 'queued') {
    logTimer = setInterval(() => load().then((x) => { if (!ACTIVE.has(x.status) && x.status !== 'queued') clearInterval(logTimer); }).catch(() => clearInterval(logTimer)), 1000);
  }
}
function closeModal() { $('#modal').hidden = true; clearInterval(logTimer); }

/* ================= history ================= */
async function refreshHistory() {
  try {
    const st = await api('state');
    S.history = st.history;
    S.historyCount = st.history.length;
    renderHistory();
  } catch { /* offline */ }
}

function dayLabel(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff === 0) return 'Сегодня';
  if (diff === 1) return 'Вчера';
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' });
}

function renderHistory() {
  const q = $('#history-search').value.trim().toLowerCase();
  const items = S.history.filter((h) => !q || `${h.title} ${h.uploader} ${h.url}`.toLowerCase().includes(q));
  const badge = $('#badge-history');
  badge.hidden = S.history.length === 0;
  badge.textContent = S.history.length;
  $('#history-empty').hidden = items.length > 0;
  $('#history-summary').textContent = S.history.length ? `${S.history.length} ${plural(S.history.length, ['запись', 'записи', 'записей'])}` : '';
  let lastDay = '';
  const html = [];
  for (const h of items) {
    const label = dayLabel(h.finished || 0);
    if (label !== lastDay) { html.push(`<div class="h-date">${esc(label)}</div>`); lastDay = label; }
    const file = (h.files || [])[h.files.length - 1];
    html.push(`
      <div class="h-item" data-hid="${esc(h.id)}">
        <div class="thumb">${icon(h.kind === 'audio' ? 'music' : 'film')}${h.thumbnail ? `<img src="${esc(h.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}</div>
        <div class="h-body">
          <b title="${esc(h.title)}">${esc(h.title)}</b>
          <small>
            ${h.uploader ? `<span>${esc(h.uploader)}</span>` : ''}
            ${h.duration ? `<span>${fmtDuration(h.duration)}</span>` : ''}
            <span>${new Date((h.finished || 0) * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</span>
            ${file ? `<span title="${esc(file)}">${esc(basename(file))}</span>` : ''}
            ${h.status === 'error' ? `<span class="err">${esc(h.error || 'ошибка')}</span>` : ''}
          </small>
        </div>
        <div class="task-actions">
          ${file ? `<button class="icon-btn accent" data-hact="open" title="Открыть файл">${icon('play')}</button><button class="icon-btn" data-hact="reveal" title="Показать в папке">${icon('folder')}</button>` : ''}
          <button class="icon-btn" data-hact="again" title="Скачать снова с текущими настройками">${icon('retry')}</button>
          <button class="icon-btn" data-hact="copy" title="Копировать ссылку">${icon('link')}</button>
          <button class="icon-btn danger" data-hact="remove" title="Удалить из истории">${icon('trash')}</button>
        </div>
      </div>`);
  }
  $('#history-list').innerHTML = html.join('');
}

async function historyAction(id, act) {
  const h = S.history.find((x) => x.id === id);
  if (!h) return;
  const file = (h.files || [])[h.files.length - 1];
  try {
    if (act === 'open') await api('open', { path: file });
    if (act === 'reveal') await api('open', { path: file, reveal: true });
    if (act === 'copy') copyText(h.url, 'Ссылка скопирована');
    if (act === 'again') {
      await api('download', { items: [{ url: h.url, meta: { title: h.title, thumbnail: h.thumbnail, uploader: h.uploader, duration: h.duration } }], options: S.opts });
      toast('Добавлено в очередь', { sub: h.title, action: { label: 'Очередь', run: () => showPage('queue') } });
    }
    if (act === 'remove') {
      await api('history/remove', { id });
      S.history = S.history.filter((x) => x.id !== id);
      renderHistory();
    }
  } catch (e) { toastError(e); }
}

/* ================= environment / update ================= */
function renderEnv(st) {
  S.env = st;
  $('#ver').textContent = `yt-dlp ${st.version}`;
  $('#kv-ytdlp').textContent = st.version;
  $('#kv-python').textContent = st.python;
  $('#kv-ffmpeg').textContent = st.ffmpeg || 'не найден';
  $('#kv-config').textContent = st.config_dir;
  const pill = $('#ffmpeg-pill');
  pill.classList.toggle('ok', !!st.ffmpeg);
  pill.classList.toggle('bad', !st.ffmpeg);
  pill.title = st.ffmpeg ? `ffmpeg: ${st.ffmpeg}` : 'ffmpeg не найден — нажмите, чтобы узнать, как установить';
  $('#ffmpeg-help').hidden = !!st.ffmpeg;
  renderUpdate(st.update);
}

let updateWasRunning = false;
function renderUpdate(u) {
  if (!u) return;
  const btn = $('#btn-update');
  btn.classList.toggle('loading', !!u.running);
  btn.querySelector('span').textContent = u.running ? 'Обновление…' : 'Обновить yt-dlp';
  const log = $('#update-log');
  log.hidden = !u.output;
  log.textContent = u.output || '';
  if (updateWasRunning && !u.running) {
    if (u.ok) toast('yt-dlp обновлён', { sub: 'Перезапустите приложение, чтобы применить', timeout: 12000, action: { label: 'Перезапустить', run: restartApp } });
    else toast('Не удалось обновить yt-dlp', { type: 'error', sub: 'Подробности — в настройках' });
  }
  updateWasRunning = !!u.running;
}

async function restartApp() {
  try {
    await api('restart', {});
  } catch (e) { toastError(e); return; }
  toast('Перезапуск…', { type: 'info', timeout: 15000 });
  const started = Date.now();
  const wait = async () => {
    try { await api('state'); location.reload(); } catch { if (Date.now() - started < 30000) setTimeout(wait, 700); }
  };
  setTimeout(wait, 1200);
}

/* ================= events stream ================= */
function connectEvents() {
  const es = new EventSource('/api/events?token=' + encodeURIComponent(TOKEN));
  es.onmessage = (e) => {
    const d = JSON.parse(e.data);
    handleTasks(d.tasks);
    renderUpdate(d.update);
    if (d.history_count !== S.historyCount) { S.historyCount = d.history_count; refreshHistory(); }
  };
}

/* ================= misc ================= */
async function copyText(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); } catch {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.append(ta); ta.select();
    try { document.execCommand('copy'); toast(msg); } catch { toast('Не удалось скопировать', { type: 'error' }); }
    ta.remove();
  }
}

function setUrl(url, { go = true } = {}) {
  if (S.batch) {
    const ta = $('#urls');
    ta.value = (ta.value.trim() ? ta.value.trim() + '\n' : '') + url;
    ta.dispatchEvent(new Event('input'));
    return;
  }
  $('#url').value = url;
  $('#url').dispatchEvent(new Event('input'));
  showPage('download');
  if (go) analyze();
}

function setBatch(on) {
  S.batch = on;
  $('#batch-toggle').checked = on;
  $('#url-single').hidden = on;
  $('#url-batch').hidden = !on;
  if (on) {
    const u = $('#url').value.trim();
    if (u && !$('#urls').value.includes(u)) $('#urls').value = u;
    $('#urls').dispatchEvent(new Event('input'));
    $('#urls').focus();
  }
  $('#btn-download span').textContent = on ? 'Скачать всё' : 'Скачать';
  refreshCommand();
}

async function checkClipboard() {
  if (!S.app.clipboard_watch || !navigator.clipboard?.readText) return;
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (isUrl(text) && text !== S.lastClip && text !== $('#url').value.trim()) {
      S.lastClip = text;
      toast('Ссылка в буфере обмена', { type: 'info', sub: text, timeout: 8000, action: { label: 'Вставить', run: () => setUrl(text) } });
    }
  } catch { /* permission denied */ }
}

function bindUI() {
  $$('.nav-item').forEach((b) => b.addEventListener('click', () => showPage(b.dataset.page)));
  document.addEventListener('click', (e) => {
    const g = e.target.closest('[data-goto]');
    if (g) showPage(g.dataset.goto);
  });

  const url = $('#url');
  url.addEventListener('input', () => { $('#btn-clear-url').hidden = !url.value; refreshCommand(); });
  url.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); download(); } else if (e.key === 'Enter') analyze();
  });
  url.addEventListener('paste', () => setTimeout(() => { if (isUrl(url.value)) analyze(); }, 0));
  $('#btn-clear-url').addEventListener('click', () => { url.value = ''; url.dispatchEvent(new Event('input')); S.info = null; renderPreview(); url.focus(); });
  $('#btn-paste').addEventListener('click', async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) { toast('Буфер обмена пуст', { type: 'warn' }); return; }
      if (S.batch) setUrl(text); else { url.value = text; url.dispatchEvent(new Event('input')); if (isUrl(text)) analyze(); }
    } catch { url.focus(); toast('Нажмите Ctrl+V, чтобы вставить', { type: 'info' }); }
  });
  $('#btn-analyze').addEventListener('click', analyze);
  $('#btn-download').addEventListener('click', download);
  $('#batch-toggle').addEventListener('change', (e) => setBatch(e.target.checked));
  $('#urls').addEventListener('input', () => {
    const n = $('#urls').value.split(/\s+/).filter(isUrl).length;
    $('#batch-count').textContent = `${n} ${plural(n, ['ссылка', 'ссылки', 'ссылок'])}`;
    refreshCommand();
  });
  $('#urls').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); download(); } });
  $('#btn-copy-cmd').addEventListener('click', () => copyText(S.command || $('#cmd').textContent, 'Команда скопирована'));

  // global paste of a link anywhere outside inputs
  document.addEventListener('paste', (e) => {
    if (e.target.closest('input, textarea, [contenteditable]')) return;
    const text = (e.clipboardData?.getData('text') || '').trim();
    if (isUrl(text)) { e.preventDefault(); setUrl(text); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#modal').hidden) closeModal();
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && $('#page-download').classList.contains('active') && !e.target.closest('#url, #urls')) download();
  });

  // drag & drop links
  let dragDepth = 0;
  const overlay = $('#drop-overlay');
  window.addEventListener('dragenter', (e) => {
    if (![...(e.dataTransfer?.types || [])].some((t) => t === 'text/uri-list' || t === 'text/plain')) return;
    dragDepth++; overlay.classList.add('show');
  });
  window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) overlay.classList.remove('show'); });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    dragDepth = 0; overlay.classList.remove('show');
    const raw = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain') || '';
    const urls = raw.split(/\s+/).filter(isUrl);
    if (!urls.length) { toast('Это не похоже на ссылку', { type: 'warn' }); return; }
    if (urls.length > 1 && !S.batch) setBatch(true);
    if (S.batch) urls.forEach((u) => setUrl(u)); else setUrl(urls[0]);
  });

  // queue
  $('#task-list').addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]');
    if (b) taskAction(b.closest('[data-id]').dataset.id, b.dataset.act);
  });
  $('#btn-pause-all').addEventListener('click', () => api('queue/pause', {}).catch(toastError));
  $('#btn-resume-all').addEventListener('click', () => api('queue/resume', {}).catch(toastError));
  $('#btn-clear-done').addEventListener('click', () => api('queue/clear', {}).catch(toastError));

  // history
  $('#history-search').addEventListener('input', debounce(renderHistory, 150));
  $('#history-list').addEventListener('error', (e) => { if (e.target.tagName === 'IMG') e.target.remove(); }, true);
  $('#history-list').addEventListener('click', (e) => {
    const b = e.target.closest('[data-hact]');
    if (b) historyAction(b.closest('[data-hid]').dataset.hid, b.dataset.hact);
  });
  $('#btn-clear-history').addEventListener('click', async () => {
    if (!S.history.length || !confirm('Очистить всю историю загрузок? Сами файлы не будут удалены.')) return;
    try { await api('history/clear', {}); S.history = []; renderHistory(); } catch (e) { toastError(e); }
  });

  // modal
  $('#modal-close').addEventListener('click', closeModal);
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
  $('#modal-copy').addEventListener('click', () => copyText(S.logText || '', 'Журнал скопирован'));

  // settings
  $('#theme-toggle').addEventListener('click', () => setApp('theme', document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  $('#ffmpeg-pill').addEventListener('click', () => { if (!S.env.ffmpeg) showPage('settings'); });
  $('#btn-update').addEventListener('click', () => api('update', {}).catch(toastError));
  $('#btn-restart').addEventListener('click', restartApp);
  $('#btn-reset-opts').addEventListener('click', async () => {
    if (!confirm('Вернуть все параметры загрузки к значениям по умолчанию?')) return;
    try {
      const r = await api('settings/reset', {});
      S.opts = r.options;
      syncOptions();
      updateCommand();
      toast('Параметры сброшены');
    } catch (e) { toastError(e); }
  });

  window.addEventListener('focus', checkClipboard);
}

/* ================= boot ================= */
async function init() {
  try {
    const st = await api('state');
    S.opts = st.settings.options;
    S.app = st.settings.app;
    S.defaults = st.defaults;
    S.prevMode = S.opts.mode === 'custom' ? 'video' : S.opts.mode;
    S.history = st.history;
    S.historyCount = st.history.length;
    renderEnv(st);
    applyApp();
    bindOptions();
    bindPreview();
    bindUI();
    syncOptions();
    st.tasks.forEach((t) => { S.prevStatus[t.id] = t.status; });
    handleTasks(st.tasks);
    renderHistory();
    showPage(store.get('page', 'download'));
    updateCommand();
    connectEvents();
    if (document.hasFocus()) checkClipboard();
    $('#url').focus();
  } catch (e) {
    document.body.innerHTML = `<div class="empty" style="height:100vh;justify-content:center"><b>Нет связи с приложением</b><p>${esc(e.message)}. Запустите приложение заново и обновите страницу.</p></div>`;
  }
}

init();
