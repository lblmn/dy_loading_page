/* LinkLab 独立管理后台（仅 admin 可访问）
 * 与工作台分开：服务端在 /admin 做页面级鉴权，前端只负责体验。
 * 重点：所有写请求带 CSRF；表格内容一律用 textContent 渲染，避免 XSS。
 */
const $ = s => document.querySelector(s);
let csrf = '', me = null;
let users = [], links = [], editingUser = null, pwdUser = null;

const KIND_TEXT = { id: 'ID 队列', url: '网页地址', app: '应用链接', room: '房间',
                    video: '视频深链', live: '直播深链' };

async function api(path, { method = 'GET', body } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  const res = await fetch(path, {
    method, headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data;
  try { data = await res.json(); } catch { data = {}; }
  if (res.status === 401) { location.href = '/login'; throw new Error('请先登录'); }
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

function notify(text, ok = true) {
  const el = $('#globalMessage');
  el.textContent = text;
  el.classList.toggle('ok', ok);
  setTimeout(() => { el.textContent = ''; }, 3500);
}

function btn(label, cls, onclick) {
  const b = document.createElement('button');
  b.className = cls; b.textContent = label; b.onclick = onclick;
  return b;
}

function td(row, text, cls) {
  const cell = document.createElement('td');
  if (cls) cell.className = cls;
  cell.textContent = text ?? '—';
  row.append(cell);
  return cell;
}

/* ---------------- 概览卡片 ---------------- */
function renderStats(s) {
  const cards = [
    ['账号总数', s.users], ['管理员', s.admins], ['短链入口', s.links],
    ['今日新增', s.todayLinks], ['总访问', s.totalClicks], ['今日访问', s.todayClicks],
    ['已禁用', s.disabled], ['已过期', s.expired],
  ];
  const box = $('#stats'); box.innerHTML = '';
  cards.forEach(([label, value]) => {
    const d = document.createElement('div');
    d.className = 'stat-card';
    const v = document.createElement('div'); v.className = 'stat-value'; v.textContent = value;
    const l = document.createElement('div'); l.className = 'stat-label'; l.textContent = label;
    d.append(v, l); box.append(d);
  });

  const owners = $('#ownerStats'); owners.innerHTML = '';
  const max = Math.max(1, ...s.byOwner.map(x => x.n));
  if (!s.byOwner.length) owners.textContent = '暂无账号';
  s.byOwner.forEach(x => {
    const line = document.createElement('div'); line.className = 'owner-line';
    const name = document.createElement('span'); name.textContent = x.name;
    const bar = document.createElement('span'); bar.className = 'owner-bar';
    const fill = document.createElement('i'); fill.style.width = `${Math.round(x.n / max * 100)}%`;
    bar.append(fill);
    const num = document.createElement('span'); num.className = 'owner-num'; num.textContent = x.n;
    line.append(name, bar, num); owners.append(line);
  });

  // 访问量 Top
  const tops = $('#topLinks'); tops.innerHTML = '';
  if (!s.topLinks?.length) tops.textContent = '暂无访问数据';
  (s.topLinks || []).forEach(x => {
    const line = document.createElement('div'); line.className = 'owner-line';
    const name = document.createElement('span'); name.textContent = x.name;
    const bar = document.createElement('span'); bar.className = 'owner-bar';
    const maxC = Math.max(1, ...s.topLinks.map(t => t.clicks));
    const fill = document.createElement('i'); fill.style.width = `${Math.round(x.clicks / maxC * 100)}%`;
    bar.append(fill);
    const num = document.createElement('span'); num.className = 'owner-num'; num.textContent = x.clicks;
    line.append(name, bar, num); tops.append(line);
  });

  const recent = $('#recentList'); recent.innerHTML = '';
  if (!s.recent.length) recent.textContent = '暂无入口';
  s.recent.forEach(r => {
    const d = document.createElement('div'); d.className = 'recent-item';
    const n = document.createElement('span'); n.textContent = r.name;
    const o = document.createElement('span'); o.className = 'm'; o.textContent = `${r.owner} · ${r.created_at.slice(0, 16).replace('T', ' ')}`;
    d.append(n, o); recent.append(d);
  });
}

/* ---------------- 审计日志 ---------------- */
const ACTION_TEXT = {
  login: '登录',   'login.fail': '登录失败', 'link.create': '创建入口',
  'link.update': '修改入口', 'link.patch': '停用/启用入口',
  'link.delete': '删除入口', 'user.create': '创建账号',
  'user.update': '修改账号', 'user.delete': '删除账号',
  'user.reset_password': '重置密码', 'user.reset_device': '解除设备绑定',
};

async function loadAudit() {
  const rows = await api('/api/admin/audit');
  const box = $('#auditRows'); box.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    td(tr, '暂无记录', 'empty-cell').colSpan = 6;
    box.append(tr); return;
  }
  rows.forEach(a => {
    const tr = document.createElement('tr');
    td(tr, a.createdAt.slice(0, 19).replace('T', ' '));
    td(tr, a.username || '—');
    td(tr, ACTION_TEXT[a.action] || a.action);
    td(tr, a.target || '—');
    td(tr, a.ok ? '成功' : '失败', a.ok ? 'state-ok' : 'state-off');
    td(tr, a.ip || '—');
    box.append(tr);
  });
}
$('#refreshAuditBtn').onclick = () => loadAudit().catch(e => notify(e.message, false));

/* ---------------- 账号表 ---------------- */
function renderUsers() {
  const kw = $('#userSearch').value.trim().toLowerCase();
  const rows = users.filter(u =>
    u.username.toLowerCase().includes(kw) || u.role.toLowerCase().includes(kw));
  const box = $('#userRows'); box.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    td(tr, '没有匹配的账号', 'empty-cell').colSpan = 7;
    box.append(tr); return;
  }
  rows.forEach(u => {
    const tr = document.createElement('tr');
    td(tr, u.id);
    td(tr, u.username, 'strong-cell');
    td(tr, u.role === 'admin' ? '管理员' : '普通用户');
    td(tr, u.expiresAt ? u.expiresAt.slice(0, 10) : '永久');
    td(tr, u.linkCount);
    td(tr, u.enabled ? (u.deviceBound ? '正常 · 已绑设备' : '正常') : '已禁用',
      u.enabled ? 'state-ok' : 'state-off');

    const ops = document.createElement('td'); ops.className = 'ops';
    const isSelf = u.id === me.id;
    if (isSelf) {
      const tag = document.createElement('span'); tag.className = 'pill'; tag.textContent = '当前账号';
      ops.append(tag);
    } else {
      ops.append(btn('编辑', 'tool', () => openEdit(u)));
      ops.append(btn('密码', 'tool', () => openPwd(u)));
      ops.append(btn('解绑', 'tool', async () => {
        try { await api(`/api/users/${u.id}/reset-device`, { method: 'POST' }); notify('设备绑定已解除'); await refresh(); }
        catch (e) { notify(e.message, false); }
      }));
      ops.append(btn(u.enabled ? '禁用' : '启用', 'tool', async () => {
        try {
          await api(`/api/users/${u.id}`, { method: 'PUT', body: { enabled: !u.enabled } });
          notify(u.enabled ? '账号已禁用' : '账号已启用'); await refresh();
        } catch (e) { notify(e.message, false); }
      }));
      ops.append(btn('删除', 'tool danger', async () => {
        if (!confirm(`确定删除账号「${u.username}」吗？该账号的全部入口会被一并删除，不可撤销。`)) return;
        try { await api(`/api/users/${u.id}`, { method: 'DELETE' }); notify('账号已删除'); await refresh(); }
        catch (e) { notify(e.message, false); }
      }));
    }
    tr.append(ops); box.append(tr);
  });
}

/* ---------------- 全局入口表 ---------------- */
function renderLinks() {
  const kw = $('#linkSearch').value.trim().toLowerCase();
  const rows = links.filter(l =>
    l.name.toLowerCase().includes(kw) || (l.ownerName || '').toLowerCase().includes(kw)
    || l.code.toLowerCase().includes(kw));
  const box = $('#linkRows'); box.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    td(tr, '没有匹配的入口', 'empty-cell').colSpan = 8;
    box.append(tr); return;
  }
  rows.forEach(l => {
    const tr = document.createElement('tr');
    td(tr, l.name, 'strong-cell');
    td(tr, l.ownerName || `uid:${l.ownerId}`);
    td(tr, KIND_TEXT[l.kind] || 'ID 队列');
    td(tr, l.roomId ? `房间 ${l.roomId}`
      : (l.kind === 'id' || l.kind === 'video') ? l.targetId : (l.targetUrl || ''));
    td(tr, l.clicks || 0);
    const stateMap = { active: '启用', disabled: '已停用', expired: '已过期' };
    td(tr, stateMap[l.status] || '启用', l.status === 'active' ? 'state-ok' : 'state-off');
    td(tr, l.createdAt.slice(0, 16).replace('T', ' '));
    const ops = document.createElement('td'); ops.className = 'ops';
    ops.append(btn('查看', 'tool', () => window.open(l.url, '_blank', 'noopener')));
    ops.append(btn(l.enabled ? '停用' : '启用', 'tool', async () => {
      try {
        await api(`/api/links/${l.code}`, { method: 'PATCH', body: { enabled: !l.enabled } });
        notify(l.enabled ? '入口已停用（短码保留）' : '入口已启用');
        await refresh();
      } catch (e) { notify(e.message, false); }
    }));
    ops.append(btn('删除', 'tool danger', async () => {
      if (!confirm(`确定删除入口「${l.name}」吗？删除后短链立即失效。`)) return;
      try { await api(`/api/links/${l.code}`, { method: 'DELETE' }); notify('入口已删除'); await refresh(); }
      catch (e) { notify(e.message, false); }
    }));
    tr.append(ops); box.append(tr);
  });
}

