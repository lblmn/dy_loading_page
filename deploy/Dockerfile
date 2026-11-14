# LinkLab 运行镜像：零第三方 Python 依赖，基础镜像只提供解释器。
# 构建：docker build -f deploy/Dockerfile -t linklab:1.2 .
FROM python:3.12-slim

WORKDIR /app
COPY server.py config.example.env ./
COPY static/ ./static/

ENV PYTHONUNBUFFERED=1 \
    LINKLAB_HOST=0.0.0.0 \
    LINKLAB_PORT=8787 \
    LINKLAB_DB=/data/linklab.db

VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=2)"

# 容器本身不含 TLS：请始终用 Nginx / Caddy 终止 HTTPS 后反代到 8787
CMD ["python3", "server.py"]
