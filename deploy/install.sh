#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root: sudo bash install.sh" >&2
  exit 1
fi

SOURCE_DIR=""
REPOSITORY="${NEXTGATEWAY_REPOSITORY:-Mendex777/NextGateway}"
VERSION="${NEXTGATEWAY_VERSION:-latest}"
ARCHIVE_URL="${NEXTGATEWAY_ARCHIVE_URL:-}"
CHECKSUM_URL="${NEXTGATEWAY_CHECKSUM_URL:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE_DIR="${2:?--source requires a directory}"; shift 2 ;;
    --repository) REPOSITORY="${2:?--repository requires OWNER/REPO}"; shift 2 ;;
    --version) VERSION="${2:?--version requires a release tag}"; shift 2 ;;
    --archive-url) ARCHIVE_URL="${2:?--archive-url requires a URL}"; shift 2 ;;
    --checksum-url) CHECKSUM_URL="${2:?--checksum-url requires a URL}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "Invalid GitHub repository. Expected OWNER/REPO." >&2
  exit 2
fi

if [[ -z "$SOURCE_DIR" && -z "$ARCHIVE_URL" ]]; then
  if [[ "$VERSION" == "latest" ]]; then
    release_base="https://github.com/${REPOSITORY}/releases/latest/download"
  elif [[ "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]]; then
    release_base="https://github.com/${REPOSITORY}/releases/download/${VERSION}"
  else
    echo "Invalid release version: $VERSION" >&2
    exit 2
  fi
  ARCHIVE_URL="${release_base}/nextgateway.tar.gz"
  CHECKSUM_URL="${release_base}/nextgateway.tar.gz.sha256"
fi

if [[ -n "$ARCHIVE_URL" && -z "$CHECKSUM_URL" ]]; then
  echo "A checksum URL is required for remote archives." >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl iproute2 python3 python3-venv sudo

if ! id nextgateway >/dev/null 2>&1; then
  useradd --system --home /var/lib/nextgateway --shell /usr/sbin/nologin nextgateway
fi
install -d -o root -g root -m 0755 /opt/nextgateway
install -d -o nextgateway -g nextgateway -m 0700 /var/lib/nextgateway
install -d -o root -g root -m 0755 /var/lib/nextgateway-system
install -d -o root -g root -m 0750 /etc/mihomo
install -d -o root -g nextgateway -m 0750 /etc/nextgateway

work_dir=$(mktemp -d /tmp/nextgateway-install.XXXXXX)
cleanup() { rm -rf -- "$work_dir"; }
trap cleanup EXIT

if [[ -n "$SOURCE_DIR" ]]; then
  source_root=$(realpath "$SOURCE_DIR")
elif [[ -n "$ARCHIVE_URL" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 "$ARCHIVE_URL" -o "$work_dir/release.tar.gz"
  curl --fail --location --proto '=https' --tlsv1.2 "$CHECKSUM_URL" \
    -o "$work_dir/release.tar.gz.sha256"
  expected_checksum=$(awk 'NR == 1 {print $1}' "$work_dir/release.tar.gz.sha256")
  if [[ ! "$expected_checksum" =~ ^[a-fA-F0-9]{64}$ ]]; then
    echo "The release checksum is invalid." >&2
    exit 1
  fi
  actual_checksum=$(sha256sum "$work_dir/release.tar.gz" | awk '{print $1}')
  if [[ "${actual_checksum,,}" != "${expected_checksum,,}" ]]; then
    echo "Release checksum verification failed." >&2
    exit 1
  fi
  tar -xzf "$work_dir/release.tar.gz" -C "$work_dir"
  source_root=$(find "$work_dir" -mindepth 1 -maxdepth 1 -type d -print -quit)
else
  echo "A release archive or --source directory is required." >&2
  exit 2
fi

test -f "$source_root/pyproject.toml"
test -f "$source_root/backend/nextgateway/main.py"
test -f "$source_root/frontend-next/dist/index.html"

rm -rf -- /opt/nextgateway/source.new
install -d -o root -g root -m 0755 /opt/nextgateway/source.new
cp -a "$source_root/." /opt/nextgateway/source.new/
if [[ -d /opt/nextgateway/source ]]; then
  mv /opt/nextgateway/source "/opt/nextgateway/source.previous.$(date +%s)"
fi
mv /opt/nextgateway/source.new /opt/nextgateway/source
chown -R root:root /opt/nextgateway/source
chmod -R a+rX /opt/nextgateway/source

python3 -m venv /opt/nextgateway/venv
/opt/nextgateway/venv/bin/pip install --disable-pip-version-check /opt/nextgateway/source

cat >/etc/systemd/system/nextgateway-api.service <<'UNIT'
[Unit]
Description=NextGateway bootstrap and management API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nextgateway
Group=nextgateway
UMask=0077
WorkingDirectory=/var/lib/nextgateway
Environment=NEXTGATEWAY_DATABASE_URL=sqlite:////var/lib/nextgateway/nextgateway.db
Environment=NEXTGATEWAY_SYSTEM_MUTATIONS_ENABLED=true
Environment=NEXTGATEWAY_FRONTEND_DIST=/opt/nextgateway/source/frontend-next/dist
Environment=NEXTGATEWAY_ZASHBOARD_DIST=/opt/nextgateway/zashboard
ExecStart=/opt/nextgateway/venv/bin/uvicorn nextgateway.main:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=3
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/nextgateway /var/lib/nextgateway-system /etc/netplan /etc/mihomo /etc/nextgateway
ReadWritePaths=-/run/netplan /run/systemd/network /run/systemd/system /run/udev/rules.d
[Install]
WantedBy=multi-user.target
UNIT

install -o root -g root -m 0440 \
  /opt/nextgateway/source/deploy/nextgateway-sudoers /etc/sudoers.d/nextgateway
visudo -cf /etc/sudoers.d/nextgateway >/dev/null

setup_token=$(/opt/nextgateway/venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')
printf '%s\n' "$setup_token" >/var/lib/nextgateway/bootstrap-token
chown nextgateway:nextgateway /var/lib/nextgateway/bootstrap-token
chmod 0600 /var/lib/nextgateway/bootstrap-token

cd /opt/nextgateway/source
sudo -u nextgateway env NEXTGATEWAY_DATABASE_URL=sqlite:////var/lib/nextgateway/nextgateway.db \
  /opt/nextgateway/venv/bin/alembic upgrade head
systemctl daemon-reload
systemctl enable nextgateway-api.service
systemctl restart nextgateway-api.service

manager_ip=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
if [[ -z "$manager_ip" ]]; then
  manager_ip=$(hostname -I | awk '{print $1}')
fi

echo
echo "NextGateway is ready for browser setup:"
echo "http://${manager_ip}:8080/?token=${setup_token}"
echo
echo "The bootstrap has not changed networking, DNS, routing, nftables, or installed Mihomo."
echo "Continue all remaining installation steps in the browser."
