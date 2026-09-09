FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn python-multipart pypdf

COPY backend /app/backend
COPY frontend /app/frontend

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
