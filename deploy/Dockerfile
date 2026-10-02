FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OTEL_SDK_DISABLED=true OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none
WORKDIR /app
RUN useradd --system --uid 10001 --home /app app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY alembic.ini .
COPY backend backend
COPY config config
COPY frontend frontend
RUN mkdir -p /app/data && chown app:app /app/data
USER app
ENV PREIS_DATA_DIR=/app/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
# Ein Worker-Prozess (SQLite, Hintergrundjobs im Prozess). Proxy-Header von nginx übernehmen.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
