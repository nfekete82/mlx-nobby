FROM python:3.13-slim

WORKDIR /app

COPY requirements/web.txt /app/requirements/web.txt

RUN pip install --no-cache-dir -r /app/requirements/web.txt

ARG MLX_NOBBY_BUILD_SHA=unknown

COPY backend /app/backend
COPY frontend /app/frontend
COPY local_security.py /app/local_security.py
COPY service_identity.py /app/service_identity.py

RUN printf '%s\n' "$MLX_NOBBY_BUILD_SHA" > /app/.mlx-nobby-build-revision

RUN useradd --create-home --uid 10001 app
USER app

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
