# Architecture

## Invariants

1. SQLite and the internal domain model are the source of truth.
2. Frontend and API deal in protocol-neutral entities, not Mihomo YAML.
3. Generated configuration is written to a temporary file and must pass
   `mihomo -t` before it can replace the active configuration.
4. Network and service mutations require backup, verification and rollback.
5. Application services run unprivileged. A future privileged helper exposes
   only a narrow allow-listed operation set.
6. Subscription URLs and node credentials are secrets and must not be logged.

## Initial module boundaries

```text
API -> domain/database -> compiler -> generated Mihomo YAML
                    \-> system apply coordinator -> privileged helper
```

The compiler is pure: the same database snapshot always produces the same
configuration. It never writes system files or restarts services.

The development deployment invokes the root-owned helper through a strict
sudoers allow-list. Consequently the API unit cannot use systemd's
`NoNewPrivileges=true`; the preferred production evolution is a dedicated Unix
socket service that validates peer credentials and request schemas.
