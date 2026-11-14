#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产模式黑盒验证：独立临时库 + 独立端口，不影响正在运行的服务与生产数据。

默认在 8792 端口起一个 DEV_MODE=0 的实例（深链关闭、UTM 关闭、品牌化、
Secure Cookie、应用白名单、PUBLIC_BASE_URL），逐项断言 36 个交付要点。

用法：python3 tests/production_check.py
     LINKLAB_PROD_TEST_PORT=9999 python3 tests/production_check.py
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("LINKLAB_PROD_TEST_PORT", "8792"))
BASE = f"http://127.0.0.1:{PORT}"
TMP = Path(tempfile.mkdtemp(prefix="linklab-prod-"))
DB = TMP / "linklab.db"
PW = "Pr0d-" + secrets.token_urlsafe(12)

env = os.environ.copy()
env.update({
    "LINKLAB_DB": str(DB), "LINKLAB_PORT": str(PORT), "LINKLAB_HOST": "127.0.0.1",
    "LINKLAB_DEV_MODE": "0", "LINKLAB_ADMIN_PASSWORD": PW, "LINKLAB_SECURE_COOKIE": "1",
    "LINKLAB_PUBLIC_BASE_URL": "https://link.example.com",
    "LINKLAB_APP_LINK_ALLOWLIST": "https://own-app.example.com/",
    "LINKLAB_DEEP_LINKS": "0", "LINKLAB_UTM_PASSTHROUGH": "0",
    "LINKLAB_FORCE_LAUNCH_MS": "0", "LINKLAB_BRAND_NAME": "客户品牌",
    "LINKLAB_BRAND_COLOR": "#ff6600", "LINKLAB_BRAND_NOTICE": "仅供内部活动使用",
    "LINKLAB_LOG_REQUESTS": "0", "PYTHONUNBUFFERED": "1",
})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(method, path, body=None, cookie=None, csrf=None, no_redirect=False):
    headers, data = {}, None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect) if no_redirect else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=5) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def js(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}


passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  PASS ", label)
    else:
        failed += 1
        print("  FAIL ", label, str(detail)[:160])


