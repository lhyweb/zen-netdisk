/* 局域网网盘 · 前端逻辑
   语言：文案统一走 t('key')（lang_zh.js / lang_en.js），cookie lang=zh|en 切换 */
'use strict';

/* ---------- 通用工具 ---------- */
function getCookie(n) {
  const m = document.cookie.match(new RegExp('(^|; )' + n + '=([^;]*)'));
  return m ? decodeURIComponent(m[2]) : '';
}
function curLang() { return getCookie('lang') === 'en' ? 'en' : 'zh'; }
function t(k) {
  const d = curLang() === 'en' ? (window.LANG_EN || {}) : (window.LANG_ZH || {});
  return d[k] !== undefined ? d[k] : k;
}
function setLang(l) {
  document.cookie = 'lang=' + l + '; path=/; max-age=31536000';
  location.reload();
}
async function api(url, opts) {
  opts = opts || {};
  opts.headers = opts.headers || {};
  opts.headers['X-Xsrftoken'] = getCookie('_xsrf');
  const r = await fetch(url, opts);
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('json')) return r.json();
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r;
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtSize(n) {
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + ' GB';
  if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}
function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = x => String(x).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}
function show(id) { document.getElementById(id).classList.remove('hidden'); }
function hide(id) { document.getElementById(id).classList.add('hidden'); }
function saveBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
/* 文件类型图标：统一用基础 emoji + U+FE0F，跨平台彩色渲染一致 */
function fileIcon(prev) {
  if (prev === 'image') return '📷️';
  if (prev === 'pdf') return '📕️';
  if (prev === 'text') return '📃️';
  return '📄️';
}

/* ---------- 自定义弹窗（替代浏览器原生 alert/confirm/prompt：虚化背景 + 居中卡片） ---------- */
function openDialog(html, btns) {
  // btns: [{text, cls, value}]，value: 'ok'/'cancel' 或任意字符串
  return new Promise(resolve => {
    const ov = document.createElement('div');
    ov.className = 'overlay';
    ov.innerHTML = '<div class="modal dialog-box">' + html +
      '<div class="row dialog-btns">' +
      btns.map(b => '<button class="btn ' + (b.cls || '') + '" data-v="' + b.value + '">' + b.text + '</button>').join('') +
      '</div></div>';
    document.body.appendChild(ov);
    function done(v) { ov.remove(); document.removeEventListener('keydown', escKey); resolve(v); }
    function escKey(e) { if (e.key === 'Escape') done(null); }
    document.addEventListener('keydown', escKey);
    ov.addEventListener('click', ev => {
      if (ev.target === ov) { done(null); return; }
      const b = ev.target.closest('button[data-v]');
      if (b) done(b.dataset.v);
    });
  });
}
function dialogAlert(msg) {
  return openDialog('<h3>' + esc(t('hint')) + '</h3><p>' + esc(msg) + '</p>',
    [{ text: t('ok'), cls: 'primary', value: 'ok' }]);
}
function dialogConfirm(msg) {
  return openDialog('<h3>' + esc(t('confirm')) + '</h3><p>' + esc(msg) + '</p>',
    [{ text: t('cancel'), value: 'cancel' }, { text: t('ok'), cls: 'primary', value: 'ok' }])
    .then(v => v === 'ok');
}
function dialogPrompt(label, def, isPwd) {
  // 输入弹窗：返回输入字符串；取消返回 null
  return new Promise(resolve => {
    const tp = isPwd ? 'password' : 'text';
    const ov = document.createElement('div');
    ov.className = 'overlay';
    ov.innerHTML = '<div class="modal dialog-box"><h3>' + esc(label) + '</h3>' +
      '<input type="' + tp + '" value="' + esc(def || '') + '">' +
      '<div class="row dialog-btns">' +
      '<button class="btn" data-v="cancel">' + t('cancel') + '</button>' +
      '<button class="btn primary" data-v="ok">' + t('ok') + '</button></div></div>';
    document.body.appendChild(ov);
    const inp = ov.querySelector('input');
    inp.focus(); inp.select();
    function done(v) { ov.remove(); document.removeEventListener('keydown', escKey); resolve(v); }
    function escKey(e) { if (e.key === 'Escape') done(null); }
    document.addEventListener('keydown', escKey);
    ov.addEventListener('click', ev => {
      if (ev.target === ov) { done(null); return; }
      const b = ev.target.closest('button[data-v]');
      if (b) done(b.dataset.v === 'ok' ? inp.value : null);
    });
    inp.addEventListener('keydown', ev => {
      if (ev.key === 'Enter') done(inp.value);
    });
  });
}
function dialogPrompt2(label1, label2, isPwd) {
  // 双输入弹窗（如密码二次确认）：返回 [v1, v2]；取消返回 null
  return new Promise(resolve => {
    const tp = isPwd ? 'password' : 'text';
    const ov = document.createElement('div');
    ov.className = 'overlay';
    ov.innerHTML = '<div class="modal dialog-box"><h3>' + esc(label1) + '</h3>' +
      '<div class="dp-field"><label>' + esc(label1) + '</label><input type="' + tp + '"></div>' +
      '<div class="dp-field"><label>' + esc(label2) + '</label><input type="' + tp + '"></div>' +
      '<p class="dp-err hidden"></p>' +
      '<div class="row dialog-btns">' +
      '<button class="btn" data-v="cancel">' + t('cancel') + '</button>' +
      '<button class="btn primary" data-v="ok">' + t('ok') + '</button></div></div>';
    document.body.appendChild(ov);
    const ins = ov.querySelectorAll('input');
    ins[0].focus();
    function done(v) { ov.remove(); document.removeEventListener('keydown', escKey); resolve(v); }
    function escKey(e) { if (e.key === 'Escape') done(null); }
    document.addEventListener('keydown', escKey);
    ov.addEventListener('click', ev => {
      if (ev.target === ov) { done(null); return; }
      const b = ev.target.closest('button[data-v]');
      if (!b) return;
      if (b.dataset.v === 'cancel') { done(null); return; }
      if (ins[0].value !== ins[1].value) {
        const err = ov.querySelector('.dp-err');
        err.textContent = t('pw_mismatch');
        err.classList.remove('hidden');
        return;
      }
      done([ins[0].value, ins[1].value]);
    });
    ins[1].addEventListener('keydown', ev => {
      if (ev.key !== 'Enter') return;
      if (ins[0].value !== ins[1].value) {
        const err = ov.querySelector('.dp-err');
        err.textContent = t('pw_mismatch');
        err.classList.remove('hidden');
        return;
      }
      done([ins[0].value, ins[1].value]);
    });
  });
}

