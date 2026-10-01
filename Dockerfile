FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
# OCR for shared payment screenshots.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/venv PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
# Throwaway key/dir so no secret gets baked into the image.
RUN SECRET_KEY=build DATA_DIR=/tmp/build python manage.py collectstatic --noinput

RUN useradd -m app && mkdir /data && chown app /data
USER app
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000
# createsuperuser --noinput reads DJANGO_SUPERUSER_USERNAME/PASSWORD; it fails harmlessly once the user exists.
CMD ["sh", "-c", "python manage.py migrate --noinput && (python manage.py createsuperuser --noinput 2>/dev/null || true) && exec gunicorn config.wsgi -b 0.0.0.0:8000 -w 2"]
