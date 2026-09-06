"""
Find the address the phone should use, and render it as a scannable QR code.

Phase 0 (2026-08-19) established that this carrier is IPv6-only (464XLAT): the hotspot
gives the Mac a 192.0.0.2/32 CLAT stub and a global IPv6 address, and there is no
172.20.10.x network. `ipconfig getifaddr en0` returns nothing useful. The resulting URL
is ~50 characters, so it is delivered as a QR code rather than typed.

The address is carrier-assigned and can change on reconnect, so this runs at every
startup instead of being recorded once.

    .venv/bin/python -m server.netinfo
"""
import ipaddress
import pathlib
import socket
import subprocess

try:
    import psutil as _psutil
except ImportError:  # The release dependency is introduced with packaging support.
    _psutil = None

QR_PATH = pathlib.Path("/tmp/ewaste_triage_qr.png")
_PRIVATE_IPV4_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
_GLOBAL_IPV6_NETWORK = ipaddress.IPv6Network("2000::/3")
_PRIVATE_IPV6_NETWORK = ipaddress.IPv6Network("fc00::/7")
_DOCUMENTATION_IPV6_NETWORK = ipaddress.IPv6Network("2001:db8::/32")


def discover_lan_addresses() -> list[str]:
    """Return usable LAN addresses in a deterministic phone-friendly order."""
    if _psutil is None:
        return []
    candidates: set[tuple[int, int, str]] = set()
    for addresses in _psutil.net_if_addrs().values():
        for entry in addresses:
            if entry.family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            candidate = _lan_candidate(entry.address)
            if candidate is not None:
                candidates.add(candidate)
    return [address for _, _, address in sorted(candidates)]


def preferred_lan_address() -> str | None:
    """Return the best currently usable LAN address, if one exists."""
    addresses = discover_lan_addresses()
    return addresses[0] if addresses else None


def _lan_candidate(raw_address: str) -> tuple[int, int, str] | None:
    literal = raw_address.partition("%")[0]
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        return None
    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        return None
    if address in _DOCUMENTATION_IPV6_NETWORK:
        return None
    if address.version == 4:
        if not any(address in network for network in _PRIVATE_IPV4_NETWORKS):
            return None
        return 0, int(address), str(address)
    if address in _GLOBAL_IPV6_NETWORK:
        return 1, int(address), str(address)
    if address in _PRIVATE_IPV6_NETWORK:
        return 2, int(address), str(address)
    return None


def parse_global_ipv6(ifconfig_output):
    """Return the stable global IPv6, skipping link-local, temporary, and CLAT addresses."""
    for line in ifconfig_output.splitlines():
        line = line.strip()
        if not line.startswith("inet6 "):
            continue
        if "temporary" in line or "clat46" in line:
            continue
        addr = line.split()[1].split("%")[0]
        if addr.startswith("fe80") or addr.startswith("::"):
            continue
        return addr
    return None


def current_ipv6(interface="en0"):
    out = subprocess.run(["ifconfig", interface], capture_output=True, text=True).stdout
    return parse_global_ipv6(out)


def make_qr(url, path=None):
    # Resolved at call time, not bound as a default, so tests can redirect QR_PATH.
    path = pathlib.Path(path or QR_PATH)
    import qrcode
    qrcode.make(url).resize((600, 600)).save(path)
    return path


def print_access_urls(port, interface="en0", open_qr=True):
    addr = current_ipv6(interface)
    if not addr:
        print(f"No global IPv6 on {interface}. Is the Mac joined to the phone's hotspot?")
        print(f"Falling back to localhost only: http://127.0.0.1:{port}")
        return None

    url = f"http://[{addr}]:{port}"
    path = make_qr(url)
    print(f"\n  Phone URL: {url}")
    print(f"  QR code:   {path}")
    print("  This address is carrier-assigned and changes on reconnect — rescan each session.\n")
    if open_qr:
        subprocess.run(["open", str(path)], check=False)
    return url


if __name__ == "__main__":
    print_access_urls(8777)