/* ---------- 状态 ---------- */
let curDir = '';
let sel = new Set();       // 已选中的文件相对路径（多选批量操作）
let files = [];
let currentText = null;    // 文本编辑状态 {path, encoding}
let sortKey = 'mtime';     // 排序：默认按修改时间倒序
let sortDir = -1;
let lightboxList = [];     // 图片预览翻页列表（当前目录可见图片的相对路径）
let lightboxIdx = 0;

/* ---------- 文件列表（排序：名称/大小/修改时间/上传者/可见性） ---------- */
const sortFns = {
  name: f => (f.name || '').toLowerCase(),
  size: f => f.is_dir ? -1 : f.size,
  mtime: f => f.is_dir ? -1 : f.mtime,
  owner: f => (f.owner || '').toLowerCase(),
  vis: f => f.visibility || 'public'
};
function sortFiles(list) {
  return [...list].sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;   // 文件夹始终在前
    const av = sortFns[sortKey](a), bv = sortFns[sortKey](b);
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return (a.name || '').localeCompare(b.name || '');
  });
}
function setSort(key) {
  if (key === sortKey) sortDir = -sortDir;
  else { sortKey = key; sortDir = (key === 'name' || key === 'vis') ? 1 : -1; }
  renderSortMark();
  renderList();
}
function renderSortMark() {
  ['name', 'size', 'mtime', 'owner', 'vis'].forEach(k => {
    const el = document.getElementById('sm-' + k);
    if (el) el.textContent = (k === sortKey) ? (sortDir === 1 ? '▲' : '▼') : '';
  });
}

/* ---------- 文件列表 ---------- */
async function loadList() {
  const q = document.getElementById('search').value.trim();
  const url = '/api/list?path=' + encodeURIComponent(curDir) + (q ? '&q=' + encodeURIComponent(q) : '');
  const d = await api(url);
  if (!d.ok) { dialogAlert(d.error || t('hint')); return; }
  files = d.items;
  renderCrumbs(d.dir, d.parent);
  renderSortMark();
  renderList();
}

function renderCrumbs(dir) {
  const el = document.getElementById('crumbs');
  el.innerHTML = '';
  const root = document.createElement('a');
  root.className = 'crumb-btn crumb-home' + (curDir ? '' : ' crumb-current');
  root.textContent = t('home'); root.href = '#';
  root.onclick = () => { curDir = ''; loadList(); };
  el.appendChild(root);
  if (!dir) return;
  const parts = dir.split('/'); let acc = '';
  for (const p of parts) {
    acc = acc ? acc + '/' + p : p;
    const sep = document.createElement('span');
    sep.className = 'crumb-sep'; sep.textContent = '›';
    el.appendChild(sep);
    const a = document.createElement('a');
    a.className = 'crumb-btn' + (acc === curDir ? ' crumb-current' : '');
    a.textContent = p; a.href = '#';
    a.onclick = () => { curDir = acc; loadList(); };
    el.appendChild(a);
  }
}

