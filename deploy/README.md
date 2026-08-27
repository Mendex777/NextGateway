# Bootstrap deployment

`install.sh` installs the manager on a clean Ubuntu 24.04 machine without changing
its existing networking. It binds the authenticated setup UI to port 8080 and prints
a one-time tokenized URL. System mutations are delegated to the root-owned helper
through a narrow sudoers allow-list.

Public installation:

```bash
curl -fsSL https://raw.githubusercontent.com/Mendex777/NextGateway/master/deploy/install.sh | sudo bash
```

The remote release archive is accepted only when its separately downloaded SHA-256
checksum matches. `--repository OWNER/REPO` and `--version vX.Y.Z` may be used for a fork
or pinned release. `--source` is reserved for local development and clean-VM testing.

Deployment layout:

- application source: `/opt/nextgateway/source`
- virtual environment: `/opt/nextgateway/venv`
- state and SQLite database: `/var/lib/nextgateway`
- API and UI service: `nextgateway-api.service`

The browser wizard installs the selected components in resumable stages. Static network,
gateway forwarding/NAT, and Mihomo configuration each have rollback protection and
separate confirmation steps.

Once bootstrap prints the setup URL, do not finish setup over SSH or by calling the API
manually. Enter the subscription and perform every remaining action through the visible
browser wizard; this is the supported user journey and the clean-snapshot acceptance test.
