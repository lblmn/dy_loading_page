/* LinkLab 前端：原生 JS，无框架。重点看这几件事：
 *  - fetch 统一封装：写操作自动带 X-CSRF-Token；管理员跨账号视图在前端改写 fetch
 *  - 用 textContent / dataset 而不是拼接 innerHTML 渲染用户输入（防 XSS）
 *  - 批量任务的异步循环与逐条错误处理；服务端搜索 / 排序 / 分页
 *  - 编辑时复用同一个 code，保证「原链接不变」
 *  - 深链类型（video / live）与协议前缀（douyin / lite）由服务端配置开关控制
 */
const $ = s => document.querySelector(s);
let csrf = '', me = null, editingCode = '', liveEditingCode = '', editingItem = null;
// 主面板 / 房间面板的目标类型：新建固定为视频深链 / 直播深链；
// 编辑旧入口（id/url/app/room）时保住原类型，不被静默改写
let editingKind = '', liveEditingKind = '';
let modalUrl = '', liveItem = null, scopeAll = false, lastUrl = '';
let page = 1, pageSize = 10, total = 0, deepLinks = false, searchTimer = null;

function deviceCode() {
  let id = localStorage.getItem('linklab.device');
  if (!id) {
    id = crypto.randomUUID().replaceAll('-', '');
    localStorage.setItem('linklab.device', id);
  }
  return id;
}

async function api(path, { method = 'GET', body, skipCsrf = false } = {}) {
  let target = path;
  // 原站语义：管理员勾选「显示所有人的作品」后由前端改写 fetch；
  // 服务端仍按 role 复核 ?all=1，前端改写只是交互方式，不是权限边界。
  if (scopeAll && (target === '/api/links' || target.startsWith('/api/links?'))) {
    target += (target.includes('?') ? '&' : '?') + 'all=1';
  }
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && !skipCsrf) headers['X-CSRF-Token'] = csrf;
  const res = await fetch(target, {
    method, headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data;
  try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const old = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(() => { btn.textContent = old; }, 1200);
  } catch { /* 非 HTTPS / 非 localhost 时剪贴板可能不可用 */ }
}

/* ---------------- 登录 / 启动 ---------------- */
$('#loginBtn').onclick = async () => {
  const btn = $('#loginBtn'), err = $('#loginError');
  btn.disabled = true; err.textContent = '';
  try {
    await api('/api/login', {
      method: 'POST', skipCsrf: true,
      body: {
        username: $('#username').value,
        password: $('#password').value,
        deviceCode: deviceCode(),
      },
    });
    await boot();
  } catch (e) {
    err.textContent = e.message;
  } finally { btn.disabled = false; }
};
$('#password').onkeydown = e => { if (e.key === 'Enter') $('#loginBtn').click(); };

$('#logoutBtn').onclick = async () => {
  await api('/api/logout', { method: 'POST' });
  location.reload();
};

async function boot() {
  try {
    me = await api('/api/me');
  } catch {
    $('#loginView').hidden = false;
    $('#appView').hidden = true;
    return;
  }
  csrf = me.csrf;
  $('#loginView').hidden = true;
  $('#appView').hidden = false;
  $('#who').textContent = `${me.username} · ${me.role === 'admin' ? '管理员' : '普通用户'}`;
  $('#expiry').textContent = me.expiresAt
    ? `到期：${new Date(me.expiresAt).toLocaleDateString('zh-CN')}`
    : '有效期：永久';
  const isAdmin = me.role === 'admin';
  $('#adminLink').hidden = !isAdmin;
  $('#scopeBtn').hidden = !isAdmin;
  syncKindFields('video');  // 新建默认视频深链：显示 ID 队列输入与深链提示
  await loadEntries();
}