function visTag(f) {
  // 私有/公开统一两字显示（文字宽度一致，表格不抖动），用颜色区分
  const label = f.visibility === 'private' ? t('private') : t('public');
  if (!f.can_manage) return '<span class="vis-tag ' + (f.visibility || 'public') + '">' + label + '</span>';
  return '<span class="vis-tag ' + (f.visibility || 'public') + '" data-act="toggle" title="' + t('toggle_vis_title') + '">' + label + '</span>';
}

function actions(f) {
  let s = '';
  if (f.preview !== 'none') s += '<button class="act" data-act="preview">' + t('preview') + '</button>';
  s += '<button class="act" data-act="download">' + t('download') + '</button>';
  if (f.can_share) s += '<button class="act" data-act="share">' + t('share') + '</button>';
  if (f.can_manage) {
    if (f.preview === 'text') s += '<button class="act" data-act="edit">' + t('edit') + '</button>';
    s += '<button class="act danger" data-act="del">' + t('delete') + '</button>';
  }
  return s;
}

function renderList() {
  const tb = document.getElementById('fileBody');
  tb.innerHTML = '';
  document.getElementById('emptyTip').classList.toggle('hidden', files.length > 0);
  document.getElementById('checkAll').checked = false;
  for (const f of sortFiles(files)) {
    const tr = document.createElement('tr');
    tr.dataset.path = f.path;
    tr.dataset.isDir = f.is_dir ? '1' : '0';
    tr.dataset.preview = f.preview;
    tr.dataset.vis = f.visibility || 'public';
    const cb = '<td class="ck"><input type="checkbox" data-check="1"></td>';
    const nameCell = f.is_dir
      ? '<td class="name"><span class="icon">📁️</span><a class="fname" href="#">' + esc(f.name) + '</a></td>'
      : '<td class="name"><span class="icon">' + fileIcon(f.preview) + '</span><a class="fname" href="#">' + esc(f.name) + '</a></td>';
    const size = f.is_dir ? '—' : fmtSize(f.size);
    const mtime = f.is_dir ? '—' : fmtTime(f.mtime);
    const owner = f.is_dir ? '—' : esc(f.owner || '');
    const vis = f.is_dir ? '—' : visTag(f);
    tr.innerHTML = cb + nameCell +
      '<td class="num">' + size + '</td><td class="num">' + mtime + '</td>' +
      '<td>' + owner + '</td><td>' + vis + '</td>' +
      '<td class="ops">' + (f.is_dir ? '' : actions(f)) + '</td>';
    tb.appendChild(tr);
  }
}

/* 事件委托：名称跳转 / 各类操作（仅文件页存在 #fileBody） */
(function () {
  const tb = document.getElementById('fileBody');
  if (!tb) return;
  tb.addEventListener('click', function (ev) {
  const tr = ev.target.closest('tr');
  if (!tr) return;
  const path = tr.dataset.path;
  const isDir = tr.dataset.isDir === '1';
  const nameLink = ev.target.closest('a.fname');
  if (nameLink) {
    ev.preventDefault();
    if (isDir) { curDir = path; loadList(); }
    else openFile(path, tr.dataset.preview);
    return;
  }
  const tag = ev.target.closest('[data-act]');
  if (!tag) return;
  const act = tag.dataset.act;
  if (act === 'preview') openFile(path, tr.dataset.preview);
  else if (act === 'download') location.href = '/api/download?path=' + encodeURIComponent(path);
  else if (act === 'share') showShare(path);
  else if (act === 'del') delOne(path);
  else if (act === 'edit') openText(path, true);
  else if (act === 'toggle') toggleVis(path);
  });
})();

/* ---------- 文件打开 / 预览（图片支持上下张切换） ---------- */
function openFile(path, prev) {
  const url = '/api/download?path=' + encodeURIComponent(path);
  if (prev === 'image') {
    lightboxList = files.filter(f => !f.is_dir && f.preview === 'image').map(f => f.path);
    const i = lightboxList.indexOf(path);
    lightboxIdx = i >= 0 ? i : 0;
    showLightbox();
    return;
  }
  if (prev === 'pdf') { window.open(url + '&inline=1', '_blank'); return; }
  if (prev === 'text') { openText(path, false); return; }
  location.href = url;
}

