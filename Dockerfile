# ---- stage 1: build the React frontend ----
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: python runtime (serves API + built SPA; also runs the ingest job) ----
FROM python:3.12-slim
WORKDIR /app
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY seed/ ./seed/
COPY --from=frontend /fe/dist ./frontend/dist
RUN pip install --no-cache-dir ./backend
ENV PORT=8080
EXPOSE 8080
# Cloud Run service runs this; the ingest Job overrides command with scripts/ingest_entrypoint.sh
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