/* ---------------- 单条创建 / 编辑 ---------------- */
function payload() {
  const kind = editingCode ? (editingKind || 'video') : 'video';
  const base = {
    name: $('#name').value, platform: $('#platform').value,
    kind, randomOrder: false, followers: [],
  };
  if (!editingCode) {
    const alias = $('#alias').value.trim();
    if (alias) base.alias = alias;
    const days = parseInt($('#expiresDays').value, 10);
    if (days > 0) base.expiresDays = days;
  } else if (editingItem) {
    base.enabled = editingItem.enabled;
  }
  if (kind === 'url') {
    base.target = '';
    base.targetUrl = $('#targetUrl').value;
  } else if (kind === 'app') {
    base.target = '';
    base.appLink = $('#appLink').value;
  } else if (kind === 'live') {
    base.target = '';
    base.live = $('#liveRoom').value.trim();
  } else {
    base.target = $('#target').value;
    base.randomOrder = $('#randomOrder').checked;
    base.followers = [...document.querySelectorAll('.follower')].map(x => x.value)
      .concat($('#bulkFollowers').value.split(/\r?\n/).map(x => x.trim()).filter(Boolean));
  }
  return base;
}

/* 不同目标类型只显示对应的输入项（类型不再由下拉选择，见 editingKind） */
function syncKindFields(kind) {
  kind = kind || editingKind || 'video';
  $('#idOnlyBox').hidden = !(kind === 'id' || kind === 'video');
  $('#targetUrlField').hidden = kind !== 'url';
  $('#appLinkField').hidden = kind !== 'app';
  $('#liveField').hidden = kind !== 'live';
  $('#deepHint').hidden = !(kind === 'video' || kind === 'live');
  $('#alias').disabled = !!editingCode;  // 短码生成后不可改，保证已分发的链接不失效
}
$('#batchKind').onchange = () => {
  const k = $('#batchKind').value;
  $('#batchTargets').placeholder = {
    id: '每行粘贴一个链接、分享文案或数字 ID',
    video: '每行一个视频 ID 或整段分享文案',
    live: '每行一个房间号或房间链接',
    url: '每行一个 https:// 地址',
    app: '每行一个应用链接（须在白名单内）',
  }[k] || '';
};

function resetForm() {
  editingCode = ''; editingItem = null;
  $('#editBanner').classList.remove('show');
  $('#createBtn').textContent = '生成链接和二维码';
  $('#name').value = ''; $('#target').value = '';
  $('#targetUrl').value = ''; $('#appLink').value = ''; $('#liveRoom').value = '';
  $('#alias').value = ''; $('#alias').disabled = false; $('#expiresDays').value = '';
  editingKind = ''; syncKindFields('video');
  $('#randomOrder').checked = false;
  $('#bulkFollowers').value = '';
  document.querySelectorAll('.follower').forEach(x => { x.value = ''; });
}

$('#createBtn').onclick = async () => {
  const btn = $('#createBtn'), msg = $('#message');
  btn.disabled = true; msg.textContent = ''; msg.classList.remove('ok');
  try {
    const d = await api(editingCode ? `/api/links/${editingCode}` : '/api/links',
      { method: editingCode ? 'PUT' : 'POST', body: payload() });
    $('#resultUrl').value = d.url;
    lastUrl = d.url;
    $('#result').hidden = false;
    $('#qrcode').innerHTML = '';
    new QRCode($('#qrcode'), { text: d.url, width: 148, height: 148 });
    msg.textContent = editingCode ? '入口已更新（短链不变）' : '链接已生成';
    msg.classList.add('ok');
    resetForm();
    page = 1;
    await loadEntries();
  } catch (e) {
    msg.textContent = e.message;
  } finally { btn.disabled = false; }
};
$('#copyBtn').onclick = () => copyText($('#resultUrl').value, $('#copyBtn'));
$('#previewLink').onclick = () => {
  if (!lastUrl) { alert('先在左侧或中间生成一个链接，再来预览落地页。'); return; }
  window.open(lastUrl, '_blank', 'noopener');
};

