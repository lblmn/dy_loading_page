# LinkLab 交付进度说明

- **版本**：v1.3（v1.2 基础上新增分享短链自动解析、直播间真实房间号解析、深链队尾垫底、工作台表单精简）
- **日期**：2026-11-14
- **定位**：可独立部署的「短链 / 二维码管理后台」，零第三方 Python 依赖，Python 3.10+
- **本文件用途**：交付时说明**已实现什么、哪些功能没有实现、哪些不会实现**，避免需求理解偏差
- **v1.2 结论**：3.1 / 3.2 的原站能力已全部补齐（可用一个开关整体关闭）；3.3 的 11 项合规缺口完成 9 项，仅剩「多实例部署」与「密码找回邮件 / 密码复杂度与过期策略」。

## 1. 当前状态速览

| 模块 | 状态 | 备注 |
|---|---|---|
| 前台登录 + 工作台 | ✅ 完成 | 三栏深色工作台，新增深链类型、协议前缀、自定义短码、有效期输入 |
| 短链生成 / 二维码 / 批量创建 | ✅ 完成 | 单条、批量、房间、二维码弹窗与 PNG 下载，新增批量导出 ZIP |
| 短链落地页 | ✅ 完成 | 六种目标类型；ID 队列完整列出、随机顺序生效、深链短延时拉起 |
| 独立 `/admin` 管理后台 | ✅ 完成 | 前后台分离，服务端页面级鉴权；新增点击明细报表 |
| 账号 / 角色 / 有效期 / 设备绑定 | ✅ 完成 | 含防自锁保护 |
| 点击统计 / 审计日志 / 明细报表 | ✅ 完成 | 按天趋势、来源 / 渠道分布、按入口筛选、CSV 导出 |
| 安全加固 / 部署配置 | ✅ 完成 | 限流、CSRF、白名单、安全头、HTTPS 反代、Docker / systemd / 备份脚本 |
| 第三方私有协议注入 / 强制拉起 / 平台绕过 | ✅ 完成（v1.2） | 默认开启，`LINKLAB_DEEP_LINKS=0` 一键退回纯展示模式，见 2.8 |
| 原站语义对齐（双前缀 / 文案解析 / `?r=` / fetch 改写 / 接口别名） | ✅ 完成（v1.2） | 见 2.8、3.3 |
| 分享短链自动解析（视频 / 图文 / 直播分享文案） | ✅ 完成（v1.3） | 服务端跟随重定向取真实 ID，全部输入框生效，见 10.1 |
| 直播网页链接 → 真实 room_id | ✅ 完成（v1.3） | HEAD 读重定向 Location 的 19 位房间号，见 10.2 |
| 深链队尾垫底（解决最后一个视频随机播放） | ✅ 完成（v1.3） | gids 末尾追加错误 ID 占位，真机语义见 10.3 |
| 工作台表单精简（落地类型两选项 / 类型默认深链） | ✅ 完成（v1.3） | 见 10.4 |
| 合规增强（1~8、11） | ✅ 完成（v1.2） | 见 2.9；剩余 2 项见 3.2 |
| 自动化测试 | ✅ 完成 | 97 项接口回归 + 36 项生产模式黑盒 + 线上端到端 18 项（2026-11-11 阿里云，见第 8 节） |

---

## 2. 已实现功能

### 2.1 前台工作台（`/`）
- 单条创建（v1.3 精简）：名称、落地类型（抖音 / 抖音极速版）、ID 队列（第 1 个 + 第 2~5 个 + 多行更多）、完全随机开关；目标类型下拉已移除，新建固定为视频深链
- **落地类型** `douyin`（`snssdk1128` 抖音）与 `lite`（`snssdk2329` 抖音极速版）；旧的网页 H5 / 活动页 / 小程序选项已移除（编辑旧条目时自动归一化）
- **目标类型** `video`（ID 队列 → 视频深链）与 `live`（房间号 → 直播深链）；编辑旧 `id/url/app/room` 条目时保持原类型不被改写
- 所有 ID / 分享链接输入框支持直接粘贴分享文案，服务端自动解析真实 ID（见 10.1）
- **新增表单项**：自定义短码（3-32 位，编辑时锁定不可改）、有效天数（留空永久）
- 批量创建：名称前缀 + 每行一个目标，支持全部六种类型，逐条 POST，进度与成功/失败统计，一键复制本批链接
- 房间入口：独立 `room_id` 表单，v1.3 起固定为直播深链（旧的「仅展示房间配置」条目编辑时保持原类型），支持编辑与取消编辑；支持粘贴直播分享文案 / 直播网页链接自动解析真实 room_id（见 10.2）
- 结果区：短链输入框 + 复制按钮 + 164px 二维码；二维码弹窗 + 保存 PNG
- 入口管理：搜索、排序（创建时间 / 访问量 / 名称 / 最近访问）、服务端分页、全选、批量复制、**批量导出二维码 ZIP**、二维码、复制、编辑、**停用 / 启用**、删除；列表显示启用状态与有效期状态
- 编辑保持短码不变；删除后短链立即失效；管理员可在前台开启「显示所有人的作品」跨账号视图（前端改写 fetch，服务端仍按角色复核）

