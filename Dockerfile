FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement requirements.txt

COPY . .

RUN groupadd --gid 10001 poweradapter \
    && useradd --uid 10001 --gid poweradapter --create-home poweradapter \
    && mkdir -p /app/common_static /app/media /app/media-private /app/logs \
    && chown -R poweradapter:poweradapter /app

USER poweradapter

EXPOSE 8000

CMD ["gunicorn", "PowerAdapterBlogs.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
