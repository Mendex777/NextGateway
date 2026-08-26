#!/usr/bin/env bash
set -Eeuo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
output_dir="${1:-$repository_root/dist-release}"
stage_dir=$(mktemp -d "${TMPDIR:-/tmp}/nextgateway-release.XXXXXX")

cleanup() { rm -rf -- "$stage_dir"; }
trap cleanup EXIT

command -v npm >/dev/null
command -v tar >/dev/null
command -v sha256sum >/dev/null

cd "$repository_root/frontend"
npm ci
npm run build

release_root="$stage_dir/nextgateway"
mkdir -p "$release_root" "$output_dir"
tar \
  --exclude='*/__pycache__' \
  --exclude='*.py[co]' \
  -C "$repository_root" -cf - \
  pyproject.toml \
  alembic.ini \
  backend/nextgateway \
  backend/migrations \
  frontend/dist \
  deploy/nextgateway-sudoers | tar -C "$release_root" -xf -

tar -C "$stage_dir" -czf "$output_dir/nextgateway.tar.gz" nextgateway
(
  cd "$output_dir"
  sha256sum nextgateway.tar.gz >nextgateway.tar.gz.sha256
)

echo "Release assets created in $output_dir"