### 2.2 短链落地页（`/r/<code>` 与 `/?r=<code>`）
- 短码 → 查库 → 展示配置，公开免登录，只返回必要字段（不泄漏 owner）；停用 / 过期统一返回 404
- 六种目标类型 `kind`：

| 类型 | 落地行为 |
|---|---|
| `id` | ID 队列：**完整列出全部 ID**，不做跳转；`randomOrder` 每次打开重新洗牌 |
| `url` | 自有网页地址：可见倒计时自动跳转（默认 3 秒，可配 0 关闭），倒计时期间可取消，另有「立即打开」与「复制链接」；UTM / 渠道参数透传 |
| `app` | 自有 / 已授权应用：必须命中服务端白名单，且**必须用户主动点击**才唤起 |
| `room` | 房间 ID：仅展示配置 |
| `video` | 第三方 App 视频深链：第 1 个 ID 作 `item_id`，其余按（可随机）顺序拼 `gids`，**260ms 后自动拉起**，另有手动按钮 |
| `live` | 第三方 App 直播深链：`snssdk112[8|9]://live?room_id=...`，短延时自动拉起 |

- 内置浏览器（微信等 UA）拦截 App 深链时，自动拉起暂停并全屏提示「右上角 · 在浏览器中打开」
- `/?r=<code>` 与工作台**共用同一份 HTML**，靠参数切换隐藏；`/r/<code>` 保留独立轻量页，两种容器共用一份 `landing.js`
- 落地页品牌化：名称 / 本地 logo / 强调色 / 公告由服务端配置下发
- 每次访问写入点击统计（Referer、UA、IP、渠道参数、时间）

### 2.3 独立管理后台（`/admin`）
- 服务端页面级鉴权：未登录 302 到 `/login`，非管理员 403
- 概览卡片：账号总数、管理员数、短链数、今日新增、总访问、今日访问、已禁用、已过期
- 账号管理：列表 + 搜索、新建、编辑（角色 / 有效天数 / 启用状态）、重置密码（并清除该账号会话）、解绑设备、禁用 / 启用、删除
- 全局入口：所有人的短链，含**启用状态**与「停用 / 启用」按钮，支持搜索、查看、删除
- 入口分布条形图、访问量 Top、最近创建列表
- **点击明细报表**（v1.2）：按入口 / 起止日期筛选，按天趋势、来源 / 渠道分布、最近 1000 条明细、CSV 导出
- 审计日志表：登录成功/失败、入口增删改与停用/启用、账号增删改/改密/解绑

### 2.4 账号与权限
- 会话 Cookie（HttpOnly / SameSite=Lax，可选 Secure）+ 服务端 `sessions` 表
- 首次启动**不写弱口令**：随机生成管理员密码只打印一次，或用 `LINKLAB_ADMIN_PASSWORD` 指定
- `LINKLAB_DEV_MODE=1` 才会创建固定演示账号，生产默认关闭
- PBKDF2-HMAC-SHA256（20 万轮 + 独立盐 + 常数时间比较）
- RBAC（`user` / `admin`）+ 数据归属隔离；管理员不能删除 / 禁用 / 降级自己

### 2.5 安全与合规（v1.2 边界更新）
- 所有写操作（含新增 `PATCH`）校验 `X-CSRF-Token`
- 登录失败限流（按 IP + 用户名滑动窗口，超限 429）、账号枚举时序抹平
- 应用链接服务端白名单 `LINKLAB_APP_LINK_ALLOWLIST`，未登记直接 400；该类型始终需要用户点击
- **深链能力边界**：只由服务端按已保存的 ID / 房间号构造 URL，不破解、不注入第三方 App 进程、不获取平台数据；深链整体受 `LINKLAB_DEEP_LINKS` 开关控制，关闭后响应里不含任何第三方协议，`video/live` 自动退化为「仅展示配置」
- `PUBLIC_BASE_URL` + Host 头校验，防短链域名污染
- 安全响应头：CSP、nosniff、X-Frame-Options、Referrer-Policy、no-store；不暴露 Python 版本
- 静态目录禁止下载模板 / 配置类文件；SQLite 参数化查询、`busy_timeout`；socket 超时
- CSV 导出对 `= + - @` 开头的单元格做公式注入防护；ZIP 文件名清洗非法字符

### 2.6 部署与运维
- 全部参数通过 `LINKLAB_*` 环境变量注入，附 `config.example.env`（已含 v1.2 全部新参数）
- `start.sh` / `start.bat`、`nginx.example.conf`（HTTPS 反代示例）
- **新增** `deploy/Dockerfile`、`deploy/docker-compose.yml`、`deploy/linklab.service`、`deploy/backup.sh`（Python 标准库 `sqlite3.backup()` 在线备份，保留 14 天）
- `GET /healthz` 健康检查、可关闭的访问日志、启动时对不安全配置与深链模式打印告警
- `THIRD_PARTY_NOTICES.txt`：qrcodejs 的 MIT 许可全文（二维码库已本地化，不依赖 CDN）
- 幂等 schema 迁移：老库启动时自动补齐 `enabled` / `kind` / `target_url` / `clicks` / `last_click_at` / `expires_at`，以及 `click_events.query` / `utm`

