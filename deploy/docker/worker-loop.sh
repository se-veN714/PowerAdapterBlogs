#!/bin/sh
set -eu

worker="${1:?worker name is required}"
interval="${WORKER_INTERVAL_SECONDS:-5}"

while true; do
  case "$worker" in
    audit)
      python manage.py process_audit_outbox --limit "${AUDIT_WORKER_BATCH_SIZE:-100}"
      ;;
    skate)
      python manage.py process_skate_clips --limit "${SKATE_WORKER_BATCH_SIZE:-10}" --reset-stuck --json
      ;;
    *)
      echo "unknown worker: $worker" >&2
      exit 64
      ;;
  esac
  sleep "$interval"
done
