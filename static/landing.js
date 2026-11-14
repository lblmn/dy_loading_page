/* 短链落地页：短码 → 查库 → 展示配置 → 按目标类型执行落地动作。
 *
 * 一份脚本同时服务两种容器：
 *   /r/<code>      独立 landing.html（原始 id）
 *   /?r=<code>     工作台 index.html 内嵌的落地视图（ld- 前缀 id，共用一份 HTML）
 *
 * 六种目标类型：
 *   id / room —— 仅展示配置（ID 队列完整列出，randomOrder 每次打开重新洗牌）
 *   url       —— 自有网页：可见倒计时自动跳转、可取消、渠道参数透传
 *   app       —— 白名单应用：用户主动点击才唤起
 *   video     —— 第三方 App 视频深链：短延时自动拉起，gids 控制上滑队列
 *   live      —— 第三方 App 直播深链：短延时自动拉起
 *
 * 平台拦截规避：检测到内置浏览器 UA 时显示「在浏览器中打开」蒙层并暂停自动拉起；
 * 该能力连同深链生成一起受服务端 LINKLAB_DEEP_LINKS 开关控制。
 */
const params = new URLSearchParams(location.search);
const LANDING_MODE = params.has('r') || location.pathname.startsWith('/r/');
window.LINKLAB_LANDING_MODE = LANDING_MODE;

const code = LANDING_MODE
  ? (params.get('r') || decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || ''))
  : '';
const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                  'utm_content', 'channel', 'ref', 'from'];
const KIND_TEXT = { id: 'ID 队列', url: '网页地址', app: '应用链接', room: '房间',
                    video: '视频深链', live: '直播深链' };

let timer = null, launchTimer = null, deepLink = '';

/* 兼容两套容器的 id：优先取工作台内嵌视图的 ld- 前缀，再退回独立页原 id */
function q(id) {
  return document.querySelector('#ld-' + id) || document.querySelector('#' + id);
}

function row(k, v) {
  const a = document.createElement('span'), b = document.createElement('span');
  a.textContent = k;
  b.textContent = v ?? '—';
  q('kv').append(a, b);
}

function setNote(text) {
  q('kindNote').textContent = text;
}

function stopCountdown(message) {
  if (timer) { clearInterval(timer); timer = null; }
  if (launchTimer) { clearTimeout(launchTimer); launchTimer = null; }
  q('stopBtn').hidden = true;
  q('actionText').textContent = message;
}

function withUtm(target, utm) {
  try {
    const u = new URL(target, location.href);
    Object.entries(utm || {}).forEach(([k, v]) => u.searchParams.set(k, v));
    return u.toString();
  } catch { return target; }
}

function renderIdList(ids, randomOrder) {
  if (!ids.length) return;
  const box = document.createElement('div');
  box.className = 'id-list';
  const title = document.createElement('h3');
  title.textContent = randomOrder ? 'ID 队列（本次已随机洗牌）' : 'ID 队列（按配置顺序）';
  const ol = document.createElement('ol');
  ids.forEach((val, i) => {
    const li = document.createElement('li');
    li.textContent = i === 0 ? `${val}（第 1 个）` : val;
    ol.append(li);
  });
  box.append(title, ol);
  q('kv').after(box);
}

function wechatMask() {
  let mask = q('wechatMask');
  if (!mask) return null;
  mask.hidden = false;
  const copy = q('wechatCopy'), tryBtn = q('wechatTry');
  if (copy) copy.onclick = () => {
    navigator.clipboard?.writeText(location.href);
    copy.textContent = '已复制';
  };
  if (tryBtn) tryBtn.onclick = () => {
    mask.hidden = true;
    if (deepLink) location.href = deepLink;
  };
  return mask;
}

async function applyBrand() {
  try {
    const c = await (await fetch('/api/config')).json();
    const b = c.brand || {};
    if (b.name) {
      document.title = `${b.name} · 短链落地页`;
      if (q('eyebrow')) q('eyebrow').textContent = `${b.name} · 短链解析`;
    }
    if (b.color) document.documentElement.style.setProperty('--brand-accent', b.color);
    if (b.logo) {
      const img = document.createElement('img');
      img.src = b.logo;
      img.alt = '';
      img.className = 'brand-logo';
      document.querySelector('.card')?.prepend(img);
    }
    if (b.notice) {
      const p = document.createElement('p');
      p.className = 'brand-notice';
      p.textContent = b.notice;
      q('kindNote').after(p);
    }
  } catch { /* 品牌配置不可用时使用默认样式 */ }
}