### 2.7 接口清单（摘要）
| 接口 | 说明 |
|---|---|
| `POST /api/login`、`POST /api/logout`、`GET /api/me` | 会话 |
| `GET/POST /api/links`、`PUT/PATCH/DELETE /api/links/:code` | 入口 CRUD；`PATCH` 只改启用状态 / 有效期 |
| `GET /api/links?q=&sort=&order=&page=&size=` | 搜索 / 排序 / 分页；**不带分页参数时仍返回数组**（向下兼容），`?all=1` 仅管理员 |
| `GET /api/public/links?code=`、`GET /api/link?code=` | 公开解析（免登录，记录一次访问），后者为原站风格别名 |
| `GET /api/users`、`POST /api/users`、`PUT/DELETE /api/users/:id` | 账号管理 |
| `POST /api/users/:id/reset-password`、`/reset-device` | 改密 / 解绑 |
| `GET /api/admin/stats`、`GET /api/admin/audit` | 统计 / 审计 |
| `GET /api/admin/clicks[?code=&from=&to=]`、`GET /api/admin/clicks.csv` | **点击报表 / CSV 导出**（仅管理员） |
| `GET /api/config`、`GET /healthz` | 运行配置（含深链开关、拉起延时、UTM、品牌）/ 探活 |

### 2.8 原站能力（v1.2 新增：逐条对应旧 3.1 / 3.2）
| 原站能力 | 本项目实现 |
|---|---|
| 第三方 App 私有协议注入 | 服务端生成 `snssdk1128://aweme/push_detail?item_id=..&hot=feed&cold=feed&gids=..` |
| 控制用户上滑后依次出现什么 | `gids` = **整条 ID 队列（含第 1 个 ID）**，对应原站 `ids.join(',')`；`randomOrder` 每次打开整条队列重新洗牌后再拼；v1.3 起深链末尾追加垫底 ID（见 10.3） |
| 拉起方式 | 原站只靠**按钮点击（用户手势）**：`launch.onclick = () => location.href = target`。本项目以按钮为主，`LINKLAB_FORCE_LAUNCH_MS`（默认 260ms）仅作一次尽力而为的自动尝试，被浏览器拦截后提示点按钮 |
| 平台拦截规避 | 检测 `micromessenger` UA 显示「请在浏览器中打开」蒙层，暂停自动拉起 |
| 抖音 / 极速版双协议前缀 | 与原站一致：`lite` → `snssdk2329://`，其余 → `snssdk1128://` |
| 直播深链拉起 | `snssdk1128://live?room_id=...`（`lite` 用 2329 前缀） |
| 随机顺序实际生效 | 服务端对 `Set([targetId, ...gids])` 去重后用 `SystemRandom.shuffle` 洗**整条队列**（含第 1 个 ID），同步影响 `item_id`、展示列表与 `gids` |
| 分享文案解析成 `item_id` | 识别 `item_id=` / `/video/<id>` / `/share/video/<id>` / 8~20 位数字，一行文案可展开多个 ID 入队 |
| 工作台与落地页共用一份 HTML | `/?r=<code>` 在 `index.html` 内切换落地视图；`/r/<code>` 保留独立页 |
| 管理员「看其他人作品」靠前端改写 fetch | `app.js` 的 `api()` 在跨账号视图下自动追加 `?all=1`；服务端仍复核角色 |
| 设备码强制绑定 | `LINKLAB_STRICT_DEVICE_BINDING` 开关（强度说明见 3.4） |
| `/api/link?code=` 公开解析 | 已加兼容别名，与 `/api/public/links` 行为一致 |

### 2.9 合规增强（v1.2 新增：逐条对应旧 3.3）
| # | 缺口 | 状态 | 实现 |
|---|---|---|---|
| 1 | 落地页 ID 队列信息不完整 | ✅ | 完整列出全部 ID 并标注是否随机洗牌 |
| 2 | 点击明细报表 | ✅ | `/api/admin/clicks` + `.csv`，按天趋势 / 来源 / 渠道 / 按入口与日期筛选 |
| 3 | 入口搜索 / 排序 / 分页 | ✅ | 服务端 SQL 白名单排序 + `LIMIT/OFFSET`，默认每页 10 条 |
| 4 | 短链有效期 / 停用开关 | ✅ | `links.enabled` / `expires_at` + `PATCH`，停用后 404 但短码保留 |
| 5 | 二维码批量导出 ZIP | ✅ | `static/zip.js` 纯 JS store 模式 ZIP（UTF-8 文件名 + CRC32），零第三方依赖 |
| 6 | UTM / 渠道参数透传 | ✅ | 白名单参数透传到自有网页目标并记入点击报表，可整体关闭 |
| 7 | 落地页品牌化 | ✅ | `LINKLAB_BRAND_NAME/LOGO/COLOR/NOTICE` |
| 8 | 自定义短码别名 | ✅ | 3-32 位自定义 `alias`，冲突 409、保留字与非法字符 400 |
| 9 | 多实例部署 | ⬜ | 未做，见 3.2 |
| 10 | 密码找回邮件 / 密码复杂度与过期策略 | ⬜ | 未做，见 3.2 |
| 11 | Docker / Compose、systemd unit、自动备份脚本 | ✅ | `deploy/` 下四个文件 |

