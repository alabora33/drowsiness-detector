#!/usr/bin/env bash
# Start an image and run scripts/smoke_test.py against it from a second
# container on the same Docker network (no Python needed on the host).
#
#   scripts/container_smoke.sh drowsiness-detector:dev
set -euo pipefail

image="${1:?usage: $0 IMAGE}"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
network="dd-smoke-$$"
name="dd-smoke-app-$$"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- container logs ---"
    docker logs "$name" 2>&1 | tail -40 || true
  fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$name" --network "$network" "$image" >/dev/null

docker run --rm --network "$network" \
  -v "$repo_root/scripts:/smoke/scripts:ro" \
  -v "$repo_root/tests/fixtures:/smoke/tests/fixtures:ro" \
  "$image" python /smoke/scripts/smoke_test.py --url "http://$name:8000"

for _ in $(seq 1 30); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$name")"
  [ "$health" != "starting" ] && break
  sleep 2
done
echo "Docker HEALTHCHECK status: $health"
[ "$health" = "healthy" ]
