FROM node:22-alpine AS console
WORKDIR /build
COPY apps/console/package*.json ./
RUN npm ci
COPY apps/console/ ./
RUN npm run build

FROM python:3.12-slim AS service
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src XFAGENT_ROOT=/app XF_HARNESS_VERSION=8
WORKDIR /app
COPY requirements-v2.lock ./
RUN pip install --no-cache-dir -r requirements-v2.lock && useradd --uid 10001 --create-home xfagent
COPY src/ ./src/
COPY scripts/service.py scripts/bootstrap_service.py ./scripts/
COPY --from=console /build/dist ./apps/console/dist/
RUN mkdir -p /app/runtime && chown -R xfagent:xfagent /app/runtime
USER xfagent
EXPOSE 8000
CMD ["python","scripts/service.py","serve","--host","0.0.0.0","--port","8000"]