/* ---------------- 二维码弹窗 / 批量 ZIP ---------------- */
function qrDataUrl(text) {
  const holder = document.createElement('div');
  holder.style.cssText = 'position:fixed;left:-9999px;top:0';
  document.body.append(holder);
  try {
    new QRCode(holder, { text, width: 220, height: 220 });
    const canvas = holder.querySelector('canvas');
    const img = holder.querySelector('img');
    if (canvas) return canvas.toDataURL('image/png');
    return img && img.src.startsWith('data:') ? img.src : '';
  } finally { holder.remove(); }
}

function showQr(item) {
  modalUrl = item.url;
  $('#modalTitle').textContent = item.name;
  $('#modalQr').innerHTML = '';
  new QRCode($('#modalQr'), { text: item.url, width: 200, height: 200 });
  $('#qrModal').showModal();
}
$('#modalClose').onclick = () => $('#qrModal').close();
$('#modalCopyBtn').onclick = () => copyText(modalUrl, $('#modalCopyBtn'));
$('#modalSaveBtn').onclick = () => {
  const src = $('#modalQr canvas')?.toDataURL('image/png') || $('#modalQr img')?.src;
  if (!src) return;
  const a = document.createElement('a');
  a.href = src; a.download = 'LinkLab-二维码.png'; a.click();
};
$('#bulkZipBtn').onclick = () => {
  const boxes = [...document.querySelectorAll('.entry-select:checked')];
  const files = boxes.map(b => ({
    name: `${b.dataset.name || '入口'}-${b.dataset.code}`,
    dataUrl: qrDataUrl(b.dataset.url),
  })).filter(f => f.dataUrl);
  if (!files.length) { $('#bulkStatus').textContent = '二维码生成失败'; return; }
  LinkLabZip.download(LinkLabZip.fromDataUrls(files), 'LinkLab-二维码.zip');
  $('#bulkStatus').textContent = `已导出 ${files.length} 张二维码`;
};

/* ---------------- 房间 / 直播入口 ---------------- */
function resetLiveEdit() {
  liveEditingCode = '';
  liveEditingKind = '';
  $('#liveBtn').textContent = '生成房间链接';
  $('#cancelLiveBtn').hidden = true;
}
$('#cancelLiveBtn').onclick = resetLiveEdit;
$('#copyLiveBtn').onclick = () => copyText($('#liveUrl').value, $('#copyLiveBtn'));
$('#qrLiveBtn').onclick = () => { if (liveItem) showQr(liveItem); };
$('#liveBtn').onclick = async () => {
  const btn = $('#liveBtn'), msg = $('#liveMessage');
  const live = $('#liveInput').value.trim();
  if (!live) { msg.textContent = '请填写房间 ID'; return; }
  btn.disabled = true; msg.textContent = ''; msg.classList.remove('ok');
  try {
    const body = {
      name: $('#liveName').value.trim() || '房间入口',
      platform: $('#livePlatform').value,
      kind: liveEditingCode ? (liveEditingKind || 'live') : 'live',
      live, target: '', followers: [], randomOrder: false,
    };
    const d = await api(liveEditingCode ? `/api/links/${liveEditingCode}` : '/api/links',
      { method: liveEditingCode ? 'PUT' : 'POST', body });
    $('#liveUrl').value = d.url;
    lastUrl = d.url;
    liveItem = { name: body.name, url: d.url };
    $('#liveResult').hidden = false;
    msg.textContent = '房间入口已保存'; msg.classList.add('ok');
    resetLiveEdit();
    page = 1;
    await loadEntries();
  } catch (e) {
    msg.textContent = e.message;
  } finally { btn.disabled = false; }
};