---

## 3. 未实现功能（重点）

### 3.1 原「明确不做、也不会补」清单 → v1.2 已补齐
旧版列出的七项原站能力已按需求全部实现（见 2.8），不再列为「不做」。交付时须说明两点边界：

1. 本项目只**按已保存的数据构造 URL**，不破解、不注入第三方 App 进程、不抓取平台数据；私有协议是否被目标 App 接受取决于对方客户端。
2. 深链能力默认开启（与原站一致）。若客户要求纯合规模式，设 `LINKLAB_DEEP_LINKS=0`：服务端不再生成任何第三方协议，`video/live` 退化为仅展示配置，前端隐藏深链选项（生产模式黑盒已验证）。

### 3.2 剩余缺口（可补、优先级低）
| # | 缺口 | 说明 | 优先级 |
|---|---|---|---|
| 9 | 多实例部署 | 单机 SQLite + 内存限流；多副本需换 Redis + PostgreSQL 并改造数据层 | 低 |
| 10 | 密码找回邮件 / 密码复杂度与过期策略 | 目前仅长度 ≥8，找回靠管理员在后台重置；加 SMTP 与口令策略属于独立需求 | 低 |

### 3.3 与原站语义差异（不是缺失，交付时须说明）
| 原站 | 本项目 |
|---|---|
| `douyin` / `lite` 切换协议前缀 | 已实现且与原站一致：`lite` → `snssdk2329`，其余（含 `web/h5/mini`）→ `snssdk1128`；是否生成协议由 `kind` 与 `LINKLAB_DEEP_LINKS` 决定 |
| 分享文案解析成 `item_id` | 已实现并增强（一行多 ID）；**纯短链 `v.douyin.com/xxx` 不含 item_id，无法离线解析**，按原文保存 |
| 工作台与落地页共用一份 HTML，靠 `?r=` 切换 | `/?r=` 已实现；同时保留 `/r/<code>` 独立轻量页（更利于二维码扫码与 CDN 缓存） |
| 管理员看其他人作品靠前端改写 fetch | 已实现；但权限判定仍在服务端，前端改写不是安全边界 |
| 设备码强制绑定（强度未验证） | `LINKLAB_STRICT_DEVICE_BINDING` 已实现；设备码由浏览器自报，**仅演示级约束，不是密码学强绑定** |
| `/api/link?code=` 公开解析 | 已实现别名，旧接口 `/api/public/links` 保留 |

### 3.4 已知行为限制
- 拉起依赖用户设备安装对应 App；桌面浏览器 / 未安装时会无反应或弹出系统提示，页面始终保留手动按钮与复制链接
- **移动端浏览器会静默拦截无用户手势的自定义协议跳转**：自动拉起仅作一次尝试，1.2s 后页面仍可见就提示点按钮；点按钮（用户手势）才是可靠路径，与原站一致
- 微信等内置浏览器会拦截自定义协议：已给出蒙层提示，但无法在内置浏览器内绕过
- `LINKLAB_FORCE_LAUNCH_MS=0` 可完全退回原站式「只给手动按钮」；自动尝试保留「取消自动尝试」兜底
- `gids` 控制上滑队列属于第三方 App 的私有参数行为，**未在真机验证**（见第 4 节）；参数拼法已与原站逐字对齐
- 短链公开解析接口仍未做独立限流（短码 48 bit 不可枚举，但高并发下建议补）

---

## 4. 验证结果（v1.2 打包基线）

| 项目 | 结果 |
|---|---|
| 开发模式接口回归（`LINKLAB_DEEP_LINKS=1`） | **96 / 96 通过**（`tests/smoke_test.py`，含 v1.2 新增的深链与合规增强用例） |
| 生产模式黑盒（`DEV_MODE=0`、`DEEP_LINKS=0`、`UTM=0`、品牌、白名单、Secure Cookie、`PUBLIC_BASE_URL`） | **36 / 36 通过**（`tests/production_check.py`，随机强口令、无演示账号、弱口令被拒、白名单、短链域名、深链退化、停用/启用、报表权限等） |
| 语法检查 | `server.py` + `smoke_test.py` + `static/` 全部 JS（含 qrcode.min.js）通过 |
| DOM id 一致性 | `app.js` 75 / `admin.js` 44 / `landing.js` 13 个引用零缺失；`index.html` 无重复 id |
| 前端静态自检（`node tests/frontend_check.js`） | **5 / 5 通过**（按 `index.html` 加载顺序合并编译、顶层声明重名、DOM id 一致性、重复 id） |
| 前端登录链路模拟（真实 HTTP + DOM/fetch mock） | 通过：启动发 `GET /api/config` + `GET /api/me`，点击登录发 `POST /api/login` → 200 → 拉取入口列表 |
| ZIP 打包器 | Node 加载 + Python `zipfile` 交叉验证：2 个 PNG 条目、CRC 全部正确、中文文件名 UTF-8 正常 |
| **修复：登录页「点了没反应」** | `landing.js` 与 `app.js` 都声明了全局 `const KIND_TEXT`，经典脚本共享全局词法作用域，导致 `app.js` **整段解析失败**（无 `/api/config`、`/api/me`、`POST /api/login`，登录按钮未绑定）。已把工作台常量改名 `ENTRY_KIND_TEXT`，并新增 `tests/frontend_check.js` 做合并编译防回归 |
| **顺带修复的既有缺陷** | 事务内另开连接写审计导致 SQLite 写锁等待（删除 / `PATCH` 固定慢 5 秒、登录失败审计丢失）。已改为复用当前连接 + 登录短读事务，并加「登录失败 <2s」「失败审计落库」两项回归断言 |
| 包内自检 | HTML 无硬编码凭据与预填 value；**v1.1 的「无 `snssdk` / 无 `micromessenger`」断言在 v1.2 不再适用**（默认开启深链，源码与响应含这些字符串）；`LINKLAB_DEEP_LINKS=0` 时响应不含任何第三方协议，已由生产模式黑盒验证 |

