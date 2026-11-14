#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LinkLab —— 短链 / 二维码管理后台

零第三方依赖，只用 Python 标准库（需要 Python 3.10+）。
全部运行参数通过 LINKLAB_* 环境变量注入，完整清单见随包 config.example.env。

【部署安全默认】
  * 默认只监听 127.0.0.1。对外提供服务必须显式设置 LINKLAB_HOST=0.0.0.0，
    并且用 Nginx / Caddy 做 HTTPS 反向代理，同时开启 LINKLAB_SECURE_COOKIE=1。
  * 首次启动不会写入任何弱口令：管理员密码取 LINKLAB_ADMIN_PASSWORD，
    未设置则随机生成并在控制台打印一次（只显示一次，请立即保存）。
  * LINKLAB_DEV_MODE=1 才会创建固定演示账号，生产环境切勿开启。
  * 建议设置 LINKLAB_PUBLIC_BASE_URL=https://你的域名，避免短链域名被 Host 头污染。

【落地能力】除「仅展示配置 / 自有网页 / 白名单应用」外，还支持可选的第三方 App
深链模式（LINKLAB_DEEP_LINKS，默认开启）：按 ID 队列生成 push_detail 深链、
按 room_id 生成直播深链、按平台切换协议前缀、落地页短延时拉起并提示在外部
浏览器打开。该模式面向自有/已授权内容与本人设备，可用环境变量一键关闭回到
纯展示模式；关闭后服务端不生成任何第三方协议。
"""

import csv
import hashlib
import hmac
import io
import json
import mimetypes
import os
import random
import re
import secrets
import sqlite3
import sys
import threading
import time
import traceback
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def env(key, default=None):
    return os.environ.get("LINKLAB_" + key, default)


def env_int(key, default):
    try:
        return int(env(key, default))
    except (TypeError, ValueError):
        return default


def env_bool(key, default=False):
    v = env(key)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


HOST = env("HOST", "127.0.0.1")
PORT = env_int("PORT", 8787)
DB_FILE = Path(env("DB", str(ROOT / "linklab.db"))).resolve()
PUBLIC_BASE_URL = (env("PUBLIC_BASE_URL") or "").rstrip("/")
SECURE_COOKIE = env_bool("SECURE_COOKIE", False)
DEV_MODE = env_bool("DEV_MODE", False)
ADMIN_PASSWORD = env("ADMIN_PASSWORD")
IS_LOCAL = HOST in ("127.0.0.1", "localhost", "::1")

LOGIN_MAX_ATTEMPTS = env_int("LOGIN_MAX_ATTEMPTS", 5)
LOGIN_WINDOW = env_int("LOGIN_WINDOW", 60)
LOG_REQUESTS = env_bool("LOG_REQUESTS", True)
TRUST_PROXY = env_bool("TRUST_PROXY", False)
# 教学开关：True 时强制「一号一设备」。默认关闭，避免清缓存后把自己锁在外面。
STRICT_DEVICE_BINDING = env_bool("STRICT_DEVICE_BINDING", False)
MIN_PASSWORD_LENGTH = env_int("MIN_PASSWORD_LENGTH", 8)

# 应用链接白名单：只有你自己拥有或已获授权的应用才允许被唤起。
# 逗号分隔的前缀列表，例如 https://yourapp.example.com/ ，myapp://
# 留空则禁用「应用链接」类型，从根上杜绝写入未授权的第三方协议。
APP_LINK_ALLOWLIST = [x.strip() for x in (env("APP_LINK_ALLOWLIST") or "").split(",") if x.strip()]
# 网页目标自动跳转前的倒计时秒数；0 表示不自动跳转，只显示按钮
AUTO_FORWARD_SECONDS = max(0, env_int("AUTO_FORWARD_SECONDS", 3))

# 分享短链自动解析：粘贴 v.douyin.com 短链时由服务端跟随重定向取真实 ID。
# 关闭后行为回到旧版（短链不含 ID，只能按原文保存 / 报错）。
RESOLVE_SHORT_LINKS = env_bool("RESOLVE_SHORT_LINKS", True)
RESOLVE_TIMEOUT = max(1, env_int("RESOLVE_TIMEOUT", 6))  # 单次解析超时秒数

# 视频深链队尾垫底：实测抖音 push_detail 的 gids 最后一项会被播放，
# 但队列只有用户 ID 时末项位置会回落推荐流（N 个只有前 N-1 个正常）。
# 在真实队列末尾追加一个「不存在的错误 ID」占住末位：抖音取不到内容，
# 该位置自然回落推荐流（= 最后一个视频随机播放），客户的全部真实 ID 正常播放。
# 垫底只进 gids，不进展示列表、不参与洗牌。
GID_PAD = env_bool("GID_PAD", True)
GID_PAD_IDS = [x.strip() for x in (env("GID_PAD_IDS")
               or "9999999999999999999").split(",") if x.strip().isdigit()]

# ---------- 第三方 App 深链（对齐原站语义，可整体关闭）----------
DEEP_LINKS = env_bool("DEEP_LINKS", True)          # 关闭后 video/live 类型退化为仅展示
FORCE_LAUNCH_MS = max(0, env_int("FORCE_LAUNCH_MS", 260))  # 落地页拉起延时，0 = 只给按钮
SCHEME_MAIN = "snssdk1128://"                       # 主版
SCHEME_LITE = "snssdk2329://"                       # 极速版
UTM_PASSTHROUGH = env_bool("UTM_PASSTHROUGH", True)  # 渠道参数透传到自有网页
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "channel", "ref", "from")

# ---------- 落地页品牌化 ----------
BRAND_NAME = (env("BRAND_NAME") or "LinkLab")[:40]
BRAND_LOGO = (env("BRAND_LOGO") or "")[:200]
BRAND_COLOR = env("BRAND_COLOR") or ""
if not re.fullmatch(r"#[0-9a-fA-F]{6}", BRAND_COLOR):
    BRAND_COLOR = ""
BRAND_NOTICE = (env("BRAND_NOTICE") or "")[:200]

PBKDF2_ROUNDS = 200_000
SESSION_DAYS = env_int("SESSION_DAYS", 7)
# 用户名不存在时也做一次等价的哈希计算，抹平时序差异，防止账号枚举
DUMMY_SALT, DUMMY_HASH = "00" * 16, "00" * 32

# 登录限流：按 (来源 IP, 用户名) 的滑动窗口计数。单进程内存版，够小项目用；
# 多副本部署请换成 Redis 等共享存储。
_login_hits = defaultdict(deque)
_login_lock = threading.Lock()


def _rate_blocked(key):
    now = time.monotonic()
    with _login_lock:
        q = _login_hits[key]
        while q and q[0] <= now - LOGIN_WINDOW:
            q.popleft()
        return len(q) >= LOGIN_MAX_ATTEMPTS


def _rate_fail(key):
    with _login_lock:
        _login_hits[key].append(time.monotonic())


def _rate_clear(key):
    with _login_lock:
        _login_hits[key].clear()




def utcnow() -> str:
    """统一用 ISO 8601 UTC 字符串存时间，字符串比较即可判断先后。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utcplus(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


@contextmanager
def db():
    """每次请求一个连接；退出时提交并关闭。row_factory 让结果可以像字典一样取列。"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 多线程写入时等待锁而不是立刻抛 database is locked
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """绝不存明文。salt 每个账号独立，PBKDF2 拉伸 20 万轮抵御彩虹表/暴力破解。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return salt, digest


def verify_password(password: str, salt: str, digest: str) -> bool:
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    # compare_digest 是常数时间比较，避免时序侧信道
    return hmac.compare_digest(calc, digest)


def init_db():
    with db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT NOT NULL UNIQUE,
                salt         TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role         TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
                expires_at   TEXT,
                device_code  TEXT,
                enabled      INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                sid         TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf        TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS links (
                code         TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                platform     TEXT NOT NULL DEFAULT 'web',
                kind         TEXT NOT NULL DEFAULT 'id',
                target_id    TEXT NOT NULL DEFAULT '',
                room_id      TEXT NOT NULL DEFAULT '',
                gids         TEXT NOT NULL DEFAULT '[]',
                random_order INTEGER NOT NULL DEFAULT 0,
                target_url   TEXT NOT NULL DEFAULT '',
                clicks       INTEGER NOT NULL DEFAULT 0,
                last_click_at TEXT,
                enabled      INTEGER NOT NULL DEFAULT 1,
                expires_at   TEXT,
                owner_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS click_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                code       TEXT NOT NULL,
                referer    TEXT NOT NULL DEFAULT '',
                ua         TEXT NOT NULL DEFAULT '',
                ip         TEXT NOT NULL DEFAULT '',
                query      TEXT NOT NULL DEFAULT '',
                utm        TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                username   TEXT NOT NULL DEFAULT '',
                action     TEXT NOT NULL,
                target     TEXT NOT NULL DEFAULT '',
                detail     TEXT NOT NULL DEFAULT '',
                ip         TEXT NOT NULL DEFAULT '',
                ok         INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_links_owner ON links(owner_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_clicks_code ON click_events(code);
            CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at);
        """)
        # 幂等迁移：老数据库可能缺少新增列，启动时自动补齐（演示 schema migration）
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
        if "enabled" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        link_cols = [r[1] for r in c.execute("PRAGMA table_info(links)")]
        for col, ddl in (("kind", "TEXT NOT NULL DEFAULT 'id'"),
                         ("target_url", "TEXT NOT NULL DEFAULT ''"),
                         ("clicks", "INTEGER NOT NULL DEFAULT 0"),
                         ("last_click_at", "TEXT"),
                         ("enabled", "INTEGER NOT NULL DEFAULT 1"),
                         ("expires_at", "TEXT")):
            if col not in link_cols:
                c.execute(f"ALTER TABLE links ADD COLUMN {col} {ddl}")
        click_cols = [r[1] for r in c.execute("PRAGMA table_info(click_events)")]
        for col, ddl in (("query", "TEXT NOT NULL DEFAULT ''"),
                         ("utm", "TEXT NOT NULL DEFAULT ''")):
            if col not in click_cols:
                c.execute(f"ALTER TABLE click_events ADD COLUMN {col} {ddl}")
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            # 首次初始化：绝不写入固定弱口令
            seeds = []
            if DEV_MODE:
                # 仅本地开发/自动化测试使用；生产开启会立刻产生可被猜测的管理员账号
                seeds = [("admin", "admin123", "admin", None),
                         ("student", "student123", "user", 30)]
                print("[LinkLab] 开发模式：已创建演示账号 admin/admin123、student/student123")
            else:
                pw = ADMIN_PASSWORD or secrets.token_urlsafe(14)
                seeds = [("admin", pw, "admin", None)]
                if ADMIN_PASSWORD:
                    print("[LinkLab] 已使用 LINKLAB_ADMIN_PASSWORD 初始化管理员账号")
                else:
                    print("=" * 66)
                    print("[LinkLab] 初始管理员密码（仅显示一次，请立即保存）：")
                    print(f"           admin / {pw}")
                    print("=" * 66)
            for name, pw, role, days in seeds:
                salt, digest = hash_password(pw)
                c.execute(
                    "INSERT INTO users(username,salt,password_hash,role,expires_at,created_at) VALUES(?,?,?,?,?,?)",
                    (name, salt, digest, role, utcplus(days) if days else None, utcnow()),
                )


_ID_RE = re.compile(
    r"(?:item_ids?=|/video/|/share/(?:video|slides?)/)(\d{6,25})"
    r"|(?<!\d)(\d{8,20})(?!\d)"
)

# 抖音分享短链（可带可不带 scheme），以及短链解析结果缓存
_SHORT_URL_RE = re.compile(
    r"(?:https?://)?v\.douyin\.com/[A-Za-z0-9_-]{4,32}"
    r"|(?:https?://)?www\.iesdouyin\.com/share/[^\s\"'<>，。；、]+",
    re.I)
_SHORT_LINK_ID_RE = re.compile(r"/(?:video|note)/(\d{6,25})")
# live.douyin.com/<网页房间号> 只是展示用的短号，真实 room_id 要再解一次
_LIVE_WEB_URL_RE = re.compile(r"(?:https?://)?live\.douyin\.com/(\d{5,25})", re.I)

_resolve_cache: dict[str, str] = {}
_resolve_lock = threading.Lock()

# 不跟随重定向的 opener：直播间链接只需 HEAD 一次，从 Location 头拿真实房间号
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)

_RESOLVE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X)"
               " AppleWebKit/603.1.30 (KHTML, like Gecko) Version/10.0"
               " Mobile/14E304 Safari/602.1")


def _cache_resolve(url: str, rid: str) -> None:
    with _resolve_lock:
        # 只缓存成功结果，失败下次仍可重试（网络抖动不该被记住）
        if len(_resolve_cache) > 512:
            _resolve_cache.clear()
        _resolve_cache[url] = rid


def resolve_live_room(url: str) -> str:
    """live.douyin.com/<网页房间号> → 真实 room_id：
    HEAD 一次（不跟随重定向），从 Location 头提取 19 位真实房间号；
    HEAD 被拒（405/403）或无重定向时退回 GET 跟随重定向看最终 URL。
    解析失败返回空串。"""
    url = url.strip()
    if not url.lower().startswith("http"):
        url = "https://" + url
    with _resolve_lock:
        cached = _resolve_cache.get(url)
    if cached is not None:
        return cached
    location = ""
    rid = ""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": _RESOLVE_UA})
        try:
            with _NO_REDIRECT_OPENER.open(req, timeout=RESOLVE_TIMEOUT) as resp:
                location = resp.headers.get("Location", "") or resp.geturl() or ""
        except urllib.error.HTTPError as e:
            # 3xx 会被上面的 opener 转成 HTTPError，Location 就在错误响应头里
            location = e.headers.get("Location", "") if e.headers else ""
            if not location or e.code in (403, 405, 501):
                # HEAD 被拒 → 退回 GET 跟随重定向
                greq = urllib.request.Request(url, headers={"User-Agent": _RESOLVE_UA})
                with urllib.request.urlopen(greq, timeout=RESOLVE_TIMEOUT) as resp:
                    location = resp.geturl() or ""
    except (urllib.error.URLError, OSError, ValueError):
        location = ""
    if location:
        # 真实 room_id 是 19 位雪花号，Location 里先出现的即目标
        m = re.search(r"(?<!\d)(\d{19})(?!\d)", location)
        if not m:
            m = _LIVE_WEB_URL_RE.search(location)
        rid = m.group(1) if m else ""
    if rid:
        _cache_resolve(url, rid)
    return rid


def resolve_short_link(url: str) -> str:
    """把 v.douyin.com 等分享短链跟随重定向到最终 URL，从中提取
    视频 ID（/video/<id>、/note/<id>）或直播间 ID（live.douyin.com/<id>）。
    解析失败返回空串。结果按短链缓存，避免重复网络请求。"""
    url = url.strip()
    if not url.lower().startswith("http"):
        url = "https://" + url
    with _resolve_lock:
        cached = _resolve_cache.get(url)
    if cached is not None:
        return cached
    final = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _RESOLVE_UA})
        with urllib.request.urlopen(req, timeout=RESOLVE_TIMEOUT) as resp:
            final = resp.geturl() or ""
    except (urllib.error.URLError, OSError, ValueError):
        final = ""
    rid = ""
    m = _SHORT_LINK_ID_RE.search(final)
    if m:
        rid = m.group(1)
    else:
        m = _LIVE_WEB_URL_RE.search(final)
        if m:
            # 短链最终落在直播间网页链接 → 继续解出真实 room_id
            rid = resolve_live_room("https://live.douyin.com/" + m.group(1))
        else:
            # 直播分享短链最终可能落在 webcast.amemv.com/.../reflow/<19位room_id>
            # 等无显式路径的页面，按实测语义从最终 URL 抓 19 位雪花号
            m = re.search(r"(?<!\d)(\d{19})(?!\d)", final)
            if m:
                rid = m.group(0)
            elif not final:
                # GET 失败 → 按分享短链实测语义改用 HEAD 跟随重定向再取最终 URL
                try:
                    hreq = urllib.request.Request(url, method="HEAD",
                                                  headers={"User-Agent": _RESOLVE_UA})
                    with urllib.request.urlopen(hreq, timeout=RESOLVE_TIMEOUT) as resp:
                        final = resp.geturl() or ""
                except (urllib.error.URLError, OSError, ValueError):
                    final = ""
                m = _SHORT_LINK_ID_RE.search(final)
                if m:
                    rid = m.group(1)
                else:
                    m = _LIVE_WEB_URL_RE.search(final)
                    if m:
                        rid = resolve_live_room("https://live.douyin.com/" + m.group(1))
                    else:
                        m = re.search(r"(?<!\d)(\d{19})(?!\d)", final)
                        if m:
                            rid = m.group(0)
    if rid:
        _cache_resolve(url, rid)
    return rid


def parse_targets(text) -> list[str]:
    """原站「粘贴整段分享文案 → 解析 item_id」的完整版：
    优先识别 item_id= / /video/<id> / /share/video/<id>，其次按出现顺序抓
    8~20 位数字 ID，去重后返回整条队列。文案里带分享短链 / 直播间网页链接时，
    由服务端跟随重定向解析出真实视频 ID / room_id 并前置（已是纯 ID 的输入
    不做任何转换）；直播链接 URL 路径里的网页房间号不是真实 room_id，
    解析成功后会从结果中剔除。"""
    text = str(text or "")
    out = []
    for m in _ID_RE.finditer(text):
        val = next((g for g in m.groups() if g), "")
        if val and val not in out:
            out.append(val)
    if not RESOLVE_SHORT_LINKS:
        return out
    # 文案里带分享短链 / 直播间链接 → 以解析出的真实 ID 为准（前置）
    resolved = []
    for m in _SHORT_URL_RE.finditer(text):
        val = resolve_short_link(m.group(0))
        if val and val not in resolved:
            resolved.append(val)
    for m in _LIVE_WEB_URL_RE.finditer(text):
        val = resolve_live_room(m.group(0))
        if val and val not in resolved:
            resolved.append(val)
    if resolved:
        # 直播链接路径里的网页房间号会被裸数字通道误抓，解析成功后剔除
        web_ids = {m.group(1) for m in _LIVE_WEB_URL_RE.finditer(text)}
        out = [x for x in out if x not in web_ids]
        return resolved + [x for x in out if x not in resolved]
    return out


def parse_target(text) -> str:
    ids = parse_targets(text)
    if ids:
        return ids[0]
    text = str(text or "").strip()
    # 短链/URL 解析不出 ID 时返回空串，让创建接口给出明确报错，
    # 而不是把整条 URL 当 ID 存进数据库
    if _SHORT_URL_RE.search(text) or text.lower().startswith(("http://", "https://")):
        return ""
    return text[:120]


def normalize_utm(q: dict) -> dict:
    """只透传白名单内的渠道参数，避免把任意 query 打到自有落地页。"""
    if not UTM_PASSTHROUGH:
        return {}
    return {k: (q.get(k) or [""])[0][:80]
            for k in UTM_KEYS if (q.get(k) or [""])[0]}


def build_deep_link(row, ids: list[str]) -> str:
    """按原站落地页内联脚本逐字语义拼第三方 App 深链：
    - platform=lite → snssdk2329://，其余 → snssdk1128://
    - 队列 = Set([targetId, ...gids])，randomOrder 时整条队列一起洗牌
    - video → aweme/push_detail?item_id=<队列第1个>&hot=feed&cold=feed
              &gids=<整条队列，含第 1 个 ID>（原站 ids.join(','），不是「后续队列」）
    - live  → live?room_id=<房间号>
    关闭 LINKLAB_DEEP_LINKS 后返回空串，落地页退化为「仅展示配置」。"""
    if not DEEP_LINKS:
        return ""
    prefix = SCHEME_LITE if row["platform"] == "lite" else SCHEME_MAIN
    if row["kind"] == "video" and ids:
        queue = quote(",".join(ids), safe=",")
        return (f"{prefix}aweme/push_detail?item_id={quote(ids[0], safe='')}"
                f"&hot=feed&cold=feed&gids={queue}")
    if row["kind"] == "live" and row["room_id"]:
        return f"{prefix}live?room_id={quote(row['room_id'], safe='')}"
    return ""


def link_dict(row, include_owner: bool = True) -> dict:
    enabled = bool(row["enabled"]) if "enabled" in row.keys() else True
    expires = row["expires_at"] if "expires_at" in row.keys() else None
    d = {
        "code": row["code"],
        "url": "",  # 由调用方按 Host 补全
        "name": row["name"],
        "platform": row["platform"],
        "kind": row["kind"] if "kind" in row.keys() else "id",
        "targetUrl": row["target_url"] if "target_url" in row.keys() else "",
        "randomOrder": bool(row["random_order"]),
        "targetId": row["target_id"],
        "roomId": row["room_id"],
        "gids": json.loads(row["gids"] or "[]"),
        "clicks": row["clicks"] if "clicks" in row.keys() else 0,
        "lastClickAt": row["last_click_at"] if "last_click_at" in row.keys() else None,
        "enabled": enabled,
        "expiresAt": expires,
        "status": "disabled" if not enabled
                   else ("expired" if expires and expires < utcnow() else "active"),
        "createdAt": row["created_at"],
    }
    if include_owner:
        d["ownerId"] = row["owner_id"]
        d["ownerName"] = row["owner_name"] if "owner_name" in row.keys() else None
    return d


class HTTPError(Exception):
    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg


class Handler(BaseHTTPRequestHandler):
    server_version = "LinkLab"
    sys_version = ""      # 不向客户端暴露 Python 版本
    timeout = 15          # socket 超时，缓解慢速连接长期占用线程

    # ---------- 底层响应工具 ----------
    def _send(self, status, data: bytes, ctype="text/html; charset=utf-8",
              set_cookie=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'",
        )
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, status, msg):
        self._json(status, {"error": msg})

    def _file(self, rel: str):
        """静态文件：先解析成绝对路径，确认仍在 STATIC 目录内，防目录穿越。"""
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return self._err(404, "文件不存在")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def _redirect(self, location: str):
        """服务端页面级鉴权用：未登录访问后台页时直接 302，而不是靠前端隐藏按钮。"""
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise HTTPError(400, "请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPError(400, "请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise HTTPError(400, "请求体应为 JSON 对象")
        return data

    # ---------- 鉴权 ----------
    def _current_user(self):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except Exception:
            return None
        if "linklab_sid" not in jar:
            return None
        sid = jar["linklab_sid"].value
        with db() as c:
            row = c.execute(
                "SELECT u.*, s.csrf AS session_csrf, s.expires_at AS session_expires "
                "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.sid = ?",
                (sid,),
            ).fetchone()
        if not row or row["session_expires"] < utcnow():
            return None
        if row["enabled"] == 0:
            return None  # 被禁用后，已有会话也立即失效
        if row["expires_at"] and row["expires_at"] < utcnow():
            return None  # 账号到期
        return dict(row)

    def _require(self, admin=False):
        u = self._current_user()
        if not u:
            raise HTTPError(401, "请先登录")
        if admin and u["role"] != "admin":
            raise HTTPError(403, "无权访问")
        return u

    def _check_csrf(self, u):
        token = self.headers.get("X-CSRF-Token") or ""
        if not hmac.compare_digest(token, u["session_csrf"] or ""):
            raise HTTPError(403, "请求验证失败，请刷新页面（CSRF 校验未通过）")

    def _guard_self(self, admin, uid):
        """禁止管理员删除/禁用/降级自己，避免把自己锁在系统外面。"""
        if uid == admin["id"]:
            raise HTTPError(403, "不能对自己执行该操作（防止系统失去管理员）")

    def _client_ip(self) -> str:
        """真实来源 IP。反代场景需显式开启 TRUST_PROXY 才采信 X-Forwarded-For。"""
        ip = self.client_address[0]
        if TRUST_PROXY:
            xff = self.headers.get("X-Forwarded-For") or ""
            if xff:
                ip = xff.split(",")[0].strip()[:64]
        return ip

    def _audit(self, user, action: str, target: str = "", detail: str = "",
               ok: bool = True, conn=None):
        """写审计日志：谁、在什么时候、做了什么、结果如何。审计失败不影响主流程。
        调用方若已持有业务写事务，必须传 conn 复用同一连接 —— SQLite 单写者，
        另开连接写 audit 会等到 busy_timeout 超时（表现为请求固定慢 5 秒）。"""
        try:
            values = ((user or {}).get("id"), (user or {}).get("username", ""),
                      action, str(target)[:120], str(detail)[:500], self._client_ip(),
                      1 if ok else 0, utcnow())
            sql = ("INSERT INTO audit_log(user_id,username,action,target,detail,ip,ok,created_at) "
                   "VALUES(?,?,?,?,?,?,?,?)")
            if conn is not None:
                conn.execute(sql, values)
            else:
                with db() as c:
                    c.execute(sql, values)
        except Exception:
            pass

    def _base_url(self):
        # 生产环境应配置 PUBLIC_BASE_URL，否则生成的短链域名会受 Host 头影响
        if PUBLIC_BASE_URL:
            return PUBLIC_BASE_URL
        host = self.headers.get("Host") or f"{HOST}:{PORT}"
        if not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]{1,253}", host):
            raise HTTPError(400, "非法 Host 请求头")
        scheme = "https" if SECURE_COOKIE else "http"
        return f"{scheme}://{host}"

    # ---------- 路由 ----------
    def do_GET(self):    self._dispatch("GET")
    def do_POST(self):   self._dispatch("POST")
    def do_PUT(self):    self._dispatch("PUT")
    def do_PATCH(self):  self._dispatch("PATCH")
    def do_DELETE(self): self._dispatch("DELETE")
    def do_HEAD(self):   self._dispatch("GET")

    def log_message(self, fmt, *args):
        if not LOG_REQUESTS:
            return
        # 只打印路径，不打 query（短码等参数可能敏感）
        path = self.path.split("?", 1)[0]
        print(f"  {self.command:6} {path}")

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            self._route(method, path, query)
        except HTTPError as e:
            self._err(e.status, e.msg)
        except (ValueError, TypeError) as e:
            self._err(400, f"请求参数错误：{e}")
        except Exception:
            traceback.print_exc()
            self._err(500, "服务器内部错误")

    def _route(self, method, path, q):
        # --- 页面 / 静态资源 ---
        if method == "GET" and path in ("/", "/login"):
            return self._file("index.html")
        if method == "GET" and path == "/admin":
            # 页面级鉴权：服务端就拦住，前端隐藏按钮只是体验，不是安全边界
            visitor = self._current_user()
            if not visitor:
                return self._redirect("/login")
            if visitor["role"] != "admin":
                return self._err(403, "无权访问")
            return self._file("admin.html")
        if method == "GET" and path.startswith("/r/"):
            return self._file("landing.html")
        if method == "GET" and path.startswith("/static/"):
            rel = path[len("/static/"):]
            # 页面模板只通过 /、/login、/admin、/r/<code> 路由提供；
            # 不允许从 /static/ 直接下载模板或配置类文件
            if Path(rel).suffix.lower() in (".html", ".py", ".db", ".ini", ".env", ".txt"):
                return self._err(404, "文件不存在")
            return self._file(rel)
        if method == "GET" and path == "/favicon.ico":
            return self._err(404, "文件不存在")

        # --- 健康检查（供反向代理 / 容器探活）---
        if method == "GET" and path == "/healthz":
            return self._json(200, {"ok": True})

        # --- 前端需要的非敏感运行配置；演示账号只在开发模式下下发 ---
        if method == "GET" and path == "/api/config":
            return self._json(200, {
                "devMode": DEV_MODE,
                "secureCookie": SECURE_COOKIE,
                "brandTag": "教学演示 · 仅本机" if DEV_MODE else "工作台",
                "deepLinks": DEEP_LINKS,
                "forceLaunchMs": FORCE_LAUNCH_MS,
                "utmPassthrough": UTM_PASSTHROUGH,
                "brand": {
                    "name": BRAND_NAME,
                    "logo": BRAND_LOGO if BRAND_LOGO.startswith("/static/") else "",
                    "color": BRAND_COLOR,
                    "notice": BRAND_NOTICE,
                },
                "demoAccounts": [
                    {"username": "admin", "password": "admin123"},
                    {"username": "student", "password": "student123"},
                ] if DEV_MODE else [],
            })

        # --- 登录（唯一不需要会话的接口）---
        if method == "POST" and path == "/api/login":
            return self._login(self._body())

        # --- 公开解析接口：免登录，且只返回必要字段（不泄漏 owner）---
        # /api/link?code= 是原站风格的兼容别名，与 /api/public/links 行为一致
        if method == "GET" and path in ("/api/public/links", "/api/link"):
            return self._public_link((q.get("code") or [""])[0], q)

        # --- 以下都需要会话 ---
        u = self._require()
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            self._check_csrf(u)

        if method == "GET" and path == "/api/me":
            return self._json(200, {
                "id": u["id"], "username": u["username"], "role": u["role"],
                "expiresAt": u["expires_at"], "csrf": u["session_csrf"],
                "deviceBound": bool(u["device_code"]),
            })

        if method == "POST" and path == "/api/logout":
            jar = SimpleCookie()
            jar.load(self.headers.get("Cookie") or "")
            sid = jar["linklab_sid"].value if "linklab_sid" in jar else ""
            with db() as c:
                c.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
            clear = "linklab_sid=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            if SECURE_COOKIE:
                clear += "; Secure"
            return self._send(200, b'{"ok":true}', "application/json; charset=utf-8", clear)

        # --- 入口 CRUD ---
        if method == "GET" and path == "/api/links":
            show_all = (q.get("all") or [""])[0] == "1" and u["role"] == "admin"
            keyword = (q.get("q") or [""])[0].strip()[:80]
            sort = (q.get("sort") or ["created_at"])[0]
            if sort not in ("created_at", "clicks", "name", "last_click_at"):
                sort = "created_at"
            order = "ASC" if (q.get("order") or [""])[0].lower() == "asc" else "DESC"
            paged = "page" in q or "size" in q
            page = max(1, int((q.get("page") or ["1"])[0]))
            size = min(100, max(1, int((q.get("size") or ["20"])[0])))
            where, args = [], []
            if not show_all:
                where.append("l.owner_id = ?")
                args.append(u["id"])
            if keyword:
                where.append("(l.name LIKE ? OR l.code LIKE ? OR l.target_id LIKE ? "
                             "OR l.target_url LIKE ? OR l.room_id LIKE ? OR u.username LIKE ?)")
                args += [f"%{keyword}%"] * 6
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            with db() as c:
                total = c.execute(
                    "SELECT COUNT(*) FROM links l JOIN users u ON u.id=l.owner_id" + clause,
                    args).fetchone()[0]
                sql = ("SELECT l.*, u.username AS owner_name FROM links l "
                       "JOIN users u ON u.id=l.owner_id" + clause
                       + f" ORDER BY l.{sort} {order}, l.code {order}")
                if paged:
                    sql += " LIMIT ? OFFSET ?"
                    args = args + [size, (page - 1) * size]
                rows = c.execute(sql, args).fetchall()
            items = [link_dict(r) for r in rows]
            for it in items:
                it["url"] = f"{self._base_url()}/r/{it['code']}"
            # 不带分页参数时保持旧版「返回数组」的契约，老调用方零改动
            if paged:
                return self._json(200, {"items": items, "total": total,
                                        "page": page, "size": size})
            return self._json(200, items)

        if method == "POST" and path == "/api/links":
            return self._create_link(self._body(), u)

        m = re.fullmatch(r"/api/links/([A-Za-z0-9_-]{3,32})", path)
        if m and method in ("PUT", "PATCH", "DELETE"):
            body = self._body() if method in ("PUT", "PATCH") else {}
            return self._modify_link(m.group(1), method, body, u)

        # --- 管理员后台：统计 / 账号管理 ---
        if method == "GET" and path == "/api/admin/stats":
            self._require(admin=True)
            with db() as c:
                total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                total_admins = c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
                total_links = c.execute("SELECT COUNT(*) FROM links").fetchone()[0]
                today = utcnow()[:10]
                today_links = c.execute(
                    "SELECT COUNT(*) FROM links WHERE substr(created_at,1,10)=?", (today,)).fetchone()[0]
                disabled = c.execute("SELECT COUNT(*) FROM users WHERE enabled=0").fetchone()[0]
                expired = c.execute(
                    "SELECT COUNT(*) FROM users WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (utcnow(),)).fetchone()[0]
                by_owner = [dict(r) for r in c.execute(
                    "SELECT u.username AS name, COUNT(l.code) AS n FROM users u "
                    "LEFT JOIN links l ON l.owner_id=u.id GROUP BY u.id ORDER BY n DESC")]
                recent = [dict(r) for r in c.execute(
                    "SELECT l.code, l.name, l.created_at, u.username AS owner FROM links l "
                    "JOIN users u ON u.id=l.owner_id ORDER BY l.created_at DESC LIMIT 5")]
                total_clicks = c.execute("SELECT COUNT(*) FROM click_events").fetchone()[0]
                today_clicks = c.execute(
                    "SELECT COUNT(*) FROM click_events WHERE substr(created_at,1,10)=?",
                    (today,)).fetchone()[0]
                top_links = [dict(r) for r in c.execute(
                    "SELECT l.code, l.name, l.clicks, u.username AS owner FROM links l "
                    "JOIN users u ON u.id=l.owner_id WHERE l.clicks > 0 "
                    "ORDER BY l.clicks DESC LIMIT 5")]
                recent_clicks = [dict(r) for r in c.execute(
                    "SELECT code, referer, ua, ip, created_at FROM click_events "
                    "ORDER BY id DESC LIMIT 10")]
            return self._json(200, {
                "users": total_users, "admins": total_admins, "links": total_links,
                "todayLinks": today_links, "disabled": disabled, "expired": expired,
                "byOwner": by_owner, "recent": recent,
                "totalClicks": total_clicks, "todayClicks": today_clicks,
                "topLinks": top_links, "recentClicks": recent_clicks,
            })

        if method == "GET" and path == "/api/admin/audit":
            self._require(admin=True)
            with db() as c:
                rows = c.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
            return self._json(200, [{
                "id": r["id"], "username": r["username"], "action": r["action"],
                "target": r["target"], "detail": r["detail"], "ip": r["ip"],
                "ok": bool(r["ok"]), "createdAt": r["created_at"],
            } for r in rows])

        # --- 点击明细报表：按天趋势 / 来源分布 / 渠道参数 / 明细 / CSV 导出 ---
        if method == "GET" and path in ("/api/admin/clicks", "/api/admin/clicks.csv"):
            return self._clicks_report(path.endswith(".csv"), q)

        if method == "GET" and path == "/api/users":
            self._require(admin=True)
            with db() as c:
                rows = c.execute(
                    "SELECT u.*, (SELECT COUNT(*) FROM links l WHERE l.owner_id=u.id) AS link_count "
                    "FROM users u ORDER BY u.id").fetchall()
            return self._json(200, [{
                "id": r["id"], "username": r["username"], "role": r["role"],
                "expiresAt": r["expires_at"], "enabled": bool(r["enabled"]),
                "deviceBound": bool(r["device_code"]), "linkCount": r["link_count"],
                "createdAt": r["created_at"],
            } for r in rows])

        if method == "POST" and path == "/api/users":
            admin = self._require(admin=True)
            return self._create_user(self._body(), admin)

        m = re.fullmatch(r"/api/users/(\d+)", path)
        if m and method in ("PUT", "DELETE"):
            admin = self._require(admin=True)
            uid = int(m.group(1))
            self._guard_self(admin, uid)
            with db() as c:
                target_row = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
                if not target_row:
                    raise HTTPError(404, "账号不存在")
                if method == "DELETE":
                    # 外键 ON DELETE CASCADE 会一并清掉该用户的入口和会话
                    c.execute("DELETE FROM users WHERE id = ?", (uid,))
                    self._audit(admin, "user.delete", target_row["username"], "删除账号", conn=c)
                    return self._json(200, {"ok": True})
                body = self._body()
                row = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
                role = body.get("role", row["role"])
                if role not in ("user", "admin"):
                    raise HTTPError(400, "role 只能是 user 或 admin")
                enabled = 1 if body.get("enabled", bool(row["enabled"])) else 0
                if "days" in body:
                    days = body["days"]
                    expires = utcplus(int(days)) if isinstance(days, int) and 0 < days < 3650 else None
                else:
                    expires = row["expires_at"]
                c.execute("UPDATE users SET role=?, enabled=?, expires_at=? WHERE id=?",
                          (role, enabled, expires, uid))
            self._audit(admin, "user.update", target_row["username"],
                        f"role={role} enabled={bool(enabled)}")
            return self._json(200, {"ok": True})

        m = re.fullmatch(r"/api/users/(\d+)/reset-password", path)
        if m and method == "POST":
            admin = self._require(admin=True)
            uid = int(m.group(1))
            self._guard_self(admin, uid)
            password = str(self._body().get("password") or "")
            if len(password) < MIN_PASSWORD_LENGTH:
                raise HTTPError(400, f"密码至少 {MIN_PASSWORD_LENGTH} 位")
            salt, digest = hash_password(password)
            with db() as c:
                if not c.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
                    raise HTTPError(404, "账号不存在")
                c.execute("UPDATE users SET salt=?, password_hash=? WHERE id=?", (salt, digest, uid))
                # 改密码后让该账号旧的会话全部失效（安全实践：凭证变更即踢下线）
                c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
            self._audit(admin, "user.reset_password", uid, "重置密码并清除其会话")
            return self._json(200, {"ok": True})

        m = re.fullmatch(r"/api/users/(\d+)/reset-device", path)
        if m and method == "POST":
            admin = self._require(admin=True)
            with db() as c:
                c.execute("UPDATE users SET device_code = NULL WHERE id = ?", (int(m.group(1)),))
            self._audit(admin, "user.reset_device", m.group(1), "解除设备绑定")
            return self._json(200, {"ok": True})

        return self._err(404, "接口不存在")

    # ---------- 公开解析 ----------
    def _public_link(self, code, q):
        """短码 → 查库 → 记录一次访问 → 返回落地页所需的最小数据集。
        停用 / 过期的入口与不存在的入口统一返回 404，避免暴露入口是否存在。"""
        with db() as c:
            row = c.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
            expired = row and row["expires_at"] and row["expires_at"] < utcnow()
            if not row or row["enabled"] == 0 or expired:
                raise HTTPError(404, "链接不存在或已失效")
            utm = normalize_utm(q)
            query = "&".join(f"{k}={v}" for k, v in utm.items())[:300]
            c.execute(
                "INSERT INTO click_events(code,referer,ua,ip,query,utm,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (code, (self.headers.get("Referer") or "")[:300],
                 (self.headers.get("User-Agent") or "")[:300],
                 self._client_ip(), query, query, utcnow()),
            )
            c.execute("UPDATE links SET clicks=clicks+1, last_click_at=? WHERE code=?",
                      (utcnow(), code))
            row = c.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()

        data = link_dict(row, include_owner=False)
        data["url"] = f"{self._base_url()}/r/{row['code']}"
        data["autoForwardSeconds"] = AUTO_FORWARD_SECONDS
        data["forceLaunchMs"] = FORCE_LAUNCH_MS
        data["utmParams"] = utm
        # 原站语义：队列 = Set([targetId, ...gids]) 去重；randomOrder 时整条队列
        # 一起洗牌（含第 1 个 ID，所以每次 item_id 也可能变化），不是只洗后续队列
        raw_ids = ([row["target_id"]] + json.loads(row["gids"] or "[]")
                   if row["kind"] in ("id", "video") else [])
        ids = list(dict.fromkeys(x for x in raw_ids if x))
        if row["random_order"] and len(ids) > 1:
            random.SystemRandom().shuffle(ids)
        data["displayIds"] = ids
        # 垫底 ID 只进深链 gids、固定垫在最后一位（洗牌只作用于真实队列），
        # 用来吸收抖音对 gids 最后一项的回落行为；不进展示列表、不与用户 ID 重复
        pad = ""
        if GID_PAD and row["kind"] == "video" and DEEP_LINKS and ids:
            pad = next((x for x in GID_PAD_IDS if x not in ids), "")
        data["deepLink"] = build_deep_link(row, ids + [pad] if pad else ids)
        return self._json(200, data)

    # ---------- 点击明细报表 ----------
    @staticmethod
    def _csv_safe(value):
        text = str(value or "")
        return "'" + text if text[:1] in ("=", "+", "-", "@") else text

    def _clicks_report(self, as_csv: bool, q: dict):
        self._require(admin=True)
        code = (q.get("code") or [""])[0].strip()[:32]
        day_from = (q.get("from") or [""])[0].strip()[:10]
        day_to = (q.get("to") or [""])[0].strip()[:10]
        where, args = [], []
        if code:
            where.append("code = ?")
            args.append(code)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_from):
            where.append("substr(created_at,1,10) >= ?")
            args.append(day_from)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_to):
            where.append("substr(created_at,1,10) <= ?")
            args.append(day_to)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with db() as c:
            total = c.execute("SELECT COUNT(*) FROM click_events" + clause, args).fetchone()[0]
            rows = c.execute(
                "SELECT id,code,referer,ua,ip,query,utm,created_at FROM click_events"
                + clause + " ORDER BY id DESC LIMIT 1000", args).fetchall()
            by_day = [dict(r) for r in c.execute(
                "SELECT substr(created_at,1,10) AS day, COUNT(*) AS n FROM click_events"
                + clause + " GROUP BY day ORDER BY day", args)]
            by_referer = [dict(r) for r in c.execute(
                "SELECT CASE WHEN referer='' THEN '(直接访问)' ELSE referer END AS referer,"
                " COUNT(*) AS n FROM click_events" + clause
                + " GROUP BY referer ORDER BY n DESC LIMIT 10", args)]
            utm_clause = clause + (" AND " if where else " WHERE ") + "utm <> ''"
            by_utm = [dict(r) for r in c.execute(
                "SELECT utm, COUNT(*) AS n FROM click_events" + utm_clause
                + " GROUP BY utm ORDER BY n DESC LIMIT 10", args)]
        items = [{
            "id": r["id"], "code": r["code"], "referer": r["referer"],
            "ua": r["ua"], "ip": r["ip"], "utm": r["utm"],
            "createdAt": r["created_at"],
        } for r in rows]
        if as_csv:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["时间", "短码", "来源", "渠道参数", "UA", "IP"])
            for it in items:
                w.writerow([it["createdAt"], it["code"], self._csv_safe(it["referer"]),
                            self._csv_safe(it["utm"]), self._csv_safe(it["ua"]), it["ip"]])
            payload = ("\ufeff" + buf.getvalue()).encode("utf-8")
            return self._send(200, payload, "text/csv; charset=utf-8",
                              extra={"Content-Disposition":
                                     'attachment; filename="linklab-clicks.csv"'})
        return self._json(200, {
            "total": total, "byDay": by_day, "byReferer": by_referer,
            "byUtm": by_utm, "items": items,
            "filters": {"code": code, "from": day_from, "to": day_to},
        })

    # ---------- 业务实现 ----------
    def _login(self, body):
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        device = str(body.get("deviceCode") or "").strip()
        if not username or not password:
            raise HTTPError(400, "请输入用户名和密码")

        # 登录限流：按来源 IP + 用户名的滑动窗口计失败次数
        ip = self._client_ip()
        key = (ip, username.lower()[:64])
        if _rate_blocked(key):
            raise HTTPError(429, "尝试过于频繁，请稍后再试")

        # 读账号用独立短事务：随后的校验不持有读锁，失败审计才能立刻写库
        # （否则 audit 连接的写事务会等读事务结束，直到 busy_timeout 超时）。
        with db() as c:
            row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        # 无论账号是否存在都做一次 PBKDF2，避免通过响应时间枚举账号
        ok = verify_password(password,
                             row["salt"] if row else DUMMY_SALT,
                             row["password_hash"] if row else DUMMY_HASH)
        if not row or not ok:
            # 用户名不存在与密码错误返回同一句话
            _rate_fail(key)
            self._audit({"id": row["id"] if row else None, "username": username},
                        "login.fail", username, "密码错误或账号不存在", ok=False)
            raise HTTPError(401, "用户名或密码错误")
        if row["enabled"] == 0:
            self._audit({"id": row["id"], "username": row["username"]},
                        "login.fail", username, "账号已禁用", ok=False)
            raise HTTPError(403, "账号已被禁用，请联系管理员")
        if row["expires_at"] and row["expires_at"] < utcnow():
            self._audit({"id": row["id"], "username": row["username"]},
                        "login.fail", username, "账号已过期", ok=False)
            raise HTTPError(403, "账号已过期")
        if STRICT_DEVICE_BINDING and row["device_code"] and row["device_code"] != device:
            raise HTTPError(409, "该账号已绑定其他设备，请让管理员解绑（设备码机制演示）")

        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_hex(20)
        with db() as c:
            if not row["device_code"] and device:
                c.execute("UPDATE users SET device_code = ? WHERE id = ?", (device, row["id"]))
            # 顺手回收过期会话，避免 sessions 表无限增长
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (utcnow(),))
            c.execute(
                "INSERT INTO sessions(sid,user_id,csrf,expires_at,created_at) VALUES(?,?,?,?,?)",
                (sid, row["id"], csrf, utcplus(SESSION_DAYS), utcnow()),
            )
        _rate_clear(key)
        self._audit({"id": row["id"], "username": row["username"]}, "login", row["username"])
        cookie = f"linklab_sid={sid}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
        if SECURE_COOKIE:
            cookie += "; Secure"
        payload = json.dumps({"ok": True, "role": row["role"], "csrf": csrf},
                             ensure_ascii=False).encode()
        self._send(200, payload, "application/json; charset=utf-8", cookie)

    def _normalize_link(self, body, current=None) -> dict:
        """按「目标类型」归一化，六种类型对应六种落地行为：

        id    —— ID 队列：只展示配置，不做任何跳转
        url   —— 自有网页地址：可见倒计时自动跳转（可取消、有手动按钮兜底）
        app   —— 自有/已授权的应用链接：必须命中服务端白名单，用户点击才唤起
        room  —— 房间 ID：只展示配置
        video —— ID 队列 + 第三方 App 深链（原站模式：gids 控制上滑队列）
        live  —— 房间 ID + 直播深链（原站模式：短延时拉起）
        """
        kind = str(body.get("kind") or "id")
        # 兼容旧调用：没给 kind 但给了 live 的，按房间处理
        if kind == "id" and not body.get("target") and body.get("live"):
            kind = "room"
        if kind not in ("id", "url", "app", "room", "video", "live"):
            kind = "id"
        name = str(body.get("name") or "").strip()[:80] or "未命名入口"
        platform = str(body.get("platform") or "web")
        # platform=lite 切换极速版协议前缀；douyin 使用主版前缀
        if platform not in ("web", "h5", "mini", "douyin", "lite"):
            platform = "web"

        target_id = room_id = target_url = ""
        gids = []

        if kind == "url":
            target_url = str(body.get("targetUrl") or "").strip()[:2048]
            if not re.match(r"^https?://[^\s<>\"']+$", target_url):
                raise HTTPError(400, "网页目标必须是完整的 http(s) 地址")
        elif kind == "app":
            target_url = str(body.get("appLink") or body.get("targetUrl") or "").strip()[:2048]
            if not APP_LINK_ALLOWLIST:
                raise HTTPError(400, "服务器未配置应用链接白名单"
                                     "（LINKLAB_APP_LINK_ALLOWLIST），已禁用该类型")
            if not any(target_url.startswith(p) for p in APP_LINK_ALLOWLIST):
                raise HTTPError(400, "该应用链接不在白名单内，"
                                     "请先在服务端配置 LINKLAB_APP_LINK_ALLOWLIST")
        elif kind in ("room", "live"):
            live = str(body.get("live") or body.get("target") or "").strip()
            if not live:
                raise HTTPError(400, "请填写房间 ID")
            room_id = parse_target(live)
        else:
            target = parse_target(body.get("target"))
            if not target:
                raise HTTPError(400, "请填写目标 ID（可粘贴含数字的整段文案）")
            target_id = target
            followers = body.get("followers") or []
            if not isinstance(followers, list):
                raise HTTPError(400, "followers 应为数组")
            for f in followers[:50]:
                # 一行里也可能粘了整段文案，逐个解析并展开为 ID 队列
                for val in parse_targets(f):
                    if val and val not in gids and val != target_id:
                        gids.append(val)

        # 启用状态 / 有效期：编辑时未显式提供则保持原值，避免被全量覆盖
        if "enabled" in body:
            enabled = 1 if body.get("enabled") else 0
        elif current is not None:
            enabled = current["enabled"]
        else:
            enabled = 1
        if "expiresDays" in body:
            days = body.get("expiresDays")
            expires = utcplus(int(days)) if isinstance(days, int) and 0 < days < 3650 else None
        elif body.get("expiresAt") is None and "expiresAt" in body:
            expires = None
        elif current is not None:
            expires = current["expires_at"]
        else:
            expires = None

        return {
            "name": name, "platform": platform, "kind": kind,
            "target_id": target_id, "room_id": room_id, "target_url": target_url,
            "gids": json.dumps(gids, ensure_ascii=False),
            "random_order": 1 if body.get("randomOrder") else 0,
            "enabled": enabled, "expires_at": expires,
        }

    def _create_link(self, body, u):
        d = self._normalize_link(body)
        alias = str(body.get("alias") or "").strip()
        if alias and not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", alias):
            raise HTTPError(400, "自定义短码只能是 3-32 位字母、数字、下划线或短横线")
        if alias in ("r", "admin", "api", "static", "login", "healthz"):
            raise HTTPError(400, "该短码为系统保留字，请换一个")
        with db() as c:
            if alias:
                if c.execute("SELECT 1 FROM links WHERE code = ?", (alias,)).fetchone():
                    raise HTTPError(409, "该短码已被占用")
                code = alias
            else:
                for _ in range(8):  # 极小概率碰撞，重试即可
                    code = secrets.token_hex(6)  # 12 位十六进制，48 bit
                    if not c.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                        break
                else:
                    raise HTTPError(500, "短码生成失败")
            c.execute(
                "INSERT INTO links(code,name,platform,kind,target_id,room_id,target_url,"
                "gids,random_order,enabled,expires_at,owner_id,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, d["name"], d["platform"], d["kind"], d["target_id"], d["room_id"],
                 d["target_url"], d["gids"], d["random_order"], d["enabled"],
                 d["expires_at"], u["id"], utcnow()),
            )
        self._audit(u, "link.create", code, f"{d['name']} kind={d['kind']}")
        return self._json(201, {"code": code, "url": f"{self._base_url()}/r/{code}"})

    def _modify_link(self, code, method, body, u):
        with db() as c:
            row = c.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
            if not row:
                raise HTTPError(404, "链接不存在或已失效")
            # 数据归属校验：普通用户只能改自己的；管理员可以改全部
            if u["role"] != "admin" and row["owner_id"] != u["id"]:
                raise HTTPError(403, "无权操作他人的入口")
            if method == "DELETE":
                c.execute("DELETE FROM links WHERE code = ?", (code,))
                self._audit(u, "link.delete", code, row["name"], conn=c)
                return self._json(200, {"ok": True})
            if method == "PATCH":
                # 局部更新：只改启用状态 / 有效期，不动目标配置（停用可保留短码）
                fields, args = [], []
                if "enabled" in body:
                    fields.append("enabled = ?")
                    args.append(1 if body.get("enabled") else 0)
                if "expiresDays" in body:
                    days = body.get("expiresDays")
                    fields.append("expires_at = ?")
                    args.append(utcplus(int(days)) if isinstance(days, int)
                                and 0 < days < 3650 else None)
                if not fields:
                    raise HTTPError(400, "没有可更新的字段")
                c.execute("UPDATE links SET " + ", ".join(fields) + " WHERE code = ?",
                          args + [code])
                self._audit(u, "link.patch", code, ", ".join(fields), conn=c)
                return self._json(200, {"code": code, "url": f"{self._base_url()}/r/{code}"})
            d = self._normalize_link(body, current=row)
            # 注意：不更新 code / owner_id / created_at —— 所以「编辑后原链接保持不变」
            c.execute(
                "UPDATE links SET name=?,platform=?,kind=?,target_id=?,room_id=?,target_url=?,"
                "gids=?,random_order=?,enabled=?,expires_at=? WHERE code=?",
                (d["name"], d["platform"], d["kind"], d["target_id"], d["room_id"],
                 d["target_url"], d["gids"], d["random_order"], d["enabled"],
                 d["expires_at"], code),
            )
        self._audit(u, "link.update", code, f"{d['name']} kind={d['kind']}")
        return self._json(200, {"code": code, "url": f"{self._base_url()}/r/{code}"})

    def _create_user(self, body, admin=None):
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        role = body.get("role") if body.get("role") in ("user", "admin") else "user"
        days = body.get("days")
        expires = utcplus(int(days)) if isinstance(days, int) and 0 < days < 3650 else None
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username) or len(password) < MIN_PASSWORD_LENGTH:
            raise HTTPError(400, f"用户名需 3-32 位字母数字下划线，密码至少 {MIN_PASSWORD_LENGTH} 位")
        salt, digest = hash_password(password)
        with db() as c:
            if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise HTTPError(409, "用户名已存在")
            c.execute(
                "INSERT INTO users(username,salt,password_hash,role,expires_at,created_at) VALUES(?,?,?,?,?,?)",
                (username, salt, digest, role, expires, utcnow()),
            )
        self._audit(admin, "user.create", username, f"role={role}")
        return self._json(201, {"ok": True})


class Server(ThreadingHTTPServer):
    daemon_threads = True        # Ctrl+C 时不被残留连接卡住
    allow_reuse_address = True
    request_queue_size = 128


def main():
    if sys.version_info < (3, 10):
        print("[LinkLab] 需要 Python 3.10 或更高版本")
        raise SystemExit(1)
    init_db()
    base = PUBLIC_BASE_URL or f"http://{HOST}:{PORT}"
    print(f"[LinkLab] 监听 {HOST}:{PORT} ｜ 对外地址 {base}")
    print(f"[LinkLab] 数据库 {DB_FILE}")
    if not IS_LOCAL:
        print("[LinkLab][警告] 本服务不含 TLS，请勿直接暴露公网，务必前置 HTTPS 反向代理。")
        if not SECURE_COOKIE:
            print("[LinkLab][警告] LINKLAB_SECURE_COOKIE 未开启；会话 Cookie 缺少 Secure 标志，"
                  "请确认反代已强制 HTTPS 后开启该项。")
        if not PUBLIC_BASE_URL:
            print("[LinkLab][警告] 未设置 LINKLAB_PUBLIC_BASE_URL；短链域名将取请求 Host，"
                  "建议显式配置为 https://你的域名。")
    if DEV_MODE:
        print("[LinkLab][警告] DEV_MODE 已开启（含固定演示账号），生产环境必须关闭！")
    if DEEP_LINKS:
        print(f"[LinkLab] 第三方 App 深链已开启（主版 {SCHEME_MAIN} / 极速版 {SCHEME_LITE}，"
              f"拉起延时 {FORCE_LAUNCH_MS}ms）；设 LINKLAB_DEEP_LINKS=0 可回到纯展示模式")
    print("[LinkLab] 健康检查 GET /healthz ｜ 按 Ctrl+C 停止")
    srv = Server((HOST, PORT), Handler)
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n[LinkLab] 正在停止…")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