/* ---------------- 批量创建 ---------------- */
$('#batchCopyBtn').onclick = () => copyText($('#batchResults').value, $('#batchCopyBtn'));
$('#batchBtn').onclick = async () => {
  const prefix = $('#batchPrefix').value.trim();
  const lines = $('#batchTargets').value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  const kind = $('#batchKind').value;
  const msg = $('#batchMessage'), btn = $('#batchBtn');
  if (!prefix || !lines.length) { msg.textContent = '请填写名称前缀和目标列表'; return; }
  btn.disabled = true;
  const urls = [], failed = [];
  $('#batchResults').value = ''; $('#batchResults').hidden = true; $('#batchCopyBtn').hidden = true;
  try {
    for (let i = 0; i < lines.length; i++) {
      msg.textContent = `正在生成 ${i + 1}/${lines.length}`;
      const job = {
        name: `${prefix}-${i + 1}`, platform: $('#batchPlatform').value,
        kind, followers: [], randomOrder: false, target: '',
      };
      if (kind === 'url') job.targetUrl = lines[i];
      else if (kind === 'app') job.appLink = lines[i];
      else if (kind === 'live') job.live = lines[i];
      else job.target = lines[i];
      try {
        const d = await api('/api/links', { method: 'POST', body: job });
        urls.push(d.url);
        lastUrl = d.url;
        $('#batchResults').value = urls.join('\n');
        $('#batchResults').hidden = false;
        $('#batchCopyBtn').hidden = false;
      } catch (e) { failed.push(`${job.name}：${e.message}`); }
    }
    msg.textContent = `完成：成功 ${urls.length}，失败 ${failed.length}`
      + (failed.length ? `；${failed.join('；')}` : '');
    if (!failed.length) $('#batchTargets').value = '';
    page = 1;
    await loadEntries();
  } finally { btn.disabled = false; }
};

/* ---------------- 入口列表 / 批量操作 ---------------- */
function editEntry(item) {
  const kind = item.kind || 'id';
  if (kind === 'room' || kind === 'live') {
    liveEditingCode = item.code;
    liveEditingKind = kind;  // 旧「仅展示房间配置」编辑时保持原类型
    $('#liveName').value = item.name;
    $('#liveInput').value = item.roomId;
    // 旧入口的 web/h5/mini 已下线，编辑时归一化为抖音
    $('#livePlatform').value = ['douyin', 'lite'].includes(item.platform) ? item.platform : 'douyin';
    $('#liveBtn').textContent = '保存房间修改';
    $('#cancelLiveBtn').hidden = false;
    $('#livePanel').scrollIntoView({ behavior: 'smooth' });
    return;
  }
  editingCode = item.code; editingItem = item;
  const normalized = ['id', 'url', 'app', 'video'].includes(kind) ? kind : 'id';
  editingKind = normalized;
  syncKindFields(normalized);
  $('#name').value = item.name;
  // 旧入口的 web/h5/mini 已下线，编辑时归一化为抖音
  $('#platform').value = ['douyin', 'lite'].includes(item.platform) ? item.platform : 'douyin';
  $('#alias').value = item.code;
  $('#expiresDays').value = '';  // 编辑不改有效期，需要改请在列表里停用/启用
  if (normalized === 'url') {
    $('#targetUrl').value = item.targetUrl || '';
  } else if (normalized === 'app') {
    $('#appLink').value = item.targetUrl || '';
  } else {
    $('#target').value = item.targetId;
    $('#randomOrder').checked = !!item.randomOrder;
    const inputs = [...document.querySelectorAll('.follower')];
    inputs.forEach((x, i) => { x.value = item.gids?.[i] || ''; });
    $('#bulkFollowers').value = (item.gids || []).slice(inputs.length).join('\n');
  }
  $('#editBanner').classList.add('show');
  $('#createBtn').textContent = '保存修改';
  scrollTo({ top: 0, behavior: 'smooth' });
}

async function toggleEntry(item, button) {
  button.disabled = true;
  try {
    await api(`/api/links/${item.code}`, { method: 'PATCH', body: { enabled: !item.enabled } });
    await loadEntries();
  } catch (e) {
    $('#bulkStatus').textContent = e.message;
  } finally { button.disabled = false; }
}

async function deleteEntry(item) {
  if (!confirm(`确定删除「${item.name}」吗？删除后原链接立即失效。`)) return;
  await api(`/api/links/${item.code}`, { method: 'DELETE' });
  await loadEntries();
}