/* ---------------- 弹窗 ---------------- */
function openEdit(u) {
  editingUser = u;
  $('#editTitle').textContent = `编辑账号 · ${u.username}`;
  $('#editRole').value = u.role;
  $('#editDays').value = '';
  $('#editEnabled').checked = !!u.enabled;
  $('#editMessage').textContent = '';
  $('#editModal').showModal();
}
$('#editCancel').onclick = $('#editCancel2').onclick = () => $('#editModal').close();
$('#editSave').onclick = async () => {
  const body = { role: $('#editRole').value, enabled: $('#editEnabled').checked };
  const raw = $('#editDays').value.trim();
  if (raw !== '') body.days = parseInt(raw, 10) || 0;  // 0 = 永久
  try {
    await api(`/api/users/${editingUser.id}`, { method: 'PUT', body });
    $('#editModal').close(); notify('账号已更新'); await refresh();
  } catch (e) { $('#editMessage').textContent = e.message; }
};

function openPwd(u) {
  pwdUser = u;
  $('#pwdTitle').textContent = `重置密码 · ${u.username}`;
  $('#pwdInput').value = '';
  $('#pwdMessage').textContent = '';
  $('#pwdModal').showModal();
}
$('#pwdCancel').onclick = $('#pwdCancel2').onclick = () => $('#pwdModal').close();
$('#pwdSave').onclick = async () => {
  try {
    await api(`/api/users/${pwdUser.id}/reset-password`,
      { method: 'POST', body: { password: $('#pwdInput').value } });
    $('#pwdModal').close(); notify('密码已重置，该账号需重新登录'); await refresh();
  } catch (e) { $('#pwdMessage').textContent = e.message; }
};

