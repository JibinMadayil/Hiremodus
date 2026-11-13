# Builds the web UI, then runs the API + UI in one container on port 8000.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY connector/ ./connector/
COPY --from=web /web/dist ./frontend/dist
ENV HIREMODUS_DATABASE_URL=sqlite:////data/hiremodus.db \
    HIREMODUS_UPLOAD_DIR=/data/uploads \
    HIREMODUS_IMPORT_DIR=/data/imports
VOLUME ["/data"]
EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