function updateSelection() {
  const boxes = [...document.querySelectorAll('.entry-select')];
  const n = boxes.filter(b => b.checked).length;
  $('#bulkCopyBtn').hidden = n === 0;
  $('#bulkZipBtn').hidden = n === 0;
  $('#bulkDeleteBtn').hidden = n === 0;
  $('#bulkCopyBtn').textContent = `批量复制（${n}）`;
  $('#bulkZipBtn').textContent = `导出二维码 ZIP（${n}）`;
  $('#bulkDeleteBtn').textContent = `批量删除（${n}）`;
  $('#selectAll').checked = boxes.length > 0 && n === boxes.length;
  $('#selectAll').indeterminate = n > 0 && n < boxes.length;
  $('#selectAll').disabled = boxes.length === 0;
  $('#bulkStatus').textContent = '';
}
$('#selectAll').onchange = e => {
  document.querySelectorAll('.entry-select').forEach(b => { b.checked = e.target.checked; });
  updateSelection();
};
$('#bulkCopyBtn').onclick = () => {
  const text = [...document.querySelectorAll('.entry-select:checked')]
    .map(b => b.dataset.url).join('\n');
  if (text) { copyText(text, $('#bulkCopyBtn')); $('#bulkStatus').textContent = `已复制 ${text.split('\n').length} 个链接`; }
};
$('#bulkDeleteBtn').onclick = async () => {
  const selected = [...document.querySelectorAll('.entry-select:checked')];
  if (!selected.length) return;
  if (!confirm(`确定删除选中的 ${selected.length} 个入口吗？此操作不可撤销。`)) return;
  const btn = $('#bulkDeleteBtn'); btn.disabled = true;
  let ok = 0; const failed = [];
  try {
    for (const b of selected) {
      try { await api(`/api/links/${b.dataset.code}`, { method: 'DELETE' }); ok++; }
      catch { failed.push(b.dataset.code); }
    }
    await loadEntries();
    document.querySelectorAll('.entry-select').forEach(b => { b.checked = failed.includes(b.dataset.code); });
    updateSelection();
    $('#bulkStatus').textContent = `删除完成：成功 ${ok}，失败 ${failed.length}`;
  } finally { btn.disabled = false; }
};
$('#scopeBtn').onclick = () => {
  scopeAll = !scopeAll;
  $('#scopeBtn').textContent = scopeAll ? '仅显示我的作品' : '显示所有人的作品';
  page = 1;
  loadEntries();
};
$('#entrySearch').oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { page = 1; loadEntries(); }, 250);
};
$('#entrySort').onchange = () => { page = 1; loadEntries(); };
$('#prevPage').onclick = () => { if (page > 1) { page -= 1; loadEntries(); } };
$('#nextPage').onclick = () => { if (page * pageSize < total) { page += 1; loadEntries(); } };

/* 注意：index.html 会同时加载 landing.js，两个经典脚本共享全局词法作用域，
 * 常量名必须错开（landing.js 已有 KIND_TEXT），否则整个 app.js 解析失败。 */
const ENTRY_KIND_TEXT = { id: 'ID 队列', url: '网页', app: '应用', room: '房间',
                          video: '视频深链', live: '直播深链' };

