# NextGateway

Self-hosted manager for a Linux VPN gateway powered by Mihomo. The internal
database is the source of truth; Mihomo YAML is a generated and validated
deployment artifact.

## Development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m pytest
.venv\Scripts\python -m uvicorn nextgateway.main:app --reload
```

The API is available at `http://127.0.0.1:8080`, with OpenAPI at `/docs`.

Build the browser UI:

```powershell
Set-Location frontend
npm install
npm run dev
```

## Public installation

On a clean Ubuntu 24.04 VM, run:

```bash
curl -fsSL https://raw.githubusercontent.com/Mendex/NextGateway/main/deploy/install.sh | sudo bash
```

The installer downloads the latest GitHub release, verifies its SHA-256 checksum,
installs only the authenticated manager, and prints a one-time browser URL. A specific
release can be installed with `sudo bash install.sh --version v0.1.0`.

For local development, the same bootstrap can use a source checkout containing a built
`frontend-next/dist` directory:

```bash
sudo bash deploy/install.sh --source /path/to/NextGateway
```

After the URL is printed, all remaining interaction must happen in the browser interface:
administrator creation, desired network plan, Mihomo installation, network and gateway
changes, subscription entry, TUN/DNS, and Zashboard. The bootstrap does not perform any
of those steps. Privileged mutations use the constrained helper; network, gateway, and
Mihomo changes require explicit confirmation before their rollback timers are cancelled.

Only administrator creation is mandatory. The manager opens immediately afterward; its
setup checklist can be skipped, resumed, or reopened. Subscriptions, direct VLESS nodes,
groups, routing rules, Mihomo runtime configuration, and protected network settings remain
editable from the normal panel after onboarding.

GitHub releases are produced from version tags by `.github/workflows/release.yml`. The
workflow builds the frontend and publishes `nextgateway.tar.gz` plus its checksum.