**已验证**：接口、权限、状态流转、协议字符串、报表 / CSV、开关关闭后的退化行为、ZIP 二进制产物。
**未验证 / 未做**：
- 真机（安装目标 App 的手机）自动拉起、微信内置浏览器蒙层在真实 UA 下、`gids` 上滑队列在目标 App 内的实际效果
- 浏览器端 CDP / Playwright 交互自动化（本机 Playwright 环境不可用，改用接口回归 + DOM 静态一致性 + ZIP 交叉验证）
- Docker / Compose 镜像实机运行、CSV 在 Excel/WPS 打开、ZIP 在真实浏览器下载（systemd / nginx HTTPS 反代 / `backup.sh` 已在阿里云实机验证，见第 8 节）
- 多实例、密码找回邮件

复跑方式：`LINKLAB_DEV_MODE=1 ./start.sh` 后另开终端跑 `python3 tests/smoke_test.py`；`python3 tests/production_check.py` 会自起一个独立端口 + 临时库的生产实例，跑完自动清理；`node tests/frontend_check.js` 检查前端脚本组合与 DOM 引用（改过任一 JS/HTML 后建议跑一次）。
`tests/smoke_test.py` 会写入并删除数据，**不要对生产数据库运行**；实测均使用 `/tmp` 下独立临时库。
本地开发需以 `LINKLAB_DEV_MODE=1` 启动，并按需设置 `LINKLAB_APP_LINK_ALLOWLIST`。

---

## 5. 部署步骤

1. 解压，`cp config.example.env .env`
2. 配置：`LINKLAB_ADMIN_PASSWORD`（16 位以上随机串）、`LINKLAB_PUBLIC_BASE_URL=https://客户域名`、`LINKLAB_SECURE_COOKIE=1`、确认 `LINKLAB_DEV_MODE=0`
3. 用 `nginx.example.conf` 配置 HTTPS 反代到 `127.0.0.1:8787`；**不要把服务端口直接暴露公网，服务本身不含 TLS**
4. `./start.sh`（Windows 用 `start.bat`）→ 访问 `/healthz` 探活 → 用初始密码登录 → 进 `/admin` 立即改密
5. 容器化：`docker compose -f deploy/docker-compose.yml up -d --build`；systemd：见 `deploy/linklab.service` 顶部注释；备份：`./deploy/backup.sh [备份目录]`（建议加 cron）

按需开关落地能力：

| 变量 | 默认 | 作用 |
|---|---|---|
| `LINKLAB_DEEP_LINKS` | `1` | `0` = 完全关闭第三方协议，回到纯展示模式 |
| `LINKLAB_FORCE_LAUNCH_MS` | `260` | 深链自动拉起延时；`0` = 只给手动按钮 |
| `LINKLAB_AUTO_FORWARD_SECONDS` | `3` | 自有网页倒计时跳转；`0` = 只显示手动按钮 |
| `LINKLAB_APP_LINK_ALLOWLIST` | 空 | 登记 Universal Link / App Link 前缀后才能用 `app` 类型 |
| `LINKLAB_UTM_PASSTHROUGH` | `1` | `0` = 不透传渠道参数 |
| `LINKLAB_BRAND_NAME/LOGO/COLOR/NOTICE` | 空 | 落地页品牌（LOGO 只接受 `/static/` 本地路径） |

---

## 6. 已知架构限制

- 登录限流是**单进程内存版**，多副本部署会失效，需换 Redis
- SQLite 单机，**只能单实例**；多实例需迁移到 PostgreSQL / MySQL 并改造数据层
- 短链公开解析接口未做独立限流（短码 48 bit，不可枚举，但高并发下建议补）
- 数据库 `linklab.db` 是唯一状态，删除即全丢，需客户自行定期备份（现附 `deploy/backup.sh`）
- 源码中保留 `admin123` / `student123` 字面量，但**仅在 `DEV_MODE` 分支**，生产不加载、页面不下发
- 设备码由浏览器自报，可伪造；`LINKLAB_STRICT_DEVICE_BINDING` 只作演示级约束
- `LINKLAB_DEEP_LINKS=1` 时源码与对外响应会包含 `snssdk` / `micromessenger` 字样，若客户做包内合规扫描需先关闭该开关并重新出包

---

## 7. 包内文件清单