async function loadEntries() {
  const params = new URLSearchParams({
    q: $('#entrySearch').value.trim(), sort: $('#entrySort').value,
    page: String(page), size: String(pageSize),
  });
  const data = await api('/api/links?' + params);
  const items = Array.isArray(data) ? data : (data.items || []);
  total = Array.isArray(data) ? items.length : (data.total || 0);
  $('#count').textContent = `共 ${total} 个入口`;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (page > pages) { page = pages; return loadEntries(); }
  $('#pager').hidden = total <= pageSize;
  $('#pageInfo').textContent = `第 ${page} / ${pages} 页`;
  $('#prevPage').disabled = page <= 1;
  $('#nextPage').disabled = page >= pages;

  const box = $('#entries');
  box.innerHTML = items.length ? '' : '<div class="empty">没有匹配的入口，换个关键词或在上方生成一个吧</div>';
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'entry';
    // 骨架是静态 HTML，所有用户可控内容都用 textContent 填入 —— 防 XSS
    row.innerHTML = '<input type="checkbox" class="entry-select"><div><div class="entry-name"></div>'
      + '<div class="entry-meta"></div></div><div class="entry-url"></div>'
      + '<div class="tools"><button class="tool qr-btn">二维码</button><button class="tool copy-btn">复制</button>'
      + '<button class="tool edit-btn">编辑</button><button class="tool toggle-btn"></button>'
      + '<button class="tool danger delete-btn">删除</button></div>';
    const cb = row.querySelector('.entry-select');
    cb.dataset.url = item.url; cb.dataset.code = item.code; cb.dataset.name = item.name;
    cb.setAttribute('aria-label', `选择 ${item.name}`);
    cb.onchange = updateSelection;
    row.querySelector('.entry-name').textContent = item.name;
    const kindText = ENTRY_KIND_TEXT[item.kind] || 'ID 队列';
    const targetText = item.roomId ? `房间 ${item.roomId}`
      : (item.kind === 'id' || item.kind === 'video')
        ? `目标 ${item.targetId} · 后续 ${item.gids?.length || 0} 个`
        : (item.targetUrl || '');
    const stateText = { active: '启用', disabled: '已停用', expired: '已过期' }[item.status] || '启用';
    row.querySelector('.entry-meta').textContent =
      `${kindText} · ${targetText} · ${item.clicks || 0} 次访问 · ${stateText} · ${item.ownerName || ''}`;
    row.querySelector('.entry-url').textContent = item.url;
    row.querySelector('.qr-btn').onclick = () => showQr(item);
    row.querySelector('.copy-btn').onclick = e => copyText(item.url, e.currentTarget);
    row.querySelector('.edit-btn').onclick = () => editEntry(item);
    const toggle = row.querySelector('.toggle-btn');
    toggle.textContent = item.enabled ? '停用' : '启用';
    toggle.onclick = () => toggleEntry(item, toggle);
    row.querySelector('.delete-btn').onclick = () => deleteEntry(item);
    box.append(row);
  });
  updateSelection();
}

/* 账号管理已迁到独立后台 /admin（admin.html + admin.js），
 * 工作台只保留「显示所有人的作品」这个跨账号视图开关。
 */

/* 登录页提示 / 品牌 / 深链开关均由服务端下发：
 * 生产部署的页面里不会出现任何凭据。 */
async function loadLoginConfig() {
  try {
    const c = await (await fetch('/api/config')).json();
    const brand = c.brand || {};
    document.querySelectorAll('.js-brand-name').forEach(el => {
      el.textContent = brand.name || 'LinkLab';
    });
    document.querySelectorAll('.js-brand-tag').forEach(el => {
      el.textContent = c.brandTag || '工作台';
    });
    if (brand.color) document.documentElement.style.setProperty('--brand-accent', brand.color);
    deepLinks = !!c.deepLinks;
    if (!deepLinks) {
      document.querySelectorAll('.deep-kind').forEach(o => {
        o.disabled = true;
        o.textContent += '（服务端已关闭）';
      });
    }
    if (!c.devMode || !c.demoAccounts?.length) return;
    const hint = $('#loginHint');
    hint.textContent = '';
    c.demoAccounts.forEach(a => {
      const d = document.createElement('div');
      d.textContent = `演示账号：${a.username} / ${a.password}`;
      hint.append(d);
    });
    const note = document.createElement('div');
    note.textContent = '开发模式仅在本地使用，部署前请关闭 LINKLAB_DEV_MODE。';
    hint.append(note);
    $('#username').value = c.demoAccounts[1]?.username || c.demoAccounts[0].username;
    $('#password').value = c.demoAccounts[1]?.password || c.demoAccounts[0].password;
  } catch { /* 保持中性提示即可 */ }
}

(async () => {
  // /?r=<code> 时与落地页共用同一份 HTML，只切换隐藏，不加载工作台
  if (window.LINKLAB_LANDING_MODE) return;
  await loadLoginConfig();
  await boot();
})();
