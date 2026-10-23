# One image for both Python services: the WorkFlowOS API (default command) and the Demo CRM.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_FORMAT=json \
    DATABASE_PATH=/data/workflowos.db \
    CRM_DATABASE_PATH=/data/crm.db \
    WORKFLOWOS_SANDBOX_DIR=/data/sandbox \
    GMAIL_CREDENTIALS_PATH=/secrets/credentials.json \
    GMAIL_TOKEN_PATH=/secrets/token.json

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 workflowos \
    && mkdir -p /data /secrets \
    && chown -R workflowos /data /secrets
USER workflowos

EXPOSE 8000 8001

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(os.environ.get('HEALTH_URL', 'http://127.0.0.1:8000/health'), timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
