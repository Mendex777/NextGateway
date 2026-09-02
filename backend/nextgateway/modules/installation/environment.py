import json
import platform
import subprocess

from fastapi import HTTPException

from .schemas import EnvironmentRead


def ip_state() -> tuple[list[str], dict[str, list[str]], str | None, str | None]:
    try:
        links = json.loads(
            subprocess.run(
                ["/usr/sbin/ip", "-j", "address", "show"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        )
        routes = json.loads(
            subprocess.run(
                ["/usr/sbin/ip", "-j", "route", "show", "default"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Unable to inspect network state") from exc
    ignored_interfaces = {"lo", "mihomo"}
    interfaces = [link["ifname"] for link in links if link["ifname"] not in ignored_interfaces]
    addresses = {
        link["ifname"]: [
            f"{item['local']}/{item['prefixlen']}"
            for item in link.get("addr_info", [])
            if item.get("family") == "inet"
        ]
        for link in links
        if link["ifname"] not in ignored_interfaces
    }
    default = routes[0] if routes else {}
    return interfaces, addresses, default.get("gateway"), default.get("dev")


def environment() -> EnvironmentRead:
    interfaces, addresses, gateway, interface = ip_state()
    return EnvironmentRead(
        os=platform.freedesktop_os_release().get("PRETTY_NAME", platform.platform()),
        interfaces=interfaces,
        addresses=addresses,
        default_gateway=gateway,
        default_interface=interface,
    )
