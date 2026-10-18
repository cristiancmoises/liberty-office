#!/bin/sh
# Creates and deletes ONLY its own new acceptance volume. Never uses the production volume.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v docker >/dev/null
[ -d node_modules/@playwright/test ] || { printf '%s\n' 'Run npm ci and install Playwright Chromium on this test host.' >&2; exit 1; }
project="liberty-acceptance-$(date +%s)-$$"
export PUBLIC_ORIGIN="http://localhost:${ACCEPTANCE_PORT:-18097}"
export EDITOR_ORIGIN="http://localhost:${ACCEPTANCE_EDITOR_PORT:-18098}"
export DEMO_EDITOR_ORIGIN="http://localhost:${ACCEPTANCE_DEMO_EDITOR_PORT:-18099}"
export LIBERTY_BIND=127.0.0.1 LIBERTY_PORT=${ACCEPTANCE_PORT:-18097} EDITOR_PORT=${ACCEPTANCE_EDITOR_PORT:-18098}
export DEMO_EDITOR_PORT=${ACCEPTANCE_DEMO_EDITOR_PORT:-18099}
initial_volume="$project-data";restore_volume="$project-restored"
export LIBERTY_VOLUME_NAME="$initial_volume"
export LIBERTY_IMAGE="$project:0.2.0-rc.2"
work="acceptance-results/$project";mkdir -p "$work";chmod 700 "$work"
compose(){ docker compose -p "$project" -f compose.yaml "$@"; }
cleanup(){ compose down --volumes --remove-orphans >/dev/null 2>&1 || true; docker volume rm "$initial_volume" "$restore_volume" >/dev/null 2>&1 || true; rm -f "$work/seed.json"; }
trap cleanup EXIT HUP INT TERM
compose config --quiet
compose build
compose up -d --wait
compose exec -T office python -m scripts.acceptance > "$work/api.json"
compose cp office:/data/tmp/acceptance-seed.json "$work/seed.json"
compose restart office
compose up -d --wait
compose exec -T office python -m liberty.cli doctor --deep > "$work/runtime.json"
export LIBERTY_ACCEPTANCE_SEED="$(pwd)/$work/seed.json"
export LIBERTY_DEMO_ORIGIN="$PUBLIC_ORIGIN"
npm run test:browser
compose stop office
compose run --rm --no-deps -T office python -m liberty.cli backup --stdout > "$work/backup.tar.gz"
chmod 600 "$work/backup.tar.gz"
# New acceptance service is already stopped. Restore only into another new test volume.
docker volume create "$restore_volume" >/dev/null
docker run --rm -i --user 10001:10001 --mount "source=$restore_volume,target=/data" "$LIBERTY_IMAGE" python -m liberty.cli restore - /data < "$work/backup.tar.gz"
export LIBERTY_VOLUME_NAME="$restore_volume"
compose up -d --force-recreate --wait
compose exec -T office python -m scripts.acceptance --verify-restored --seed - < "$work/seed.json" > "$work/restored.json"
rm -f "$work/backup.tar.gz"
printf '%s\n' 'API, runtime integrity, browser smoke and backup/restore gates passed on this host.' > "$work/result.txt"
cat "$work/result.txt"
