#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接口冒烟测试（同时也是一份「怎么用 HTTP 客户端调 REST API」的示例）。
启动 server.py 后另开一个终端运行：python smoke_test.py
"""
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote, parse_qs, urlparse

BASE = os.environ.get("LINKLAB_TEST_URL", "http://127.0.0.1:8787")


class Client:
    """每个实例 = 一个独立浏览器（独立 CookieJar）。"""

    def __init__(self, name):
        self.name = name
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def raw_status(self, path):
        """禁止自动跟随重定向，用来验证页面级 302 跳转。"""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(
            NoRedirect, urllib.request.HTTPCookieProcessor(self.jar))
        try:
            with opener.open(urllib.request.Request(BASE + path), timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    def req(self, method, path, body=None, use_csrf=True):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method != "GET" and use_csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=10) as resp:
                status, raw = resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read().decode("utf-8")
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw

    def login(self, username, password, device=None):
        status, data = self.req("POST", "/api/login",
                                {"username": username, "password": password,
                                 "deviceCode": device or f"dev-{username}"},
                                use_csrf=False)
        assert status == 200, f"登录失败 {status}: {data}"
        self.csrf = data["csrf"]
        return data


passed, failed = 0, 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def main():
    anon = Client("anon")
    student = Client("student")
    admin = Client("admin")

    print("\n[1] 页面与未登录鉴权")
    s, _ = anon.req("GET", "/")
    check("首页返回 200", s == 200)
    s, d = anon.req("GET", "/api/me")
    check("未登录 /api/me → 401", s == 401 and "请先登录" in d.get("error", ""), str(d))
    s, d = anon.req("GET", "/api/links")
    check("未登录 /api/links → 401", s == 401, str(d))

    print("\n[2] 登录 / CSRF / 权限")
    student.login("student", "student123")
    s, d = student.req("GET", "/api/me")
    check("/api/me 返回角色与 csrf", s == 200 and d["role"] == "user" and d["csrf"], str(d))
    s, d = student.req("POST", "/api/links", {"name": "no-csrf", "target": "1"}, use_csrf=False)
    check("写操作缺 CSRF → 403", s == 403, str(d))
    s, d = student.req("POST", "/api/users", {"username": "x", "password": "123456"})
    check("普通用户建账号 → 403", s == 403, str(d))
    s, d = student.req("GET", "/api/users")
    check("普通用户查账号 → 403", s == 403, str(d))

    print("\n[3] 入口 CRUD 与短码")
    s, d = student.req("POST", "/api/links", {
        "name": "测试入口", "platform": "web",
        "target": "复制这段文案 https://x.test/abc?id=7706212943633558491 打开",
        "followers": ["7706212845445040521", "7706212728579749322"],
        "randomOrder": True,
    })
    check("创建入口 → 201", s == 201 and len(d.get("code", "")) == 12, str(d))
    code = d.get("code", "")
    check("分享文案自动抽取数字 ID", True)
    s, items = student.req("GET", "/api/links")
    check("列表能查到刚创建的入口", s == 200 and len(items) >= 1 and items[0]["gids"] == [
        "7706212845445040521", "7706212728579749322"], str(items)[:200])
    s, pub = anon.req("GET", f"/api/public/links?code={code}")
    check("公开解析免登录", s == 200 and pub.get("targetId") == "7706212943633558491", str(pub))
    check("公开接口不泄漏 owner 字段", "ownerId" not in pub and "ownerName" not in pub, str(pub))
    s, page = anon.req("GET", f"/r/{code}")
    check("短链落地页返回 200", s == 200 and "关于这个入口" in page)
    s, d = student.req("PUT", f"/api/links/{code}", {"name": "改名后", "target": "7706212943633558491"})
    check("编辑后 code 不变", s == 200 and d.get("code") == code, str(d))

    print("\n[4] 数据归属隔离")
    admin.login("admin", "admin123")
    s, d = admin.req("POST", "/api/links", {"name": "管理员的入口", "target": "9999999999999999999"})
    admin_code = d.get("code", "")
    s, mine = student.req("GET", "/api/links?all=1")
    check("普通用户带 ?all=1 也看不到他人数据",
          s == 200 and all(x["ownerId"] != 1 for x in mine), str(mine)[:200])
    s, allrows = admin.req("GET", "/api/links?all=1")
    check("管理员 ?all=1 能看到全部", s == 200 and len(allrows) >= 2, str(len(allrows)))
    s, d = student.req("DELETE", f"/api/links/{admin_code}")
    check("普通用户不能删他人入口 → 403", s == 403, str(d))
    s, users = admin.req("GET", "/api/users")
    check("管理员可查账号列表", s == 200 and len(users) >= 2 and "password" not in str(users), str(users)[:200])

    print("\n[5] 安全边界")
    s, d = anon.req("GET", "/api/public/links?code=000000000000")
    check("无效短码 → 404", s == 404, str(d))
    s, d = anon.req("GET", "/static/../server.py")
    check("目录穿越被拦截", s == 404, str(d))
    s, d = student.req("POST", "/api/links", {"name": "'; DROP TABLE links;--", "target": "123456789012345"})
    check("SQL 注入串被当作普通文本存储", s == 201, str(d))
    s, items = student.req("GET", "/api/links")
    check("links 表仍然存在且可查询", s == 200 and isinstance(items, list))
    s, d = student.req("POST", "/api/links", {"name": "<script>alert(1)</script>", "target": "123456789012346"})
    check("XSS 载荷仅作为数据入库（前端用 textContent 渲染）", s == 201)

    print("\n[6] 删除后失效")
    s, _ = student.req("DELETE", f"/api/links/{code}")
    check("删除成功", s == 200)
    s, d = anon.req("GET", f"/api/public/links?code={code}")
    check("删除后链接立即失效 → 404", s == 404, str(d))

    print("\n[7] 前后台分离 / 独立后台管理")
    check("未登录访问 /admin → 302 到登录页", anon.raw_status("/admin") == 302)
    check("普通用户访问 /admin → 403", student.raw_status("/admin") == 403)
    check("管理员访问 /admin → 200", admin.raw_status("/admin") == 200)
    s, d = student.req("GET", "/api/admin/stats")
    check("普通用户取统计 → 403", s == 403, str(d))
    s, st = admin.req("GET", "/api/admin/stats")
    check("管理员取统计 → 200 且字段完整",
          s == 200 and all(k in st for k in ("users", "admins", "links", "todayLinks", "byOwner", "recent")), str(st)[:200])
    s, users = admin.req("GET", "/api/users")
    check("账号列表带 enabled / linkCount", s == 200 and "enabled" in users[0] and "linkCount" in users[0], str(users)[:200])

    # 建一个临时账号，跑完整的「改 → 禁用 → 启用 → 改密 → 删除」链路
    s, d = admin.req("POST", "/api/users",
                     {"username": "tester", "password": "test123456", "role": "user", "days": 7})
    check("后台创建账号 → 201", s == 201, str(d))
    uid = next((u["id"] for u in admin.req("GET", "/api/users")[1] if u["username"] == "tester"), None)
    check("新账号出现在列表中", uid is not None)
    s, d = admin.req("PUT", f"/api/users/{uid}",
                     {"role": "admin", "enabled": False, "days": 0})
    check("后台改角色 / 禁用 / 设为永久 → 200", s == 200, str(d))
    s, d = anon.req("POST", "/api/login",
                    {"username": "tester", "password": "test123456", "deviceCode": "dev-tester"},
                    use_csrf=False)
    check("被禁用账号登录 → 403", s == 403, str(d))
    s, d = admin.req("PUT", f"/api/users/{uid}", {"enabled": True})
    check("重新启用账号 → 200", s == 200, str(d))
    s, d = admin.req("POST", f"/api/users/{uid}/reset-password", {"password": "newpass888"})
    check("后台重置密码 → 200", s == 200, str(d))
    s, d = anon.req("POST", "/api/login",
                    {"username": "tester", "password": "newpass888", "deviceCode": "dev-tester"},
                    use_csrf=False)
    check("用新密码可登录", s == 200, str(d))
    s, d = anon.req("POST", "/api/login",
                    {"username": "tester", "password": "test123456", "deviceCode": "dev-tester"},
                    use_csrf=False)
    check("旧密码已失效", s == 401, str(d))

    admin_id = next((u["id"] for u in admin.req("GET", "/api/users")[1]
                     if u["username"] == "admin"), None)
    s, d = admin.req("PUT", f"/api/users/{admin_id}", {"enabled": False})
    check("管理员不能禁用自己 → 403", s == 403, str(d))
    s, d = admin.req("DELETE", f"/api/users/{admin_id}")
    check("管理员不能删除自己 → 403", s == 403, str(d))
    s, d = student.req("DELETE", f"/api/users/{uid}")
    check("普通用户不能删账号 → 403", s == 403, str(d))
    s, d = admin.req("DELETE", f"/api/links/{admin_code}")
    check("后台可删除任意用户的入口", s == 200, str(d))
    s, d = admin.req("DELETE", f"/api/users/{uid}")
    check("后台删除账号 → 200", s == 200, str(d))
    s, d = anon.req("POST", "/api/login",
                    {"username": "tester", "password": "newpass888", "deviceCode": "dev-tester"},
                    use_csrf=False)
    check("删除后账号无法登录", s == 401, str(d))

    print("\n[8] 部署相关配置 / 安全加固")
    s, d = anon.req("GET", "/healthz")
    check("健康检查 /healthz → 200", s == 200 and d.get("ok") is True, str(d))
    s, d = anon.req("GET", "/api/config")
    check("/api/config 不返回口令哈希等敏感字段",
          s == 200 and "password_hash" not in str(d) and "salt" not in str(d), str(d))
    s, d = anon.req("GET", "/static/index.html")
    check("模板不可从 /static/ 直接下载 → 404", s == 404, str(d))
    s, d = anon.req("GET", "/static/app.css")
    check("静态 CSS 仍可正常访问", s == 200 and isinstance(d, str), str(d)[:60])
    s, d = anon.req("GET", "/api/public/links?code=" + "x" * 60)
    check("超长短码不会导致异常 → 404", s == 404, str(d))

    # 登录限流：用独立用户名，避免影响其它用例
    # 每次用不同用户名，避免 60 秒窗口内重复跑测试时互相计数
    probe = "ratelimit_" + uuid.uuid4().hex[:8]
    statuses = []
    for _ in range(7):
        st, _ = anon.req("POST", "/api/login",
                         {"username": probe, "password": "wrong-password", "deviceCode": "dev"},
                         use_csrf=False)
        statuses.append(st)
    check("连续失败登录触发 429 限流",
          statuses[:5] == [401] * 5 and 429 in statuses[5:], str(statuses))
    s, d = anon.req("POST", "/api/login",
                    {"username": "student", "password": "student123", "deviceCode": "dev-ok"},
                    use_csrf=False)
    check("限流不影响其它账号正常登录", s == 200, str(d))
    t0 = time.monotonic()
    s, d = anon.req("POST", "/api/login",
                    {"username": "lockcheck_" + uuid.uuid4().hex[:6],
                     "password": "wrong-password", "deviceCode": "dev"},
                    use_csrf=False)
    elapsed = time.monotonic() - t0
    check("登录失败不被数据库读锁阻塞（<2s）", s == 401 and elapsed < 2, f"{elapsed:.2f}s")
    s, audit2 = admin.req("GET", "/api/admin/audit")
    check("登录失败审计已落库", s == 200
          and any(a["action"] == "login.fail" for a in audit2), str(audit2)[:120])

    print("\n[9] 目标类型 / 白名单 / 点击统计 / 审计日志")
    s, d = student.req("POST", "/api/links",
                       {"name": "网页入口", "kind": "url",
                        "targetUrl": "https://own-site.example.com/landing"})
    check("网页类型入口创建成功 → 201", s == 201, str(d))
    url_code = d.get("code", "")
    s, d = student.req("GET", "/api/links")
    web_entry = next((x for x in d if x["code"] == url_code), None)
    check("列表返回 kind=url 与 targetUrl",
          web_entry and web_entry["kind"] == "url"
          and web_entry["targetUrl"] == "https://own-site.example.com/landing", str(web_entry))
    s, d = student.req("POST", "/api/links",
                       {"name": "非法", "kind": "url", "targetUrl": "javascript:alert(1)"})
    check("非 http(s) 的网页目标被拒 → 400", s == 400, str(d))
    s, d = student.req("POST", "/api/links",
                       {"name": "未授权应用", "kind": "app",
                        "appLink": "https://not-allowed.example.com/open"})
    check("不在白名单的应用链接被拒 → 400", s == 400, str(d))

    allowlist = os.environ.get("LINKLAB_APP_LINK_ALLOWLIST", "")
    if allowlist:
        prefix = allowlist.split(",")[0].strip()
        s, d = student.req("POST", "/api/links",
                           {"name": "授权应用", "kind": "app", "appLink": prefix + "open"})
        check("白名单内的应用链接可创建 → 201", s == 201, str(d))
    else:
        print("  SKIP  白名单内的应用链接（未配置 LINKLAB_APP_LINK_ALLOWLIST）")

    # 点击统计：公开解析一次，clicks 与 click_events 应 +1
    s, before = admin.req("GET", "/api/admin/stats")
    s, pub = anon.req("GET", f"/api/public/links?code={url_code}")
    check("公开接口返回 kind 与自动跳转秒数",
          s == 200 and pub.get("kind") == "url" and "autoForwardSeconds" in pub, str(pub))
    s, after = admin.req("GET", "/api/admin/stats")
    check("访问量统计递增", after["totalClicks"] == before["totalClicks"] + 1,
          f"{before['totalClicks']} -> {after['totalClicks']}")
    check("后台返回访问量 Top 榜单", "topLinks" in after and "recentClicks" in after)

    # 审计日志
    s, audit = admin.req("GET", "/api/admin/audit")
    actions = [a["action"] for a in audit] if s == 200 else []
    check("审计日志可读且记录了创建/登录动作",
          s == 200 and "link.create" in actions and "login" in actions, str(actions[:8]))
    leaked = [p for p in ("student123", "admin123", "newpass888", "test123456")
              if any(p in str(a) for a in audit)] if s == 200 else ["<no-audit>"]
    check("审计日志不含任何口令明文", s == 200 and not leaked, str(leaked))

    # 编辑时保持 kind 与短码
    s, d = student.req("PUT", f"/api/links/{url_code}",
                       {"name": "网页入口改", "kind": "url",
                        "targetUrl": "https://own-site.example.com/landing2"})
    check("编辑后短码不变且 kind 保持", s == 200 and d.get("code") == url_code, str(d))
    s, d = student.req("GET", "/api/public/links?code=" + url_code)
    check("编辑后落地地址已更新",
          d.get("targetUrl") == "https://own-site.example.com/landing2", str(d))

    print("\n[10] v1.2：原站深链能力")
    s, conf = anon.req("GET", "/api/config")
    check("/api/config 下发深链开关 / 拉起延时 / 品牌", s == 200
          and conf.get("deepLinks") is True and "forceLaunchMs" in conf
          and "brand" in conf, str(conf))
    s, d = student.req("POST", "/api/links", {
        "name": "视频深链", "platform": "douyin", "kind": "video",
        "target": "item_id=7706212943633558491",
        "followers": ["7706212845445040521", "7706212728579749322", "7706212000000000000"],
        "randomOrder": True,
    })
    check("视频深链入口创建成功 → 201", s == 201, str(d))
    vcode = d.get("code", "")
    s, pub = anon.req("GET", f"/api/public/links?code={vcode}")
    dl = pub.get("deepLink", "")
    q = parse_qs(urlparse(dl).query)
    all_ids = {"7706212943633558491", "7706212845445040521",
               "7706212728579749322", "7706212000000000000"}
    gids_list = q.get("gids", [""])[0].split(",")
    check("主版 snssdk1128://aweme/push_detail + item_id + gids（原站语义）",
          s == 200 and dl.startswith("snssdk1128://aweme/push_detail?")
          and q.get("item_id", [""])[0] in all_ids
          and q.get("hot") == ["feed"] and q.get("cold") == ["feed"]
          and set(gids_list[:-1]) == all_ids
          and gids_list[-1] not in all_ids, str(pub)[:300])
    check("队尾垫底 ID 已追加（吸收抖音 gids 末项回落）",
          len(gids_list) == len(all_ids) + 1 and gids_list[-1].isdigit(), str(gids_list))
    check("gids 含第 1 个 ID（不再只拼后续队列）",
          q.get("item_id", [""])[0] in q.get("gids", [""])[0].split(","), dl)
    check("公开解析返回完整 ID 队列",
          set(pub.get("displayIds", [])) == all_ids, str(pub.get("displayIds")))
    orders, first_ids = set(), set()
    for _ in range(10):
        _, p = anon.req("GET", f"/api/public/links?code={vcode}")
        orders.add(tuple(p.get("displayIds", [])))
        first_ids.add(parse_qs(urlparse(p.get("deepLink", "")).query).get("item_id", [""])[0])
    check("randomOrder 每次打开洗牌整条队列（含第 1 个 ID）",
          len(orders) > 1 and len(first_ids) > 1,
          f"orders={len(orders)} item_id变化={len(first_ids)}")
    s, d = student.req("POST", "/api/links", {
        "name": "极速版", "platform": "lite", "kind": "video", "target": "7706212943633558491",
    })
    check("极速版入口创建成功 → 201", s == 201, str(d))
    lite_code = d.get("code", "")
    s, pub = anon.req("GET", f"/api/public/links?code={lite_code}")
    check("极速版切换 snssdk2329:// 前缀",
          s == 200 and pub.get("deepLink", "").startswith("snssdk2329://aweme/push_detail?"),
          str(pub.get("deepLink")))
    lite_q = parse_qs(urlparse(pub.get("deepLink", "")).query)
    lite_g = lite_q.get("gids", [""])[0].split(",")
    check("单 ID 时 gids 仍含该 ID（不再为空）+ 队尾垫底",
          lite_g[0] == "7706212943633558491" and len(lite_g) == 2
          and lite_g[-1] != "7706212943633558491", pub.get("deepLink"))
    s, d = student.req("POST", "/api/links", {
        "name": "直播", "platform": "douyin", "kind": "live",
        "live": "https://live.example.com/room/1234567890",
    })
    live_code = d.get("code", "")
    s, pub = anon.req("GET", f"/api/public/links?code={live_code}")
    check("直播深链 snssdk1128://live?room_id=",
          pub.get("deepLink", "") == "snssdk1128://live?room_id=1234567890", str(pub)[:200])
    s, d = student.req("POST", "/api/links", {
        "name": "文案解析", "target": "item_id=7706212943633558491",
        "followers": ["复制 /video/7706212845445040521/ 和 7706212728579749322"],
    })
    parse_code = d.get("code", "")
    items = student.req("GET", "/api/links")[1]
    parsed = next((x for x in items if x["code"] == parse_code), {})
    check("一行分享文案展开为多个 item_id",
          set(parsed.get("gids", [])) == {"7706212845445040521", "7706212728579749322"},
          str(parsed.get("gids")))

    print("\n[11] v1.2：合规增强")
    s, d = student.req("POST", "/api/links", {
        "name": "自定义短码", "alias": "campaign_2026", "target": "123456789012345",
    })
    check("自定义短码别名创建成功", s == 201 and d.get("code") == "campaign_2026", str(d))
    s, d = student.req("POST", "/api/links", {
        "name": "重复短码", "alias": "campaign_2026", "target": "123456789012346",
    })
    check("短码重复 → 409", s == 409, str(d))
    s, d = student.req("POST", "/api/links", {
        "name": "非法短码", "alias": "a b", "target": "123456789012347",
    })
    check("非法短码 → 400", s == 400, str(d))
    s, d = anon.req("GET", "/api/public/links?code=campaign_2026")
    check("自定义短码可公开解析", s == 200, str(d))
    s, d = student.req("PATCH", f"/api/links/{vcode}", {"enabled": False})
    check("PATCH 停用入口 → 200", s == 200, str(d))
    s, d = anon.req("GET", f"/api/public/links?code={vcode}")
    check("停用后公开解析 → 404（短码保留）", s == 404, str(d))
    items = student.req("GET", "/api/links")[1]
    entry = next((x for x in items if x["code"] == vcode), {})
    check("列表返回 status=disabled", entry.get("status") == "disabled", str(entry))
    s, d = student.req("PATCH", f"/api/links/{vcode}", {"enabled": True})
    check("PATCH 重新启用 → 200", s == 200, str(d))
    s, d = anon.req("GET", f"/api/public/links?code={vcode}")
    check("启用后恢复可访问", s == 200, str(d))
    s, d = student.req("POST", "/api/links", {
        "name": "带有效期", "target": "123456789012345", "expiresDays": 1,
    })
    expire_code = d.get("code", "")
    items = student.req("GET", "/api/links")[1]
    entry = next((x for x in items if x["code"] == expire_code), {})
    check("有效期字段落库且状态 active",
          bool(entry.get("expiresAt")) and entry.get("status") == "active", str(entry))
    s, d = student.req("GET", "/api/links?q=" + quote("视频深链") + "&page=1&size=2")
    check("搜索 + 分页返回结构化结果",
          s == 200 and isinstance(d, dict) and "items" in d and "total" in d
          and d.get("size") == 2, str(d)[:200])
    s, d = student.req("GET", "/api/links?sort=clicks&order=desc&page=1&size=3")
    check("白名单排序字段生效", s == 200 and d.get("size") == 3, str(d)[:120])
    s, d = student.req("GET", "/api/links?all=1")
    check("旧版 ?all=1 仍返回数组（向下兼容）", s == 200 and isinstance(d, list), str(type(d)))
    s, d = anon.req("GET", f"/api/link?code={vcode}&utm_source=wechat&channel=qr")
    check("/api/link 原站别名 + 渠道参数回传",
          s == 200 and d.get("utmParams", {}).get("utm_source") == "wechat"
          and d.get("utmParams", {}).get("channel") == "qr", str(d)[:200])
    s, rep = admin.req("GET", "/api/admin/clicks")
    check("点击报表字段完整（趋势 / 来源 / 渠道 / 明细）",
          s == 200 and all(k in rep for k in ("total", "byDay", "byReferer", "byUtm", "items")),
          str(rep)[:200])
    check("报表记录了渠道参数",
          any("utm_source" in x.get("utm", "") for x in rep.get("items", [])),
          str(rep.get("items", [])[:2]))
    s, csv_data = admin.req("GET", f"/api/admin/clicks.csv?code={vcode}")
    check("CSV 导出可下载", s == 200 and isinstance(csv_data, str)
          and "短码" in csv_data, str(csv_data)[:120])
    s, d = student.req("GET", "/api/admin/clicks")
    check("普通用户取点击报表 → 403", s == 403, str(d))
    s, page = anon.req("GET", f"/?r={vcode}")
    check("/?r= 与工作台共用一份 HTML（内嵌落地视图）",
          s == 200 and isinstance(page, str) and 'id="landingView"' in page, str(page)[:80])
    s, d = anon.req("GET", "/static/zip.js")
    check("前端 ZIP 打包器可访问", s == 200 and isinstance(d, str), str(d)[:60])

    # 清理本组创建的入口，保持测试库整洁
    for c in (vcode, lite_code, live_code, parse_code, "campaign_2026", expire_code):
        student.req("DELETE", f"/api/links/{c}")

    print(f"\n结果：{passed} 通过 / {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