function showLightbox() {
  if (!lightboxList.length) return;
  const path = lightboxList[lightboxIdx];
  document.getElementById('lightboxImg').src = '/api/download?path=' + encodeURIComponent(path) + '&inline=1';
  const multi = lightboxList.length > 1;
  document.getElementById('lbPrev').classList.toggle('hidden', !multi);
  document.getElementById('lbNext').classList.toggle('hidden', !multi);
  show('lightbox');
}
function lbPrev() { if (lightboxList.length) { lightboxIdx = (lightboxIdx - 1 + lightboxList.length) % lightboxList.length; showLightbox(); } }
function lbNext() { if (lightboxList.length) { lightboxIdx = (lightboxIdx + 1) % lightboxList.length; showLightbox(); } }
function closeLightbox() { hide('lightbox'); document.getElementById('lightboxImg').src = ''; }
document.addEventListener('keydown', function (e) {
  if (document.getElementById('lightbox').classList.contains('hidden')) return;
  if (e.key === 'ArrowLeft') lbPrev();
  else if (e.key === 'ArrowRight') lbNext();
  else if (e.key === 'Escape') closeLightbox();
});

/* ---------- 公告（全局，管理员维护） ---------- */
async function openNotice() {
  const d = await api('/api/notice');
  openNoticeWith(d);
}
function openNoticeWith(d) {
  if (!d || !d.ok) return;
  document.getElementById('noticeTitle').textContent = d.title || t('notice');
  const body = document.getElementById('noticeBody');
  if (d.body) body.innerHTML = d.body;          // 服务端已白名单过滤，安全
  else body.innerHTML = '<p class="muted">' + t('no_notice') + '</p>';
  show('noticeBox');
}
function closeNotice() { hide('noticeBox'); }
async function maybeAutoNotice() {
  try {
    const d = await api('/api/notice');
    if (d.ok && d.enabled && d.body && !sessionStorage.getItem('noticeShown')) {
      sessionStorage.setItem('noticeShown', '1');   // 每次登录弹一次（登录页已清标志）
      openNoticeWith(d);
    }
  } catch (e) {}
}

/* ---------- 文本预览 / 编辑 ---------- */
async function openText(path, edit) {
  const d = await api('/api/text?path=' + encodeURIComponent(path));
  if (!d.ok) { dialogAlert(d.error); return; }
  document.getElementById('textTitle').textContent = d.name;
  const ta = document.getElementById('textArea');
  ta.value = d.content;
  const canEdit = d.can_edit && edit;
  ta.readOnly = !canEdit;
  document.getElementById('textOps').style.display = canEdit ? 'flex' : 'none';
  currentText = { path: path, encoding: d.encoding };
  show('textBox');
}
async function saveText() {
  const d = await api('/api/text', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: currentText.path, content: document.getElementById('textArea').value, encoding: currentText.encoding })
  });
  if (d.ok) hideText(); else dialogAlert(d.error);
}
function hideText() { hide('textBox'); currentText = null; }

/* ---------- 可见性 ---------- */
async function toggleVis(path) {
  const row = [...document.querySelectorAll('#fileBody tr')].find(r => r.dataset.path === path);
  const next = row && row.dataset.vis === 'private' ? 'public' : 'private';
  const d = await api('/api/visibility', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: [path], visibility: next })
  });
  if (d.ok) loadList(); else dialogAlert(d.error || t('hint'));
}
async function setVis(v) {
  if (!sel.size) return;
  // 可见性只作用于文件，自动过滤选中的文件夹
  const paths = [];
  document.querySelectorAll('#fileBody tr').forEach(tr => {
    if (tr.dataset.isDir === '1') return;
    if (sel.has(tr.dataset.path)) paths.push(tr.dataset.path);
  });
  if (!paths.length) { dialogAlert(t('sel_files_vis')); return; }
  const d = await api('/api/visibility', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: paths, visibility: v })
  });
  if (d.ok) { clearSel(); loadList(); } else dialogAlert(d.error || t('hint'));
}

/* ---------- 分享 ---------- */
function showShare(path) {
  const f = files.find(x => x.path === path);
  if (!f || !f.share) return;
  document.getElementById('shareUrl').value = location.origin + f.share;
  show('shareBox');
}
function hideShare() { hide('shareBox'); }
async function copyShare() {
  const inp = document.getElementById('shareUrl');
  inp.select();
  try { await navigator.clipboard.writeText(inp.value); } catch (e) {}
  dialogAlert(t('link_copied'));
}

/* ---------- 新建文件夹 ---------- */
async function mkdir() {
  const name = await dialogPrompt(t('new_folder'), '', false);
  if (!name) return;
  const d = await api('/api/mkdir', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dir: curDir, name: name })
  });
  if (d.ok) loadList(); else dialogAlert(d.error || t('hint'));
}