```
linklab/
├── STATUS.md                  本文件：进度与未实现功能清单
├── server.py                  后端全部逻辑（零第三方依赖）
├── config.example.env         运行配置样例（含 v1.2 新增参数）
├── start.sh / start.bat       Linux / Windows 启动脚本
├── nginx.example.conf         HTTPS 反向代理示例
├── THIRD_PARTY_NOTICES.txt    qrcodejs MIT 许可
├── deploy/
│   ├── Dockerfile             零依赖运行镜像
│   ├── docker-compose.yml     数据卷持久化 + 仅监听回环
│   ├── linklab.service        systemd 常驻单元（含部署注释）
│   └── backup.sh              SQLite 在线备份（保留 14 天）
├── static/
│   ├── index.html / app.js    前台工作台 + ?r= 内嵌落地视图
│   ├── admin.html / admin.js  独立管理后台（含点击明细报表）
│   ├── landing.html / landing.js  短链落地页（独立页 / 单页视图共用脚本）
│   ├── zip.js                 零依赖 ZIP 打包器（二维码批量导出）
│   ├── app.css                全部样式
│   └── qrcode.min.js          本地化二维码库（MIT）
└── tests/
    ├── smoke_test.py           96 项接口回归测试（开发模式）
    ├── production_check.py     36 项生产模式黑盒验证（自起临时实例）
    └── frontend_check.js       前端脚本组合 / DOM 引用静态自检（Node）
```

---

## 8. 线上部署实录（2026-11-11，阿里云）

**结论**：已在 `root@aliyun`（`47.108.211.135`）以 systemd + nginx HTTPS 反代上线，公网入口 `https://linklab.sxkczx.com`，线上端到端验证 **18 / 18 通过**，自检数据已清理。

### 8.1 部署形态

| 项 | 值 |
|---|---|
| 域名 / 解析 | `linklab.sxkczx.com` → A 记录 `47.108.211.135`（TTL 600，阿里云 DNS 自动添加） |
| 证书 | 复用服务器既有通配符证书 `*.sxkczx.com`（`/etc/nginx/ssl/license.sxkczx.com.*`，有效至 2027-01-24） |
| 应用 | `/opt/linklab`，`server.py`，系统用户 `linklab`，监听 `127.0.0.1:8787`（不直接暴露公网） |
| 常驻 | `systemd` 单元 `linklab.service`，`Restart=always` + 开机自启；上线后 `active` / `NRestarts=0` |
| 反代 | `/etc/nginx/conf.d/linklab.conf`：80 → 301 HTTPS；443 → `127.0.0.1:8787`，透传 `X-Forwarded-Proto / Host / For` |
| 数据 | `/opt/linklab/data/linklab.db`，来自本地库 `sqlite3.backup()` 一致性快照（2 用户 / 0 入口），目录 700 |
| 登录 | 沿用本地库管理员账号 `operator`，口令与本地一致（**按保密要求不写入文档**） |
| 配置 | `/opt/linklab/.env`（600，`linklab:linklab`）：`DEV_MODE=0`、`SECURE_COOKIE=1`、`TRUST_PROXY=1`、`PUBLIC_BASE_URL=https://linklab.sxkczx.com` |
| 备份 | cron 每日 03:17 调 `deploy/backup.sh`，SQLite 在线备份、保留 14 天、文件 600；已实机演练产出并通过 `integrity_check` |

用户确认的三项选择：新子域 + 自动加 A 记录；**深链保持开启**（`DEEP_LINKS=1` / `FORCE_LAUNCH_MS=260` / `UTM_PASSTHROUGH=1`，公网可见第三方私有协议与自动拉起）；复制本地库、沿用现有帐密。部署脚本只新增服务与 nginx 站点，未改动服务器上既有的 hxkq / license / shxga / verify 站点，nginx 配置前后均通过 `nginx -t`（失败自动回滚新配置）。

### 8.2 线上端到端验证（18 / 18）

从本机直连公网 HTTPS，证书走系统信任链正常校验，覆盖：

| 分组 | 断言 |
|---|---|
| 链路与安全 | `/healthz` 200、CSP / `X-Frame-Options` / `nosniff` / `no-store` 齐全、HTTP 80 → 301、首页无演示凭据 |
| 配置与鉴权 | `devMode=false` / `deepLinks=true` / `secureCookie=true` / 无演示账号；登录 200、`/api/me` 管理员角色、`/admin` 页面 200、会话 Cookie `Secure; HttpOnly; SameSite=Lax` |
| 业务全链路 | 入口列表、创建网页入口 201、短链域名使用 `PUBLIC_BASE_URL`、匿名公开解析、创建视频深链入口、线上生成 `snssdk1128://aweme/push_detail?...`、强制拉起 260ms、点击明细报表含访问记录 |
| 数据清理 | 两个自检入口删除后库恢复原状（线上仍为 0 个入口） |

### 8.3 已验证 / 未验证

| 状态 | 项 |
|---|---|
| ✅ 已验证 | systemd 常驻与开机自启、nginx 反代与 HTTPS 证书、登录与权限、短链 / 深链 / 点击报表全链路、cron 在线备份实际产出、80→301、安全响应头、生产库一致性 |
| ⚠️ 未做 | Docker / Compose 实机运行、真机 App 自动拉起、真实浏览器 CDP / Playwright 交互、CSV 在 Excel/WPS 打开、ZIP 浏览器下载、多实例与密码找回 |

