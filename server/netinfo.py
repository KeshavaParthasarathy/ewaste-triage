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
import pathlib
import subprocess

QR_PATH = pathlib.Path("/tmp/ewaste_triage_qr.png")


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