/* ---------- 删除 ---------- */
async function delOne(path) {
  if (!await dialogConfirm(t('del_one_confirm'))) return;
  const d = await api('/api/delete', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: [path] })
  });
  if (d.ok) loadList(); else dialogAlert(d.error || t('hint'));
}
async function delSelected() {
  if (!sel.size) return;
  if (!await dialogConfirm(t('del_sel_confirm').replace('{n}', sel.size))) return;
  const d = await api('/api/delete', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: [...sel] })
  });
  if (d.ok) { clearSel(); loadList(); } else dialogAlert(d.error || t('hint'));
}

/* ---------- 多选 / 批量 ---------- */
(function () {
  const tb = document.getElementById('fileBody');
  if (!tb) return;
  tb.addEventListener('change', function (ev) {
  if (!ev.target.dataset.check) return;
  const tr = ev.target.closest('tr');
  if (!tr) return;
  if (ev.target.checked) sel.add(tr.dataset.path); else sel.delete(tr.dataset.path);
  updateSel();
  });
})();
function toggleAll(c) {
  document.querySelectorAll('#fileBody tr').forEach(tr => {
    const cb = tr.querySelector('input[data-check]');
    if (cb) cb.checked = c;
    if (c) sel.add(tr.dataset.path); else sel.delete(tr.dataset.path);
  });
  updateSel();
}
function updateSel() {
  const bar = document.getElementById('batchBar');
  const show = sel.size > 0;
  bar.classList.toggle('hidden', !show);
  // 批量条出现时隐藏上传提示，批量条隐藏后恢复显示
  const hint = document.getElementById('uploadHint');
  if (hint) hint.classList.toggle('hidden', show);
  document.getElementById('selCount').textContent = t('sel_count').replace('{n}', sel.size);
}
function clearSel() {
  sel.clear();
  document.querySelectorAll('#fileBody input[data-check]').forEach(cb => cb.checked = false);
  document.getElementById('checkAll').checked = false;
  updateSel();
}
async function zipSelected() {
  if (!sel.size) return;
  const r = await api('/api/zip', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: [...sel] })
  });
  const blob = await r.blob();
  saveBlob(blob, 'files_' + Date.now() + '.zip');
}

/* ---------- 上传（跟随当前目录） ---------- */
function pickFiles() { document.getElementById('fileInput').click(); }
function pickFolder() { document.getElementById('folderInput').click(); }

async function uploadFiles(list) {
  for (const f of list) await uploadOne(f, curDir);
  loadList();
}
async function uploadFolder(list) {
  for (const f of list) {
    const rel = f.webkitRelativePath || f.name;
    const parts = rel.split('/');
    const name = parts.pop();
    // 文件夹相对路径拼接在当前打开的目录下
    const dir = (curDir ? curDir + '/' : '') + parts.join('/');
    await uploadOne(f, dir, name);
  }
  loadList();
}
async function uploadOne(file, dir, name) {
  name = name || file.name;
  const hint = document.getElementById('uploadHint');
  hint.textContent = t('uploading').replace('{name}', name);
  const url = '/api/upload?name=' + encodeURIComponent(name) + '&dir=' + encodeURIComponent(dir || '');
  const d = await api(url, { method: 'POST', body: file });
  hint.textContent = d.ok ? '' : t('upload_fail') + (d.error || name);
}

/* ---------- 下拉菜单（用户名 / 语言 / 文件夹，通用） ---------- */
function toggleDrop(id, ev) {
  if (ev) ev.stopPropagation();
  const d = document.getElementById(id);
  if (!d) return;
  const open = d.classList.contains('open');
  closeDrops();
  if (!open) d.classList.add('open');
}
function closeDrops() {
  document.querySelectorAll('.menu-drop.open').forEach(x => x.classList.remove('open'));
}
document.addEventListener('click', closeDrops);

