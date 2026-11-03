FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    QWEN_ENVIRONMENT=production \
    QWEN_COOKIE_SECURE=true

WORKDIR /app
ARG INSTALL_AI=false
COPY requirements.txt requirements-ai.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_AI" = "true" ]; then pip install --no-cache-dir -r requirements-ai.txt; fi \
    && groupadd --gid 10001 qwen \
    && useradd --uid 10001 --gid qwen --no-create-home --shell /usr/sbin/nologin qwen

COPY backend ./backend
COPY frontend ./frontend
COPY models ./models
RUN mkdir -p /app/data && chown -R qwen:qwen /app/data

USER 10001:10001
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
