FROM python:3.13-slim

WORKDIR /app

COPY requirements/web.txt /app/requirements/web.txt

RUN pip install --no-cache-dir -r /app/requirements/web.txt

COPY backend /app/backend
COPY frontend /app/frontend

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