/* ---------- 关于弹窗（作者信息，base64 存储；点击平台名 / 用户名下拉「关于」触发） ---------- */
const ABOUT_B64 = '5beh5a+f5bel5L2c57uE6LWE5paZ5bmz5Y+wCueJiOacrO+8mlYyMDI2MDkK5L2c6ICF77ya6IyC5ZCN5YiG6KGMIOe9l+iIquWuhwrlvIDmupDpobnnm67lnLDlnYDvvJpodHRwczovL2dpdGh1Yi5jb20vbGh5d2ViL3plbi1uZXRkaXNrCgrorr7orqHor7TmmI4KMeOAgeacrOmhueebruS4uuWxgOWfn+e9keaWh+S7tuWNj+S9nOacjeWKoeW5s+WPsO+8jOS7pee9kemhteS9nOS4uuWuouaIt+err++8jOWxgOWfn+e9keWGhemAmui/h+a1j+iniOWZqOWNs+WPr+iuv+mXru+8jOaUr+aMgeaWh+S7tuOAgeaWh+S7tuWkueeahOS4iuS8oOOAgeS4i+i9veS7peWPiuWFqOeUn+WRveWRqOacn+aWh+S7tueuoeeQhuOAggoy44CB6Z2i5ZCR5peg5aSW572R44CB5pegIFNNQi9GVFAg5paH5Lu25YWx5Lqr55qE6ZqU56a75bel5L2c546v5aKD5byA5Y+R77yM5Li76KaB5pyN5Yqh5beh5a+f57uE44CB5qOA5p+l57uE562J5ZCE57G75Li05pe25LiT6aG55bel5L2c57uE77yM5ruh6Laz5bel5L2c57uE5YaF6YOo6LWE5paZ5b2S6ZuG44CB5p2Q5paZ5pW055CG44CB5paH5Lu25Lqk5o2i5YWx5Lqr55qE5Lia5Yqh6ZyA5rGC44CCCjPjgIHmnKzpobnnm67lkI7nq6/ln7rkuo4gUHl0aG9uIOW8gOWPke+8jOW8gOa6kOWMhemZpOS6huagh+WHhuW6k+WkluS7hemHh+eUqCBUb3JuYWRvIFdlYiDmoYbmnrblrp7njrDjgIIKNOOAgemAgumFjeS/oeWIm+OAgee7n+S/oeetieWbveS6p+aTjeS9nOezu+e7n++8m+WGhee9rueUqOaIt+i6q+S7veagoemqjOS4jue7hueykuW6puadg+mZkOeuoeaOp++8jOWujOaVtOeVmeWtmOaWh+S7tuWPmOabtOaXpeW/l+S4jueUqOaIt+aTjeS9nOaXpeW/l++8jOmhueebruS7o+eggeW8gOa6kO+8jOaUr+aMgeW8gOWxleWGhemDqOWuieWFqOWuoeiuoeW3peS9nOOAggo144CBVjIwMjYwOSDkuLrpobnnm67liJ3lp4vniYjmnKzvvIzln7rkuo7lrp7pmYXkuLTml7blt6XkvZzlnLrmma/lvIDlj5HvvIzpooTnlZnmjqXlj6PkvYbmmoLmnKrpgILphY3ooYzlhoXnu5/kuIDouqvku73orqTor4HvvJvlkI7nu63lrozlloTniYjmnKzor7fliY3lvoDlvIDmupDpobnnm67lnLDlnYDojrflj5bmiJbogZTns7vkvZzogIXjgII=';
function showAbout() {
  let txt = '';
  try {
    const bytes = Uint8Array.from(atob(ABOUT_B64), c => c.charCodeAt(0));
    txt = new TextDecoder('utf-8').decode(bytes);
  } catch (e) { txt = t('about_title'); }
  const el = document.getElementById('aboutText');
  if (el) {
    const lines = txt.split('\n');
    let html = '';
    for (const ln of lines) {
      const s = ln.trim();
      if (!s) continue;
      if (/^\d+[、.]/.test(s)) html += '<div class="about-num">' + esc(s) + '</div>';
      else if (s.indexOf('设计说明') === 0) html += '<div class="about-sec">' + esc(s) + '</div>';
      else if (!html) html += '<div class="about-title">' + esc(s) + '</div>';
      else html += '<div class="about-line">' + esc(s) + '</div>';
    }
    el.innerHTML = html;
  }
  const box = document.getElementById('aboutBox');
  if (box) box.classList.remove('hidden');
}
function closeAbout() {
  const box = document.getElementById('aboutBox');
  if (box) box.classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', function () {
  const p = location.pathname;
  if (p === '/') { loadList(); maybeAutoNotice(); }
  else if (p === '/settings') loadMe();
  else if (p === '/admin') showTab('notice');
  // 用户名下拉里的语言切换：给当前语言加 ✓ 标记
  document.querySelectorAll('a[data-lang]').forEach(a => {
    a.classList.toggle('cur', a.dataset.lang === curLang());
  });
});

/* ---------- 设置页 ---------- */
async function loadMe() {
  const d = await api('/api/me');
  if (!d.ok) return;
  document.getElementById('myUsername').value = d.username;
  document.getElementById('myDisplayName').value = d.display_name;
}
async function saveDisplay() {
  const d = await api('/api/display-name', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: document.getElementById('myDisplayName').value })
  });
  if (d.ok) dialogAlert(t('saved')); else dialogAlert(d.error || t('hint'));
}
async function changePw() {
  const d = await api('/api/password', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old: document.getElementById('oldPw').value, new: document.getElementById('newPw').value })
  });
  document.getElementById('pwMsg').textContent = d.ok ? t('pw_changed') : (d.error || t('hint'));
}

