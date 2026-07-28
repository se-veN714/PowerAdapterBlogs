#!/bin/sh
set -eu

NGINX_BIN="${NGINX_BIN:-nginx}"
OPENSSL_BIN="${OPENSSL_BIN:-openssl}"

nginx_version="$("$NGINX_BIN" -V 2>&1)"
openssl_version="$("$OPENSSL_BIN" version 2>&1)"

case "$nginx_version" in
    *"OpenSSL 4.0."*) ;;
    *)
        echo "FAIL nginx_not_built_with_openssl_4_0" >&2
        echo "$nginx_version" >&2
        exit 1
        ;;
esac

case "$openssl_version" in
    "OpenSSL 4.0."*) ;;
    *)
        echo "FAIL ca_cli_not_openssl_4_0" >&2
        echo "$openssl_version" >&2
        exit 1
        ;;
esac

"$NGINX_BIN" -t

echo "PASS nginx_openssl_4_0"
echo "$openssl_version"
echo "$nginx_version"
