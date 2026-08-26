# Clean VM acceptance test

The test starts from the saved empty snapshot of `prx-ng-dev01`.

## Bootstrap boundary

SSH may be used only to launch `deploy/install.sh` and to read its one-time setup URL.
The bootstrap passes only when it starts the manager without changing the VM network,
DNS, routes, sysctl, nftables, or installing Mihomo.

After the setup URL is printed, all state-changing actions and all secret input must be
performed in the visible browser UI. Direct API requests and SSH configuration commands
are not part of this acceptance test.

## Browser journey

1. Open the one-time URL and create the administrator.
2. Enter and save the network, router, DNS, and LAN values.
3. Install Mihomo from the wizard.
4. Apply the static network and reopen the manager at its configured address.
5. Confirm the network before its rollback timer expires.
6. Apply and confirm gateway forwarding/NAT.
7. Paste the subscription URL into the protected subscription field and import it.
8. Confirm that the UI reports the expected compatible nodes and `VPN-Auto` group.
9. Apply TUN and DNS, verify connectivity, then confirm the change.
10. Install Zashboard and reach the completed manager UI.
11. Open Live Dashboard and verify that it connects to Mihomo.

## Final client check

Temporarily set a LAN device's gateway and DNS to the NextGateway address. Verify Internet
access, a blocked resource, DNS resolution through the gateway, the first traceroute hop,
the public exit address, and access to the physical router. Restore the client's original
network settings after the check.