/* ---------- 管理后台 ---------- */
function showTab(n) {
  ['notice', 'users', 'logs', 'recycle', 'sys'].forEach(x => {
    const el = document.getElementById('tab-' + x);
    const btn = document.getElementById('tabbtn-' + x);
    if (!el || !btn) return;
    el.classList.toggle('hidden', x !== n);
    btn.classList.toggle('active', x === n);
  });
  if (n === 'notice') loadNotice();
  if (n === 'users') loadUsers();
  if (n === 'logs') loadLogs();
  if (n === 'recycle') loadRecycle();
  if (n === 'sys') loadSite();
}
async function loadUsers() {
  const d = await api('/admin/api/users');
  const tb = document.getElementById('userBody');
  tb.innerHTML = '';
  for (const u of d.users) {
    const roleSel = '<select data-uid="' + u.id + '">' +
      '<option value="admin"' + (u.role === 'admin' ? ' selected' : '') + '>' + t('role_admin') + '</option>' +
      '<option value="user"' + (u.role === 'user' ? ' selected' : '') + '>' + t('role_user') + '</option>' +
      '<option value="readonly"' + (u.role === 'readonly' ? ' selected' : '') + '>' + t('role_readonly') + '</option>' +
      '<option value="pending"' + (u.role === 'pending' ? ' selected' : '') + '>' + t('role_pending') + '</option></select>';
    const locked = u.username.toLowerCase() === 'admin';   // admin 的用户 ID 锁定不可改
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + u.id + '</td>' +
      '<td><span class="u-name">' + esc(u.username) + '</span>' +
      (locked ? '' : '<button class="u-edit" data-uid="' + u.id + '" data-field="username">' + t('edit') + '</button>') + '</td>' +
      '<td><span class="u-name">' + esc(u.display_name || '—') + '</span><button class="u-edit" data-uid="' + u.id + '" data-field="display_name">' + t('edit') + '</button></td>' +
      '<td>' + roleSel + '</td>' +
      '<td class="ops">' +
      '<button class="btn sm" data-uid="' + u.id + '" data-act="reset">' + t('reset_pw') + '</button> ' +
      '<button class="btn sm danger" data-uid="' + u.id + '" data-act="del">' + t('delete') + '</button></td>';
    tb.appendChild(tr);
  }
}
(function () {
  const ub = document.getElementById('userBody');
  if (!ub) return;
  ub.addEventListener('click', function (ev) {
    const b = ev.target.closest('button[data-act]');
    const ue = ev.target.closest('button.u-edit');
    if (ue) {
      const uid = parseInt(ue.dataset.uid, 10);
      if (ue.dataset.field === 'username') userRenameId(uid);
      else userRenameDisplay(uid);
      return;
    }
    if (!b) return;
    const uid = parseInt(b.dataset.uid, 10);
    const act = b.dataset.act;
    if (act === 'reset') userResetPwd(uid);
    else if (act === 'del') userDelete(uid);
  });
  ub.addEventListener('change', function (ev) {
    const s = ev.target.closest('select[data-uid]');
    if (!s) return;
    setRole(parseInt(s.dataset.uid, 10), s.value);
  });
})();

