FROM python:3.13-slim

WORKDIR /app

COPY requirements/web.txt /app/requirements/web.txt

RUN pip install --no-cache-dir -r /app/requirements/web.txt

ARG MLX_NOBBY_BUILD_SHA=unknown

COPY backend /app/backend
COPY frontend /app/frontend
COPY local_security.py /app/local_security.py
COPY service_identity.py /app/service_identity.py

# Version the shared frontend bootstrap with the exact image revision so a
# rebuilt UI cannot keep using an older cached common.js in the browser.
RUN find /app/frontend -maxdepth 1 -name '*.html' -type f \
        -exec sed -i "s|/assets/common.js|/assets/common.js?v=${MLX_NOBBY_BUILD_SHA}|g" {} + \
    && printf '%s\n' "$MLX_NOBBY_BUILD_SHA" > /app/.mlx-nobby-build-revision

RUN useradd --create-home --uid 10001 app
USER app

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
