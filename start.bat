@echo off
chcp 65001 >nul
REM LinkLab 启动脚本（Windows）
REM 前置：Python 3.10+，零第三方依赖。
REM 步骤：复制 config.example.env 为 .env，按注释修改后双击本文件。
REM 生产部署：必须用 Nginx/Caddy 终止 HTTPS 并反向代理，不要把本端口直接暴露公网；
REM           同时设置 LINKLAB_PUBLIC_BASE_URL 与 LINKLAB_SECURE_COOKIE=1。
REM 健康检查：浏览器访问 http://127.0.0.1:8787/healthz
REM 数据备份：定期备份 linklab.db；删除该文件等于重置系统。
cd /d "%~dp0"

if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
)

if not defined LINKLAB_HOST set "LINKLAB_HOST=127.0.0.1"
if not defined LINKLAB_PORT set "LINKLAB_PORT=8787"

echo [LinkLab] 正在启动，按 Ctrl+C 停止...
python server.py
pause
