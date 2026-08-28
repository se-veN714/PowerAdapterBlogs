#!/bin/sh
set -eu

mode="${1:-web}"

case "$mode" in
  prepare)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    python manage.py init_mongo_audit
    python manage.py check_mongo_audit_deployment
    if [ "${IMPORT_MUSIC_RECORDS:-false}" = "true" ]; then
      python manage.py import_spotify_records
      python manage.py import_apple_music_records
    fi
    ;;
  web)
    exec gunicorn PowerAdapterBlogs.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-1}" \
      --timeout "${GUNICORN_TIMEOUT:-120}" \
      --access-logfile - \
      --error-logfile -
    ;;
  *)
    echo "unknown app mode: $mode" >&2
    exit 64
    ;;
esac