/* ---------------- 新建账号 ---------------- */
$('#createUserBtn').onclick = async () => {
  const msg = $('#userMessage'); msg.textContent = ''; msg.classList.remove('ok');
  const days = parseInt($('#newDays').value, 10);
  try {
    await api('/api/users', {
      method: 'POST',
      body: {
        username: $('#newUser').value, password: $('#newPwd').value,
        role: $('#newRole').value, ...(days > 0 ? { days } : {}),
      },
    });
    $('#newUser').value = ''; $('#newPwd').value = '';
    msg.textContent = '账号已创建'; msg.classList.add('ok');
    await refresh();
  } catch (e) { msg.textContent = e.message; }
};

/* ---------------- 点击明细报表 ---------------- */
function clickQuery() {
  const p = new URLSearchParams();
  const code = $('#clickCode').value, from = $('#clickFrom').value, to = $('#clickTo').value;
  if (code) p.set('code', code);
  if (from) p.set('from', from);
  if (to) p.set('to', to);
  return p.toString();
}

function renderBarList(el, rows) {
  el.innerHTML = '';
  if (!rows.length) { el.textContent = '暂无数据'; return; }
  const max = Math.max(1, ...rows.map(r => r.n));
  rows.forEach(r => {
    const line = document.createElement('div'); line.className = 'owner-line';
    const name = document.createElement('span'); name.textContent = r.label;
    const bar = document.createElement('span'); bar.className = 'owner-bar';
    const fill = document.createElement('i'); fill.style.width = `${Math.round(r.n / max * 100)}%`;
    bar.append(fill);
    const num = document.createElement('span'); num.className = 'owner-num'; num.textContent = r.n;
    line.append(name, bar, num); el.append(line);
  });
}

