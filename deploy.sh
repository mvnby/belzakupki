#!/usr/bin/env bash
# Deploy a reviewed, committed release. No production action without a SHA.
set -euo pipefail
release_sha=${1:?Usage: ./deploy.sh FULL_COMMIT_SHA [SSH_HOST]}
deploy_host=${2:-mvn-api-by}
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'A full commit SHA is required.' >&2; exit 2; }
git cat-file -e "${release_sha}^{commit}"
archive_path=$(mktemp "${TMPDIR:-/tmp}/belzakupki-release.XXXXXX")
deploy_output=$(mktemp "${TMPDIR:-/tmp}/belzakupki-deploy-output.XXXXXX")
trap 'rm -f "$archive_path" "$deploy_output"' EXIT
git archive --format=tar "$release_sha" > "$archive_path"
remote_stage=$(ssh "$deploy_host" 'umask 077; mktemp -d /tmp/belzakupki-release.XXXXXXXX')
[[ "$remote_stage" =~ ^/tmp/belzakupki-release\.[A-Za-z0-9]+$ ]] || { echo 'Unexpected staging path' >&2; exit 1; }
remote_archive="$remote_stage/source.tar"
scp "$archive_path" "$deploy_host:$remote_archive"
ssh "$deploy_host" sudo -n bash -s -- "$release_sha" "$remote_archive" <<'REMOTE' | tee "$deploy_output"
set -euo pipefail
release_sha=$1
archive_path=$2
trap 'rm -f "$archive_path"; rmdir "$(dirname "$archive_path")" 2>/dev/null || true' EXIT
project_dir=/opt/belzakupki
release_dir="$project_dir/releases/$release_sha"
lock=/var/lock/mvn-shared-host-belzakupki.lock
[[ ! -L "$lock" ]] || { echo 'Refusing symlink lock' >&2; exit 1; }
if [[ ! -e "$lock" ]]; then (umask 077; set -o noclobber; : > "$lock") || true; fi
[[ -f "$lock" && $(stat -c '%u:%a' "$lock") == '0:600' ]] || { echo 'Unsafe deployment lock ownership/mode' >&2; exit 1; }
exec 9<>"$lock"
flock -n 9 || { echo 'Another shared-host deployment is in progress.' >&2; exit 1; }
[[ -f "$project_dir/.env" ]] || { echo 'Provision /opt/belzakupki/.env before deployment.' >&2; exit 1; }
# A previously staged SHA is reused without mutating its source.
if [[ ! -d "$release_dir" ]]; then
    mkdir -p "$project_dir/releases"
    staging=$(mktemp -d "$project_dir/releases/.staging.XXXXXX")
    tar -xf "$archive_path" -C "$staging"
    mv "$staging" "$release_dir"
fi
cat > "$release_dir/build-context.override.yml" <<EOF
services:
  api:
    image: belzakupki:$release_sha
    build:
      context: $release_dir
  worker:
    image: belzakupki:$release_sha
    build:
      context: $release_dir
  scheduler:
    image: belzakupki:$release_sha
    build:
      context: $release_dir
  telegram:
    image: belzakupki:$release_sha
    build:
      context: $release_dir
