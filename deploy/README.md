# PowerAdapter Docker deployment

This layout keeps local development on `run.py`. Production runs Django,
PostgreSQL, Redis, the transaction-capable MongoDB audit store, and both bounded
workers in Docker Compose. Host Nginx owns TLS/mTLS and proxies only to
`127.0.0.1:18000`; this avoids requiring Docker Desktop or WSL on the Windows
development machine and keeps the client-certificate boundary outside the app
network.

## One-time server preparation

1. Install Docker Engine and the Compose plugin on a Linux server.
2. Copy the repository checkout to the server.
3. Copy `deploy/.env.production.example` to `deploy/.env.production`, replace
   every placeholder, then set mode `0600`. Compose uses this file for
   interpolation only; each service receives an explicit least-secret subset.
4. Create `deploy/secrets/mongo-keyfile` with at least 32 random bytes encoded as
   base64 text and set mode `0400`. This is the Mongo replica-set member key, not
   an application HMAC key.
5. Create `deploy/var/{static,media,media-private,logs}` and grant UID/GID 10001
   write access. Never expose `media-private` through Nginx.
6. Render `deploy/nginx/skate_media.conf.example` to a root-owned Nginx snippet,
   replacing `__PROJECT_ROOT__`. Render `deploy/nginx/poweradapter.conf.example`
   with the snippet path, real absolute paths, domains, certificates, CRL, and
   the same proxy secret used by Django. Both public and admin vhosts must load
   the SK8 snippet before their generic `/media/` handling.

On a Tencent Cloud mainland host, image builds may time out against Debian or
PyPI. In that environment only, set these public build-only values in the
production env file (application containers do not receive them):

```dotenv
DEBIAN_MIRROR_HOST=mirrors.tencentyun.com
PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
```

Keep the example defaults for hosts that can reliably reach the upstream
repositories. This mirror switch changes package transport, not the pinned
package requirements or runtime configuration.

The Root Client CA private key remains offline. The server receives only the
public CA chain and current CRL. Do not enable the admin vhost until Nginx is
built against the project-approved latest OpenSSL 4.0 patch and the certificate
binding flow has been tested.

## Validate and start

Choose exactly one first-release mode before the first `prepare`.

For an existing-site migration, keep `BOOTSTRAP_FRESH_SITE=false`, start the
stateful services, and restore the verified PostgreSQL backup containing users,
Categories, Boards, memberships, posts, and content metadata:

```bash
docker compose --env-file deploy/.env.production -f compose.production.yml up -d postgres redis mongo
docker compose --env-file deploy/.env.production -f compose.production.yml run --rm mongo-init
# Restore the verified PostgreSQL dump here, then confirm the music Board exists.
```

For an explicitly approved empty site, set `BOOTSTRAP_FRESH_SITE=true` for the
first successful `prepare` and set `BOOTSTRAP_OWNER_USERNAME` to an existing,
active superuser created after the initial migration. The bootstrap command
creates the three missing Board/Category pairs, assigns every Category to that
superuser, and preserves existing Board editorial fields. Set the flag back to
`false` after the first release. Do not run `seed_boards` in production: it
assumes local Category IDs and can overwrite editorial metadata.
Set `IMPORT_MUSIC_RECORDS=false` only for recovery work; never use it to publish
an accidentally empty Music page.

All Compose commands must explicitly load the production interpolation file:

```bash
docker compose --env-file deploy/.env.production -f compose.production.yml config
docker compose --env-file deploy/.env.production -f compose.production.yml build
docker compose --env-file deploy/.env.production -f compose.production.yml run --rm prepare
docker compose --env-file deploy/.env.production -f compose.production.yml up -d web audit-worker skate-worker
docker compose --env-file deploy/.env.production -f compose.production.yml ps
```

The `prepare` service applies migrations, collects static files, initializes the
Mongo audit indexes, checks that transactions are available, and (when
`IMPORT_MUSIC_RECORDS=true`) idempotently imports the normalized Spotify and
Apple Music JSON. Restore the relational database before `prepare`; a missing
Board deliberately fails the release
instead of silently publishing an empty Music page. It must finish successfully
before web/workers start. The HTTP `/healthz/` probe checks
PostgreSQL and Redis without exposing diagnostics; it is an operations endpoint,
not an application API.

Mongo credentials are separated by role: root exists only at Mongo initialization
and replica-set bootstrap; `prepare` receives an index-only deploy account;
`audit-worker` receives the insert-only delivery account; web plus non-audit
workers receive the read-only verifier account. Never collapse these accounts
into a shared `readWrite` user.

The checked-in defaults target the initial 2 GiB host: one Gunicorn worker and a
0.256 GiB WiredTiger cache (MongoDB's supported minimum). Increase them only after observing real memory and
latency under load.

## Release checks

Run these inside the built image before switching Nginx upstream traffic:

```bash
docker compose --env-file deploy/.env.production -f compose.production.yml run --rm web python manage.py check --deploy
docker compose --env-file deploy/.env.production -f compose.production.yml run --rm web python manage.py makemigrations --check --dry-run
docker compose --env-file deploy/.env.production -f compose.production.yml run --rm web python manage.py audit_outbox_health
```

Back up PostgreSQL, MongoDB, `deploy/var/media`, and
`deploy/var/media-private` independently. A database backup alone cannot restore
SK8 delivery assets or private source files.
