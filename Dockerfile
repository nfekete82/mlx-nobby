FROM python:3.13-slim

WORKDIR /app

# Read-only extractor for legacy binary .doc files (not .docx).
RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword catdoc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/web.txt /app/requirements/web.txt

RUN pip install --no-cache-dir -r /app/requirements/web.txt

ARG MLX_NOBBY_BUILD_SHA=unknown

COPY VERSION /app/VERSION
COPY backend /app/backend
COPY frontend /app/frontend
COPY local_security.py /app/local_security.py
COPY service_identity.py /app/service_identity.py

# macOS checkout permissions can be 0600 after Git updates. The container
# runs as UID 10001, so make only immutable packaged app assets readable.
# This does not touch owner-only chat, profile or SQLite runtime volumes.
RUN chmod -R a+rX /app/backend /app/frontend \
    && chmod a+r /app/local_security.py /app/service_identity.py /app/VERSION

# Version the shared frontend bootstrap with the exact image revision so a
# rebuilt UI cannot keep using an older cached common.js in the browser.
RUN find /app/frontend -maxdepth 1 -name '*.html' -type f \
        -exec sed -i "s|/assets/common.js|/assets/common.js?v=${MLX_NOBBY_BUILD_SHA}|g" {} + \
    && printf '%s\n' "$MLX_NOBBY_BUILD_SHA" > /app/.mlx-nobby-build-revision

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/eml-data \
    && chown app:app /app/eml-data
USER app

CMD ["uvicorn", "backend.entrypoint:app", "--host", "0.0.0.0", "--port", "8000"]
