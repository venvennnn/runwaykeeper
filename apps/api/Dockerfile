FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/apps/api:/app/packages/forecasting:/app/packages/agent

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY packages/ /app/packages/
COPY apps/api/requirements.txt /app/apps/api/requirements.txt

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/apps/api/requirements.txt && \
    pip install --no-cache-dir -e /app/packages/forecasting && \
    pip install --no-cache-dir -e /app/packages/agent

COPY apps/api/ /app/apps/api/

WORKDIR /app/apps/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
