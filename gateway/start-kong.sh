#!/bin/sh
# Render gateway/kong.yml with secrets from the environment, then start Kong (DB-less).
set -eu

: "${JWT_SECRET:?JWT_SECRET must be set}"
: "${API_UPSTREAM:?API_UPSTREAM must be set, e.g. http://api:8080}"

# Escape characters that are special in the sed replacement.
escape() { printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g'; }

sed -e "s|__JWT_SECRET__|$(escape "$JWT_SECRET")|" \
    -e "s|__API_UPSTREAM__|$(escape "$API_UPSTREAM")|" \
    /kong/kong.yml > /tmp/kong.yml

export KONG_DECLARATIVE_CONFIG=/tmp/kong.yml
exec /docker-entrypoint.sh kong docker-start
