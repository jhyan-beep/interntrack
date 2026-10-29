FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system interntrack \
    && adduser --system --ingroup interntrack --home /app interntrack

COPY --chown=interntrack:interntrack app ./app
COPY --chown=interntrack:interntrack alembic.ini ./
COPY --chown=interntrack:interntrack alembic ./alembic
COPY --chown=interntrack:interntrack --from=frontend-builder /frontend/dist ./frontend/dist

USER interntrack

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=2)"

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