async function addUser() {
  const d = await api('/admin/api/user/add', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: document.getElementById('nuName').value,
      display_name: document.getElementById('nuDisplay').value,
      password: document.getElementById('nuPw').value,
      role: document.getElementById('nuRole').value
    })
  });
  if (d.ok) {
    document.getElementById('nuName').value = '';
    document.getElementById('nuDisplay').value = '';
    document.getElementById('nuPw').value = '';
    loadUsers();
  } else dialogAlert(d.error);
}
async function addBatch() {
  const ids = document.getElementById('batchIds').value;
  const pw = document.getElementById('batchPw').value;
  if (!ids.trim()) { dialogAlert(t('batch_empty')); return; }
  if (!pw) { dialogAlert(t('reset_pw_prompt')); return; }
  const d = await api('/admin/api/user/batch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: ids, password: pw })
  });
  if (!d.ok) { dialogAlert(d.error); return; }
  const msg = t('batch_result')
    .replace('{n}', d.created.length)
    .replace('{m}', d.skipped.length)
    .replace('{list}', d.skipped.join(', ') || '—');
  await dialogAlert(msg);
  document.getElementById('batchIds').value = '';
  document.getElementById('batchPw').value = '';
  loadUsers();
}
async function userRenameId(id) {
  const v = await dialogPrompt(t('rename_id_prompt'), '', false);
  if (v === null) return;
  const d = await api('/admin/api/user/update', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id, username: v })
  });
  if (!d.ok) dialogAlert(d.error);
  loadUsers();
}
async function userRenameDisplay(id) {
  const v = await dialogPrompt(t('rename_display_prompt'), '', false);
  if (v === null) return;
  const d = await api('/admin/api/user/update', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id, display_name: v })
  });
  if (!d.ok) dialogAlert(d.error);
  loadUsers();
}
async function setRole(id, role) {
  const d = await api('/admin/api/user/update', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id, role: role })
  });
  if (!d.ok) dialogAlert(d.error);
}
async function userResetPwd(id) {
  const v = await dialogPrompt2(t('reset_pw_prompt'), t('pw_again'), true);
  if (!v) return;
  const d = await api('/admin/api/user/password', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id, password: v[0], confirm: v[1] })
  });
  if (!d.ok) dialogAlert(d.error);
}
async function userDelete(id) {
  if (!await dialogConfirm(t('del_user_confirm'))) return;
  const d = await api('/admin/api/user/delete', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id })
  });
  if (!d.ok) dialogAlert(d.error);
  loadUsers();
}

/* ---------- 管理后台：公告 / 站点 / 重置 ---------- */
async function loadNotice() {
  const d = await api('/api/notice');
  if (!d.ok) return;
  document.getElementById('noticeTitle').value = d.title;
  document.getElementById('noticeBody').value = d.body.replace(/<br>/g, '\n');
  document.getElementById('noticeEnabled').checked = !!d.enabled;
}
async function saveNotice() {
  const d = await api('/api/notice', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: document.getElementById('noticeTitle').value,
      body: document.getElementById('noticeBody').value,
      enabled: document.getElementById('noticeEnabled').checked
    })
  });
  document.getElementById('noticeMsg').textContent = d.ok ? t('notice_saved') : (d.error || t('hint'));
}
function wrap(tag, label) {
  const ta = document.getElementById('noticeBody');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const selText = ta.value.slice(s, e) || label;
  let open, close;
  if (tag === 'ul') { open = '<ul>\n<li>'; close = '</li>\n</ul>'; }
  else { open = '<' + tag + '>'; close = '</' + tag + '>'; }
  ta.value = ta.value.slice(0, s) + open + selText + close + ta.value.slice(e);
  ta.focus();
}
function insertImg() { document.getElementById('noticeImg').click(); }
async function uploadNoticeImg(list) {
  const f = list[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('file', f);
  const d = await api('/api/notice/upload', { method: 'POST', body: fd });
  if (d.ok) {
    const ta = document.getElementById('noticeBody');
    ta.value += (ta.value ? '\n' : '') + '<img src="' + d.url + '">';
  } else dialogAlert(d.error);
}
async function loadSite() {
  const d = await api('/admin/api/site');
  if (d.ok) document.getElementById('siteTitle').value = d.site_title;
}
async function saveSite() {
  const d = await api('/admin/api/site', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site_title: document.getElementById('siteTitle').value })
  });
  document.getElementById('siteMsg').textContent = d.ok ? t('saved') : (d.error || t('hint'));
}
async function resetSystem() {
  if (!await dialogConfirm(t('reset_confirm_1'))) return;
  if (!await dialogConfirm(t('reset_confirm_2'))) return;
  const d = await api('/admin/api/reset', { method: 'POST' });
  if (d.ok) location.href = '/setup';
  else dialogAlert(d.error || t('reset_fail'));
}

async function loadLogs() {
  const d = await api('/admin/api/logs');
  const tb = document.getElementById('logBody');
  tb.innerHTML = '';
  for (const l of d.logs) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + esc(l.created_at) + '</td><td>' + esc(l.username) + '</td>' +
      '<td>' + esc(l.action) + '</td><td>' + esc((l.path || '') + (l.detail ? ' / ' + l.detail : '')) + '</td>' +
      '<td>' + esc(l.ip) + '</td>';
    tb.appendChild(tr);
  }
}
async function loadRecycle() {
  const d = await api('/admin/api/recycle');
  const tb = document.getElementById('recycleBody');
  tb.innerHTML = '';
  for (const it of d.items) {
    const tr = document.createElement('tr');
    const nm = (it.is_dir ? '📁️ ' : '') + esc(it.name);
    tr.innerHTML = '<td>' + nm + '</td><td class="num">' + fmtSize(it.size) + '</td><td class="num">' + fmtTime(it.mtime) + '</td>';
    tb.appendChild(tr);
  }
}
