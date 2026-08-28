#!/bin/sh
set -eu

install -o mongodb -g mongodb -m 0400 /run/secrets/mongo-keyfile /data/configdb/keyfile
exec /usr/local/bin/docker-entrypoint.sh "$@"