async function loadClicks() {
  const r = await api('/api/admin/clicks?' + clickQuery());
  $('#clickMessage').textContent = `共 ${r.total} 次访问，明细显示最近 ${r.items.length} 条`;
  renderBarList($('#clickByDay'), (r.byDay || []).map(x => ({ label: x.day, n: x.n })));
  const sources = [
    ...(r.byReferer || []).map(x => ({ label: x.referer, n: x.n })),
    ...(r.byUtm || []).map(x => ({ label: '渠道 ' + x.utm, n: x.n })),
  ];
  renderBarList($('#clickBySource'), sources);
  const box = $('#clickRows'); box.innerHTML = '';
  if (!r.items.length) {
    const tr = document.createElement('tr');
    td(tr, '暂无访问明细', 'empty-cell').colSpan = 6;
    box.append(tr); return;
  }
  r.items.forEach(it => {
    const tr = document.createElement('tr');
    td(tr, it.createdAt.slice(0, 19).replace('T', ' '));
    td(tr, it.code);
    td(tr, it.referer || '(直接访问)');
    td(tr, it.utm || '—');
    td(tr, it.ip || '—');
    td(tr, (it.ua || '—').slice(0, 48));
    box.append(tr);
  });
}
$('#queryClicksBtn').onclick = () => loadClicks().catch(e => notify(e.message, false));
$('#exportClicksBtn').onclick = () => {
  // 走浏览器导航下载，服务端返回 Content-Disposition: attachment
  location.href = '/api/admin/clicks.csv?' + clickQuery();
};

/* ---------------- 启动 ---------------- */
$('#userSearch').oninput = renderUsers;
$('#linkSearch').oninput = renderLinks;
$('#logoutBtn').onclick = async () => {
  await api('/api/logout', { method: 'POST' });
  location.href = '/login';
};

async function refresh() {
  const [stats, u, l] = await Promise.all([
    api('/api/admin/stats'), api('/api/users'), api('/api/links?all=1'),
  ]);
  renderStats(stats);
  users = u; links = l;
  const select = $('#clickCode'), prev = select.value;
  select.innerHTML = '<option value="">全部入口</option>';
  links.forEach(x => {
    const o = document.createElement('option');
    o.value = x.code; o.textContent = `${x.name}（${x.code}）`;
    select.append(o);
  });
  select.value = links.some(x => x.code === prev) ? prev : '';
  renderUsers(); renderLinks();
  await Promise.all([loadAudit(), loadClicks()]);
}

(async () => {
  try {
    me = await api('/api/me');
    if (me.role !== 'admin') { document.body.textContent = '无权访问'; return; }
    $('#who').textContent = `${me.username} · 管理员`;
    csrf = me.csrf;
    await refresh();
  } catch (e) {
    $('#globalMessage').textContent = e.message;
  }
})();
