# moot 运行时镜像（仅 Python 标准库）
FROM docker.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY moot/ /app/moot/

RUN mkdir -p /data
EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).status == 200 else 1)"]

ENTRYPOINT ["python", "-m", "moot.server", "--host", "0.0.0.0", "--port", "8080", "--store", "/data"]
