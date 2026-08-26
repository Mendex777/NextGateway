# Development VM baseline

Captured read-only on 2026-08-24.

- Host: `prx-ng-dev01` / `192.168.1.84`
- OS: Ubuntu 24.04.4 LTS, x86_64
- Kernel: 6.8.0-100-generic
- Interface: `ens18`, DHCP, `192.168.1.84/24`
- Current default gateway: `192.168.1.2`
- Current DNS: `192.168.1.2` plus its advertised IPv6 address
- Intended independent upstream during gateway tests: `192.168.1.1`
- Network renderer: systemd-networkd through Netplan/cloud-init file
- `/dev/net/tun`: available
- nftables: available
- `tdcadmin`: passwordless sudo available
- Topology: single-arm gateway

Do not switch the default gateway until an automatic rollback watchdog exists.

