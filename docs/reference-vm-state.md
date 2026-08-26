# Reference gateway state

Captured from `prx-ng-dev01` before converting the project to browser-driven setup.
No credentials, subscription URLs, node UUIDs, or API secrets are recorded here.

- OS: Ubuntu 24.04 LTS
- LAN interface: `ens18`
- Manager address: `192.168.1.84/24`
- Upstream gateway: `192.168.1.1`
- TUN interface: `mihomo`, `198.18.0.1/30`
- LAN DNS: TCP/UDP `192.168.1.84:53`
- Manager UI: `192.168.1.84:8080`
- Mihomo controller: `192.168.1.84:9090`, secret required
- IPv4 forwarding: enabled
- Managed NAT: `192.168.1.0/24` masqueraded through `ens18`
- Services: `nextgateway-api`, `mihomo`, and `nextgateway-firewall` active

This is the expected outcome of the setup wizard, not a prerequisite for installing
NextGateway.
