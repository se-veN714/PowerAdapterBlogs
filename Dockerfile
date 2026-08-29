FROM python:3.12-slim-bookworm

ARG DEBIAN_MIRROR_HOST=deb.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN sed -i "s|deb.debian.org|${DEBIAN_MIRROR_HOST}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --index-url "${PIP_INDEX_URL}" --upgrade pip \
    && python -m pip install --index-url "${PIP_INDEX_URL}" --requirement requirements.txt

COPY . .

RUN find deploy -type f -name '*.sh' -exec sed -i 's/\r$//' {} +

RUN groupadd --gid 10001 poweradapter \
    && useradd --uid 10001 --gid poweradapter --create-home poweradapter \
    && mkdir -p /app/common_static /app/media /app/media-private /app/logs \
    && chown -R poweradapter:poweradapter /app

USER poweradapter

EXPOSE 8000

CMD ["gunicorn", "PowerAdapterBlogs.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