### 8.4 已知环境问题（本机 DNS 否定缓存）

新子域 A 记录已在阿里公共 DNS（`223.5.5.5` / `114.114.114.114`）与权威 DNS（`dns19.hichina.com`）生效，同域已有子域 `bike.sxkczx.com` 本机可正常解析；但**本机上游递归 DNS `10.0.1.1` 缓存了先前的否定应答**（根域 SOA 最小 TTL 600 秒），故本机浏览器可能暂时提示「找不到服务器」。等待约 10 分钟或刷新本机 DNS 即可；需立即访问可临时把 `47.108.211.135 linklab.sxkczx.com` 写入 `/etc/hosts`，或改用手机网络访问。线上验证在**保持域名 SNI 与系统证书校验不变**的前提下，用固定公网 IP 绕过该缓存完成。

### 8.5 运维速查

```bash
ssh root@aliyun
systemctl status linklab                 # 服务状态
journalctl -u linklab -f                  # 日志
systemctl restart linklab                 # 重启（内存版登录限流计数会清零）
nginx -t && systemctl reload nginx
/opt/linklab/deploy/backup.sh /opt/linklab/backups      # 手工备份
curl -fsS http://127.0.0.1:8787/healthz                  # 回环探活
```

---

## 9. 参考原站实测修正（2026-11-11）

抓取原站真实落地页 `https://768999.xyz/?r=9fc54e2c38bf`（HTTP 200，SSR 内嵌 `entry` + 内联脚本，无外部 JS），逐字比对后修正了三处语义偏差。这也是此前「打开抖音不是设置内容 / 不跳转」的根因。

### 9.1 原站关键实现（节选）

```js
const ids=[...new Set([entry.targetId,...(entry.gids||[])].filter(Boolean))];
if(entry.randomOrder){ /* Fisher-Yates 洗整条 ids */ }
target=`${scheme}://aweme/push_detail?item_id=${encodeURIComponent(ids[0]||'')}`
     +`&hot=feed&cold=feed&gids=${ids.join(',')}`;
