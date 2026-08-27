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
node_bin=$(command -v node || true)
if [[ -z "$node_bin" && -x "$(dirname "$(command -v npm)")/node.exe" ]]; then
  node_bin="$(dirname "$(command -v npm)")/node.exe"
fi
[[ -n "$node_bin" ]]

cd "$repository_root/frontend-next"
npm ci
"$node_bin" --experimental-strip-types scripts/build-openapi.mjs
npx vite build

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
  routing-templates \
  frontend-next/dist \
  frontend-next/LICENSE.3X-UI \
  frontend-next/UPSTREAM.md \
  deploy/nextgateway-sudoers | tar -C "$release_root" -xf -

tar -C "$stage_dir" -czf "$output_dir/nextgateway.tar.gz" nextgateway
(
  cd "$output_dir"
  sha256sum nextgateway.tar.gz >nextgateway.tar.gz.sha256
)

echo "Release assets created in $output_dir"
