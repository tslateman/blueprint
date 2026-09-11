#!/bin/sh
# Fails if uv.lock resolves packages with known vulnerabilities that have a
# fixed release available. diskcache PYSEC-2026-2447 has no fix and is an
# accepted, explicitly ignored exception.
set -e

cd "$(dirname "$0")/.."

req_file=$(mktemp)
trap 'rm -f "$req_file"' EXIT

uv export --format requirements-txt --no-hashes --no-emit-project -q -o "$req_file"

uvx pip-audit -r "$req_file" --no-deps --disable-pip --progress-spinner off \
    --ignore-vuln PYSEC-2026-2447