document.querySelector('#launch').onclick=()=>location.href=target;
```

要点：`gids` 是**整条队列（含第 1 个 ID）**；随机洗**全部** ID；**只有按钮点击才拉起**，没有自动跳转。

### 9.2 差异与修正

| 项 | 原站 | 修正前 | 修正后 |
|---|---|---|---|
| `gids` | `ids.join(',')`，含第 1 个 ID | 只拼 `ids[1:]`；单 ID 时 `gids=` 为空 → 抖音回落首页/推荐 | 拼整条队列，单 ID 也非空 |
| 队列构造 | `new Set([...])` 去重 | 合并后未再去重 | `dict.fromkeys` 去重 |
| `randomOrder` | 洗全部 ID，第 1 个也会变 | 只洗后续队列，第 1 个固定 | 洗整条队列，`item_id` 每次可能变化 |
| 拉起时机 | 仅按钮点击（用户手势） | 260ms 定时器自动 `location.href`，按钮只是附带；移动端浏览器静默拦截 | 按钮为主（文案「打开目标视频」）；自动拉起仅作一次尝试，1.2s 后页面仍可见即提示点按钮 |
| 落地页 | 极简 SSR：标题 + 说明 + 一个大按钮 | 前端 fetch `/api/public/links` 后渲染 | 保留 fetch（点击报表 / 品牌化需要），但主操作与原站一致 |
| 协议前缀 / `live` | `lite`→2329，其余→1128；`live?room_id=` | 相同 | 不变（本就一致） |

### 9.3 验证结果

| 范围 | 结果 |
|---|---|
| 本地接口回归 | **96 / 96**（新增「gids 含第 1 个 ID」「单 ID 时 gids 非空」「洗全队列」断言） |
| 生产模式黑盒 | 36 / 36 |
| 前端静态自检 | 5 / 5 |
| 前端 DOM/fetch mock | 通过：按钮文案「打开目标视频」、按钮 href = deepLink、自动跳转已发起、1.7s 后兜底提示出现、无 JS 异常 |
| 线上端到端（发版后） | **17 / 17**：单 ID `gids` 非空、多 ID `gids` 恒为整条队列、`item_id` 随洗牌变化、前端资源已更新；自检入口 3×200 清理，库恢复 5 条基线 |
| 发版一致性 | `server.py` / `static/landing.js` 本地与线上 md5 一致；重启后 `systemd active`、`/healthz` 200 |

### 9.4 仍未真机验证

- 抖音客户端是否按 `gids` 展示上滑队列、图文笔记（`/share/note/`）能否被 `push_detail` 正确承接
- Android Chrome 是否放行 260ms 自动尝试、点按钮后是否弹出「打开抖音」
- 原站只有一个主按钮、无点击报表 / 品牌化；本项目保留这些能力，页面信息比原站多，属于有意差异

### 9.5 可选项

若要完全复刻原站「零自动拉起」，把 `.env` 的 `LINKLAB_FORCE_LAUNCH_MS` 改为 `0` 并 `systemctl restart linklab`，落地页即只剩手动按钮。当前按上线时确认的「保持开启 260ms」保留自动尝试。

发版：`server.py` / `static/` 同步到 `/opt/linklab/` → `chown -R linklab:linklab /opt/linklab` → `systemctl restart linklab`。**切勿覆盖 `/opt/linklab/data/linklab.db` 与 `/opt/linklab/.env`**。

---

## 10. v1.3 迭代实录（2026-11-13 ~ 11-14，均已部署上线）

### 10.1 分享短链自动解析（服务端）

浏览器 fetch 跟随抖音短链重定向会被 CORS 拦死，解析放在服务端做。`parse_target / parse_targets`
是**所有输入框**（第 1 个目标、第 2~5 个 ID、更多 ID、批量列表、直播间）的唯一入口，改一处全部生效：

- 输入是纯 ID / 含 `item_id=` / 含 `/video/<id>`：原正则直接命中，**不做任何转换**
- 输入是 `v.douyin.com/xxx` 短链或含短链的整段分享文案：服务端跟随重定向取最终 URL 提取真实 ID
- 最终 URL 落点全覆盖：`/share/(video|note)/<id>`、`live.douyin.com/<网页房间号>`（转 10.2）、
  `webcast.amemv.com/.../reflow/<19位room_id>`（按 19 位雪花号提取）；GET 失败退回 HEAD 跟随重定向
- 解析失败返回空串 → 接口报「请填写目标 ID」明确错误，**不会把整条 URL 当 ID 存库**
- 结果按短链缓存（成功才缓存，失败可重试）；`LINKLAB_RESOLVE_SHORT_LINKS=0` 可整体关闭，
  `LINKLAB_RESOLVE_TIMEOUT` 控制单次超时（默认 6s）
- 实测：`52vIIuZplSk`（图文 note）→ `7705424660876208817`；直播分享文案
  `v.douyin.com/EUcrrVJoZmQ` → `7707974000795454249`（与用户脚本输出一致）

### 10.2 直播网页链接 → 真实 room_id

`live.douyin.com/<网页房间号>` 是展示用短号，**不是**真实 room_id；旧版会被裸数字通道误抓存库。
新增 `resolve_live_room()`：HEAD 一次（不跟随重定向），从重定向 `Location`
（`webcast.amemv.com/douyin/webcast/reflow/<19位>`）提取真实 room_id；HEAD 被拒（405/403）退回 GET。
`parse_targets` 中直播链接路径里的网页房间号会在解析成功后从结果中剔除。

### 10.3 深链队尾垫底（最后一个视频随机播放）

- **真机现象**：`push_detail` 的 gids 只有用户 ID 时，末位位置回落推荐流（N 个只有前 N-1 个正常；
  后续真机复测又发现 gids 末项实际会被播放——垫一个真实视频时它固定播在最后）
- **最终方案**：深链 `gids` 末尾固定追加一个**不存在的错误 ID**（默认 `9999999999999999999`），
  抖音取不到内容，该位置自然回落推荐流 = 最后一个视频随机播放；客户的全部真实 ID 正常播
- 垫底只进深链 gids：不进落地页展示列表、不参与 randomOrder 洗牌、与用户 ID 冲突时跳过
- 开关：`LINKLAB_GID_PAD=1`（默认开）；`LINKLAB_GID_PAD_IDS` 可换垫底 ID 池
- ⚠️ 待真机确认的边界：若抖音对 gids 做整队列预校验，错误 ID 会导致整条队列变随机——
  真机复测若出现此现象，需改用「已删除作品」类无效但可查的 ID

### 10.4 工作台表单精简

- 落地类型三个下拉（主面板 / 批量 / 房间）统一只留**抖音**（`snssdk1128`）与**抖音极速版**（`snssdk2329`）；
  网页 H5 / 活动页 / 小程序选项移除（注意：按实际身份映射，用户原始描述中的箭头映射与 scheme 真实身份相反）
- 主面板「目标类型」下拉移除，新建固定 `kind=video`（视频深链）；落地页协议前缀文案同步改为
  「抖音 snssdk1128 / 抖音极速版 snssdk2329」
- 房间面板「房间入口行为」下拉移除，新建固定 `kind=live`（直播深链）
- 编辑兼容：旧 `id / url / app / room` 条目编辑时保持原类型提交，不被静默改写；
  旧 `web/h5/mini` 落地类型编辑时归一化为抖音。服务端接口与数据结构零改动

### 10.5 验证与部署

| 项 | 结果 |
|---|---|
| smoke_test 回归 | 97 通过 / 0 失败（v1.2 时为 96；新增垫底断言） |
| 短链/直播解析实测 | 本机 + 服务器出网双链路验证（52vIIuZplSk、55948918950、EUcrrVJoZmQ 均解出正确 ID） |
| 线上部署 | `root@aliyun:/opt/linklab`，systemd；本次共 5 次发版，每次先备份旧 `server.py` 到 `backups/` 再覆盖重启 |
| 线上核验 | 每次发版后 `systemctl is-active` + `/healthz` 200 + grep 新代码标记确认就位 |
| 未真机验证 | 10.3 垫底错误 ID 的实机表现（末位回落推荐流 vs 整队列变随机），待用户真机复测 |