def main():
    print("\n[生产模式黑盒：深链关闭 + 品牌 + Secure Cookie + 白名单]")
    s, h, raw = call("GET", "/healthz")
    check("健康检查 /healthz", s == 200 and js(raw).get("ok") is True)
    check("安全头齐全（CSP / XFO / nosniff / no-store）",
          "Content-Security-Policy" in h and h.get("X-Frame-Options") == "DENY"
          and h.get("X-Content-Type-Options") == "nosniff" and h.get("Cache-Control") == "no-store")
    s, h, html = call("GET", "/")
    check("首页 200 且无演示凭据", s == 200 and "admin123" not in html and "student123" not in html)
    s, h, raw = call("GET", "/api/config")
    c = js(raw)
    check("生产模式无演示账号", c.get("devMode") is False and c.get("demoAccounts") == [])
    check("深链开关关闭 + 拉起延时 0", c.get("deepLinks") is False and c.get("forceLaunchMs") == 0)
    check("品牌配置下发（名称 / 颜色 / 公告）",
          c.get("brand", {}).get("name") == "客户品牌" and c.get("brand", {}).get("color") == "#ff6600"
          and c.get("brand", {}).get("notice") == "仅供内部活动使用")
    check("UTM 透传开关关闭", c.get("utmPassthrough") is False)
    s, h, raw = call("POST", "/api/login",
                     {"username": "admin", "password": "admin123", "deviceCode": "dev"})
    check("演示弱口令被拒 → 401", s == 401, raw)
    s, h, raw = call("POST", "/api/login",
                     {"username": "admin", "password": PW, "deviceCode": "dev"})
    d = js(raw)
    cookie = h.get("Set-Cookie", "")
    sid, csrf = cookie.split(";")[0], d.get("csrf", "")
    check("强口令管理员登录成功", s == 200 and d.get("role") == "admin", raw)
    check("Cookie 带 Secure / HttpOnly / SameSite=Lax",
          "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie, cookie)
    s, h, raw = call("GET", "/api/me", cookie=sid)
    check("会话可用", s == 200 and js(raw).get("role") == "admin", raw)
    s, h, raw = call("POST", "/api/links", {"name": "x", "target": "123456789012345"}, cookie=sid)
    check("写操作缺 CSRF → 403", s == 403)
    s, h, raw = call("POST", "/api/links", {"name": "生产入口", "target": "123456789012345"},
                     cookie=sid, csrf=csrf)
    d = js(raw)
    code = d.get("code", "")
    check("创建入口 201 且 12 位随机短码",
          s == 201 and bool(re.fullmatch(r"[0-9a-f]{12}", code or "")), raw)
    check("PUBLIC_BASE_URL 决定短链域名",
          d.get("url", "").startswith("https://link.example.com/r/"), d.get("url"))
    s, h, raw = call("GET", f"/api/public/links?code={code}")
    pub = js(raw)
    check("公开解析免登录且域名正确",
          s == 200 and pub.get("url", "").startswith("https://link.example.com/r/"))
    check("公开解析不泄漏 owner", "ownerId" not in pub and "ownerName" not in pub)
    s, h, raw = call("GET", f"/api/public/links?code={code}&utm_source=wechat")
    pub = js(raw)
    check("UTM 关闭后不透传渠道参数", pub.get("utmParams") == {}, pub.get("utmParams"))
    s, h, raw = call("POST", "/api/links",
                     {"name": "越权应用", "kind": "app", "appLink": "https://evil.example.com/open"},
                     cookie=sid, csrf=csrf)
    check("白名单外应用链接 → 400", s == 400)
    s, h, raw = call("POST", "/api/links",
                     {"name": "授权应用", "kind": "app",
                      "appLink": "https://own-app.example.com/open"}, cookie=sid, csrf=csrf)
    check("白名单内应用链接 → 201", s == 201, raw)
    s, h, raw = call("POST", "/api/links",
                     {"name": "深链退化", "kind": "video", "platform": "douyin",
                      "target": "7706212943633558491"}, cookie=sid, csrf=csrf)
    vcode = js(raw).get("code", "")
    check("深链关闭时 video 仍可建（退化为展示）", s == 201, raw)
    s, h, raw = call("GET", f"/api/public/links?code={vcode}")
    pub = js(raw)
    check("关闭后不生成任何第三方协议",
          pub.get("deepLink") == "" and "snssdk" not in raw, raw[:200])
    check("ID 队列完整展示",
          pub.get("displayIds") == ["7706212943633558491"], pub.get("displayIds"))
    s, h, raw = call("PATCH", f"/api/links/{vcode}", {"enabled": False}, cookie=sid, csrf=csrf)
    check("PATCH 停用 → 200", s == 200)
    s, h, raw = call("GET", f"/api/public/links?code={vcode}")
    check("停用后公开解析 → 404", s == 404)
    s, h, raw = call("PATCH", f"/api/links/{vcode}", {"enabled": True}, cookie=sid, csrf=csrf)
    check("PATCH 启用 → 200", s == 200)
    s, h, raw = call("GET", "/api/admin/clicks", cookie=sid, csrf=csrf)
    check("管理员可取点击报表", s == 200 and "byDay" in js(raw), raw)
    s, h, raw = call("GET", "/api/admin/clicks.csv", cookie=sid, csrf=csrf)
    check("CSV 导出带 attachment 头",
          s == 200 and "短码" in raw and "attachment" in h.get("Content-Disposition", ""),
          h.get("Content-Disposition"))
    s, h, raw = call("POST", "/api/users", {"username": "weakuser", "password": "123"},
                     cookie=sid, csrf=csrf)
    check("弱口令账号被拒 → 400", s == 400)
    s, h, raw = call("POST", "/api/users",
                     {"username": "normaluser", "password": "Normal@12345"},
                     cookie=sid, csrf=csrf)
    check("创建普通用户 → 201", s == 201)
    s, h, raw = call("POST", "/api/login",
                     {"username": "normaluser", "password": "Normal@12345", "deviceCode": "dev2"})
    ncookie = h.get("Set-Cookie", "").split(";")[0]
    check("普通用户登录成功", s == 200, raw)
    s, h, raw = call("GET", "/api/admin/clicks", cookie=ncookie)
    check("普通用户取报表 → 403", s == 403)
    s, h, raw = call("GET", "/admin", no_redirect=True)
    check("未登录访问 /admin → 302", s == 302)
    s, h, raw = call("GET", "/static/index.html")
    check("模板不可直接下载 → 404", s == 404)
    s, h, raw = call("GET", "/static/zip.js")
    check("静态脚本可访问 → 200", s == 200)
    s, h, raw = call("GET", f"/api/link?code={code}")
    check("/api/link 原站别名可用", s == 200 and js(raw).get("code") == code)
    s, h, raw = call("GET", f"/?r={code}")
    check("单页 ?r= 内嵌落地视图", s == 200 and 'id="landingView"' in raw)
    print(f"\n生产模式黑盒：{passed} 通过 / {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(BASE + "/healthz", timeout=1).close()
                break
            except Exception:
                time.sleep(0.25)
        else:
            print(proc.communicate()[0])
            raise SystemExit("服务未启动")
        rc = main()
    finally:
        proc.terminate()
        shutil.rmtree(TMP, ignore_errors=True)
    raise SystemExit(rc)