async function main() {
  const qs = new URLSearchParams({ code });
  // 把渠道参数带给公开解析接口：服务端记录来源，并回传用于透传到自有落地页
  for (const [k, v] of params) if (UTM_KEYS.includes(k)) qs.set(k, v);
  const res = await fetch('/api/public/links?' + qs);
  const d = await res.json();
  if (!res.ok) throw new Error(d.error || '解析失败');

  q('title').textContent = d.name;
  row('短码', code);
  row('目标类型', KIND_TEXT[d.kind] || 'ID 队列');
  if (d.platform === 'lite' || d.platform === 'douyin') {
    row('协议前缀', d.platform === 'lite' ? '抖音极速版 snssdk2329' : '抖音 snssdk1128');
  }
  if (d.roomId) row('房间 ID', d.roomId);
  else if (d.kind === 'id' || d.kind === 'video') {
    row('目标 ID', d.targetId);
    row('后续 ID 数', (d.gids || []).length);
  }
  row('创建时间', new Date(d.createdAt).toLocaleString('zh-CN', { hour12: false }));
  row('短链地址', d.url);
  renderIdList(d.displayIds || [], !!d.randomOrder);
  if (Object.keys(d.utmParams || {}).length) {
    row('渠道参数', Object.entries(d.utmParams).map(([k, v]) => `${k}=${v}`).join(' · '));
  }
  await applyBrand();

  const action = q('action');
  const btn = q('launchBtn');
  const note = q('actionNote');
  const text = q('actionText');
  deepLink = d.deepLink || '';

  if (d.kind === 'url' && d.targetUrl) {
    const target = withUtm(d.targetUrl, d.utmParams);
    action.hidden = false;
    btn.hidden = false;
    btn.href = target;
    btn.textContent = '立即打开';
    note.textContent = '倒计时结束后自动跳转到目标网页；期间可随时取消，或点击按钮、复制链接。渠道参数会透传到目标页。';
    const secs = Number(d.autoForwardSeconds || 0);
    if (secs > 0) {
      let left = secs;
      text.textContent = `${left} 秒后自动跳转…`;
      q('stopBtn').hidden = false;
      timer = setInterval(() => {
        left -= 1;
        if (left <= 0) { stopCountdown('正在跳转…'); location.replace(target); return; }
        text.textContent = `${left} 秒后自动跳转…`;
      }, 1000);
      q('stopBtn').textContent = '取消自动跳转';
      q('stopBtn').onclick = () =>
        stopCountdown('已取消自动跳转，请点击上方按钮或复制链接后自行打开。');
    } else {
      text.textContent = '点击上方按钮打开目标网页。';
    }
    setNote('该入口指向一个自有网页地址。自动跳转带可见倒计时并可取消，用户始终可以选择手动打开或复制链接。');
  } else if (d.kind === 'app' && d.targetUrl) {
    action.hidden = false;
    btn.hidden = false;
    btn.href = d.targetUrl;
    btn.textContent = '打开应用';
    text.textContent = '点击上方按钮在你的设备上打开该应用。';
    note.textContent = '应用链接已在服务端白名单内登记，且必须由你主动点击才会唤起。';
    setNote('该入口指向已获授权的应用链接（服务端白名单校验），系统不会静默唤起应用。');
  } else if (deepLink) {
    action.hidden = false;
    btn.hidden = false;
    btn.href = deepLink;
    btn.textContent = d.kind === 'live' ? '打开目标直播' : '打开目标视频';
    note.textContent = '整条 ID 队列进入 gids（含第 1 个 ID），上滑可继续浏览；点击按钮打开抖音目标。';
    const inWeChat = /micromessenger/i.test(navigator.userAgent || '');
    if (inWeChat) {
      text.textContent = '当前是内置浏览器，无法直接拉起 App。';
      wechatMask();
      setNote('检测到内置浏览器：已提示「在浏览器中打开」，自动拉起被暂停以避免被拦截。');
    } else if (Number(d.forceLaunchMs || 0) > 0) {
      const ms = Number(d.forceLaunchMs);
      /* 原站只靠按钮点击（用户手势）拉起。移动端浏览器会静默拦截无手势的
         自定义协议跳转，所以自动拉起只作一次尽力而为的尝试，失败即提示点按钮。 */
      text.textContent = '点击下方按钮打开抖音目标。';
      q('stopBtn').hidden = false;
      q('stopBtn').textContent = '取消自动尝试';
      launchTimer = setTimeout(() => { location.href = deepLink; }, ms);
      const missed = setTimeout(() => {
        if (document.visibilityState === 'visible') {
          text.textContent = '没有自动打开？请点上方「打开目标视频」按钮。';
          setNote('浏览器拦截了无点击的 App 协议跳转；点按钮（用户手势）即可可靠拉起。');
        }
      }, ms + 1200);
      q('stopBtn').onclick = () => {
        clearTimeout(missed);
        stopCountdown('已取消自动尝试，请点击上方按钮或复制链接后自行打开。');
      };
      setNote('参照原站：按钮点击为主，自动拉起仅作尝试；整条队列进 gids，随机顺序每次打开重新洗牌。');
    } else {
      text.textContent = '点击上方按钮打开抖音目标。';
      setNote('服务端 LINKLAB_FORCE_LAUNCH_MS=0：按原站方式只提供手动按钮，不做自动拉起。');
    }
  } else {
    setNote(d.roomId
      ? '该入口记录一个房间 ID，仅用于展示配置，不会自动跳转或唤起任何应用。'
      : d.kind === 'video' || d.kind === 'live'
        ? '服务端未开启 LINKLAB_DEEP_LINKS，深链类型已退化为「仅展示配置」。'
        : '该入口是一组 ID 队列，仅用于展示配置；完整队列已在上方列出。');
  }
}

if (LANDING_MODE) {
  const view = document.querySelector('#landingView');
  if (view) view.hidden = false;
  const login = document.querySelector('#loginView');
  const app = document.querySelector('#appView');
  if (login) login.hidden = true;
  if (app) app.hidden = true;
  q('copyBtn').onclick = async (e) => {
    try {
      await navigator.clipboard.writeText(location.href);
      e.target.textContent = '已复制';
      setTimeout(() => { e.target.textContent = '复制链接'; }, 1200);
    } catch { /* 剪贴板不可用时忽略 */ }
  };
  main().catch((e) => {
    q('title').textContent = '链接不存在或已失效';
    setNote(e.message);
  });
}
