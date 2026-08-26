# Bootstrap and browser setup

NextGateway has two distinct installation phases.

## Minimal bootstrap

The root-run bootstrap script only installs the manager and its constrained privileged
helper. It must not install a proxy core or change the host network, routing, DNS, sysctl,
or nftables configuration. It starts the manager on the machine's current address and
prints the setup URL.

## Authenticated setup wizard

After the first administrator is created, the normal manager opens immediately. A
non-blocking, resumable setup checklist is available from the `Настройка` section and:

1. inspects the OS, interfaces, addresses, and current default route;
2. records a validated desired-state plan;
3. installs a selected supported core;
4. applies static networking with a rollback timer;
5. enables forwarding and managed NAT with a rollback timer;
6. imports nodes or a subscription and creates routing groups;
7. configures TUN and LAN DNS with a rollback timer;
8. verifies local reachability, DNS, Internet access, and the public exit address;
9. requires explicit confirmation before rollback timers are cancelled.

Every step is resumable and idempotent. A fresh database starts in `setup_required`, but
that state never blocks the manager UI. `complete` describes gateway readiness only. The
user may leave setup, manage available objects, and resume or reopen the wizard later.

Subscriptions, direct VLESS nodes, proxy groups, routing rules, runtime Mihomo deployment,
and protected network changes remain available after onboarding. The setup wizard is a
convenience layer over permanent management capabilities, not a one-time gate.

The acceptance test deliberately follows the same boundary: SSH is used only to launch
the bootstrap and perform read-only diagnostics. After the one-time URL appears, every
mutation and all secret input are performed through the visible browser UI.
