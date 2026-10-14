#!/usr/bin/env bash
# Smoke-test a locally built image, then push exactly that image under every
# given tag and check that all tags resolve to the same digest.
#
#   scripts/publish_tested_image.sh LOCAL_IMAGE TAG [TAG...]
#
# Nothing is pushed unless the smoke test passes. The image is referenced by its
# ID, so the pushed bytes are the ones that were tested. Prints
# "digest=sha256:..." and, on GitHub Actions, writes it to $GITHUB_OUTPUT.
set -euo pipefail

image="${1:?usage: $0 LOCAL_IMAGE TAG [TAG...]}"
shift
if [ "$#" -eq 0 ]; then
  echo "usage: $0 LOCAL_IMAGE TAG [TAG...]" >&2
  exit 2
fi
repo_root="$(cd "$(dirname "$0")/.." && pwd)"

image_id="$(docker image inspect --format '{{.Id}}' "$image")"
echo "== Smoke testing $image ($image_id)"
"$repo_root/scripts/container_smoke.sh" "$image_id"

echo "== Pushing the tested image"
for tag in "$@"; do
  docker tag "$image_id" "$tag"
  docker push --quiet "$tag"
done

echo "== Verifying that every tag points to the same digest"
digest=""
for tag in "$@"; do
  tag_digest="$(docker buildx imagetools inspect --format '{{.Manifest.Digest}}' "$tag")"
  echo "$tag -> $tag_digest"
  if [ -z "$digest" ]; then
    digest="$tag_digest"
  elif [ "$tag_digest" != "$digest" ]; then
    echo "::error::$tag points to $tag_digest, expected $digest" >&2
    exit 1
  fi
done

echo "digest=$digest"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "digest=$digest" >> "$GITHUB_OUTPUT"
fi