EOF
compose=(docker compose --project-name belzakupki --project-directory "$project_dir" --env-file "$project_dir/.env" -f "$release_dir/docker-compose.prod.yml" -f "$release_dir/build-context.override.yml")
"${compose[@]}" config --quiet
# Validate the resolved secret before stopping any running service. Never print it.
"${compose[@]}" config --format json | python3 -c 'import json, sys; value = json.load(sys.stdin)["services"]["api"]["environment"].get("API_SECRET_KEY", ""); sys.exit(0 if len(value) >= 32 else "API_SECRET_KEY must contain at least 32 characters")'
# Never replace an existing queue with an empty external volume or switch an
# RDB-only queue to AOF before its initial AOF rewrite is durably complete.
redis_volume=$("${compose[@]}" config --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["volumes"]["redis_data"]["name"])')
[[ "$redis_volume" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || { echo 'Invalid Redis volume name' >&2; exit 1; }
redis_containers=$(docker ps -aq --filter label=com.docker.compose.project=belzakupki --filter label=com.docker.compose.service=redis)
if [[ -n "$redis_containers" ]]; then
    [[ "$redis_containers" != *$'\n'* ]] || { echo 'Multiple Redis containers found; resolve before deploying' >&2; exit 1; }
    current_volume=$(docker inspect --format '{{json .Mounts}}' "$redis_containers" | python3 -c 'import json, sys; mounts = [m for m in json.load(sys.stdin) if m["Destination"] == "/data" and m["Type"] == "volume"]; sys.exit("Redis /data must be one Docker volume; migrate explicitly") if len(mounts) != 1 else print(mounts[0]["Name"])')
    if [[ "$current_volume" != "$redis_volume" ]]; then
        echo "Redis volume mismatch: existing=$current_volume requested=$redis_volume. Set REDIS_DATA_VOLUME to the existing volume, or perform an explicit data migration first." >&2
        exit 1
    fi
    docker exec "$redis_containers" redis-cli --raw INFO persistence | python3 -c '
import sys
info = dict(line.strip().split(":", 1) for line in sys.stdin if ":" in line)
expected = {"aof_enabled": "1", "aof_rewrite_in_progress": "0", "aof_rewrite_scheduled": "0", "aof_last_bgrewrite_status": "ok", "aof_last_write_status": "ok"}
if any(info.get(key) != value for key, value in expected.items()):
    sys.exit("Redis AOF is not ready. Enable appendonly on the EXISTING running Redis and wait for successful initial rewrite before deploying; do not recreate it yet.")'
else
    # Docker volume create is idempotent: an existing durable volume is retained.
    docker volume create "$redis_volume" >/dev/null
fi
recovery_dir=$(mktemp -d "$project_dir/deploy-recovery.XXXXXX")
chmod 700 "$recovery_dir"
printf '%s\n' "$release_sha" > "$recovery_dir/attempted-sha"
if [[ -f "$project_dir/deployed-sha" ]]; then cp "$project_dir/deployed-sha" "$recovery_dir/previous-sha"; fi
# Cold rollout: suspend current queue producers and consumers before building.
# Restore only previously running containers if a build/migration fails.
previously_running=()
for service in scheduler worker telegram; do
    while IFS= read -r container; do
        [[ -z "$container" ]] || previously_running+=("$container")
    done < <(docker ps -q --filter label=com.docker.compose.project=belzakupki --filter "label=com.docker.compose.service=$service")
done
printf '%s\n' "${previously_running[@]}" > "$recovery_dir/previously-running"
restore_previous() {
    status=$?
    rm -f "$archive_path"
    rmdir "$(dirname "$archive_path")" 2>/dev/null || true
    if (( status != 0 )); then
        echo "Deployment failed; recovery record retained at $recovery_dir" >&2
        for container in "${previously_running[@]}"; do
            if docker inspect "$container" >/dev/null 2>&1; then
                if ! docker start "$container" >/dev/null; then
                    echo "RESTORE FAILED for previous container $container; operator recovery required" >&2
                fi
            else
                echo "Previous container $container was replaced; inspect the new rollout before retrying. No automatic rollback." >&2
            fi
        done
    fi
    exit "$status"
}
trap restore_previous EXIT
# SIGTERM asks RQ to finish its current job. Never force-kill a busy worker.
if (( ${#previously_running[@]} > 0 )); then
    for container in "${previously_running[@]}"; do
        docker kill --signal TERM "$container" >/dev/null
    done
    deadline=$((SECONDS + 60))
    for container in "${previously_running[@]}"; do
        while [[ $(docker inspect -f '{{.State.Running}}' "$container") == true ]]; do
            if (( SECONDS >= deadline )); then
                echo "Service is still completing work; aborting before build: $container" >&2
                exit 1
            fi
            sleep 2
        done
    done
fi
# All application services use the same immutable release-tagged image.
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" build api
"${compose[@]}" up -d --wait db redis
"${compose[@]}" run --rm --no-deps -T --interactive=false api alembic upgrade head
"${compose[@]}" up -d --no-deps api worker scheduler telegram
# Run inside API: works without publishing a port or changing Caddy routing.
"${compose[@]}" exec -T api python - <<'PY'
import json
import time
import urllib.error
import urllib.request
for attempt in range(60):
    try:
        for path in ('/api/health', '/api/ready'):
            with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=5) as response:
                assert response.status == 200
                json.load(response)
        try:
            urllib.request.urlopen('http://127.0.0.1:8000/api/auth/me', timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code == 401, f'Expected auth 401, received {error.code}'
        else:
            raise RuntimeError('Anonymous auth endpoint unexpectedly succeeded')
        break
    except Exception:
        if attempt == 59:
            raise
        time.sleep(3)
PY
for service in api worker scheduler telegram; do
    [[ -n $("${compose[@]}" ps --status running -q "$service") ]] || { echo "$service is not running" >&2; exit 1; }
done
printf '%s\n' "$release_sha" > "$project_dir/deployed-sha"
rm -r "$recovery_dir"
echo "Deployed and verified $release_sha"
REMOTE

# A remote shell may exit zero early if a child consumes its script stdin.
# Accept success only after the explicit marker emitted after all runtime probes.
if ! grep -Fxq "Deployed and verified $release_sha" "$deploy_output"; then
    echo 'Remote deployment ended without its verified completion marker; inspect deployment recovery state.' >&2
    exit 1
fi
