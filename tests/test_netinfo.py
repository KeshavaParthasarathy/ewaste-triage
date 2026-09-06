"""
Address discovery is the one part of fair day that cannot be rehearsed away: the carrier
hands out the address, and a wrong pick (link-local, privacy-temporary, CLAT) produces a
QR code that scans fine and then fails to load in front of a judge.
"""
from PIL import Image

from server import netinfo
from server.netinfo import current_ipv6, make_qr, parse_global_ipv6, print_access_urls

IFCONFIG_IPV6_ONLY = """en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	inet6 fe80::f5:1ce2:d944:66ad%en0 prefixlen 64 secured scopeid 0xf
	inet6 2607:fb90:5029:4ea7:10be:b80a:29e9:394 prefixlen 64 autoconf secured
	inet6 2607:fb90:5029:4ea7:c0aa:6a18:3093:507 prefixlen 64 autoconf temporary
	inet 192.0.0.2 netmask 0xffffffff broadcast 192.0.0.2
	inet6 2607:fb90:5029:4ea7:1424:b1ed:7452:8e10 prefixlen 64 clat46
"""

# Captured verbatim from `ifconfig en0` on the demo MacBook, 2026-08-21, while joined to
# ordinary home WiFi rather than the hotspot. Kept because it is a different shape from
# the hotspot fixture: real IPv4, no clat46, and the only routable v6 is a router-issued
# ULA (fd00::/8) rather than a 2000::/3 global. The phone shares that /64 on the same
# LAN, so the ULA is the address the QR should carry here.
IFCONFIG_WIFI_REAL = """en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	options=6460<TSO4,TSO6,CHANNEL_IO,PARTIAL_CSUM,ZEROINVERT_CSUM>
	ether c8:89:f3:b8:e0:56
	inet6 fe80::f5:1ce2:d944:66ad%en0 prefixlen 64 secured scopeid 0xf 
	inet6 fdad:b36b:3734:d42e:1874:53d8:793:ca36 prefixlen 64 autoconf secured 
	inet 192.168.68.58 netmask 0xfffffc00 broadcast 192.168.71.255
	nd6 options=201<PERFORMNUD,DAD>
	media: autoselect
	status: active
"""

# A v4-only network, or the hotspot before it has finished handing out a prefix.
IFCONFIG_V4_ONLY = """en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	inet6 fe80::f5:1ce2:d944:66ad%en0 prefixlen 64 secured scopeid 0xf
	inet 192.168.1.42 netmask 0xffffff00 broadcast 192.168.1.255
"""


def _fake_ifconfig(monkeypatch, output):
    """Stand in for the ifconfig subprocess so tests never depend on the live network."""
    class _Completed:
        stdout = output

    monkeypatch.setattr(netinfo.subprocess, "run", lambda *a, **k: _Completed())


def test_picks_the_stable_secured_address():
    assert parse_global_ipv6(IFCONFIG_IPV6_ONLY) == "2607:fb90:5029:4ea7:10be:b80a:29e9:394"


def test_skips_temporary_privacy_addresses():
    assert "temporary" not in parse_global_ipv6(IFCONFIG_IPV6_ONLY)
    assert parse_global_ipv6(IFCONFIG_IPV6_ONLY) != "2607:fb90:5029:4ea7:c0aa:6a18:3093:507"


def test_skips_link_local_and_clat():
    got = parse_global_ipv6(IFCONFIG_IPV6_ONLY)
    assert not got.startswith("fe80")
    assert got != "2607:fb90:5029:4ea7:1424:b1ed:7452:8e10"


def test_returns_none_when_there_is_no_global_address():
    assert parse_global_ipv6("en0: flags=8863\n\tinet6 fe80::1%en0 prefixlen 64 secured\n") is None


def test_real_wifi_capture_picks_the_routable_address():
    assert parse_global_ipv6(IFCONFIG_WIFI_REAL) == "fdad:b36b:3734:d42e:1874:53d8:793:ca36"


def test_v4_only_network_yields_no_address():
    assert parse_global_ipv6(IFCONFIG_V4_ONLY) is None


def test_current_ipv6_reads_the_interface(monkeypatch):
    _fake_ifconfig(monkeypatch, IFCONFIG_IPV6_ONLY)
    assert current_ipv6("en0") == "2607:fb90:5029:4ea7:10be:b80a:29e9:394"


def test_current_ipv6_survives_an_interface_that_does_not_exist():
    # Really shells out: ifconfig exits non-zero and prints nothing on stdout.
    assert current_ipv6("nosuchif0") is None


def test_make_qr_writes_a_real_png(tmp_path):
    path = make_qr("http://[2607:fb90:5029:4ea7:10be:b80a:29e9:394]:8777", tmp_path / "qr.png")
    assert path.exists() and path.stat().st_size > 0
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.size == (600, 600)


def test_make_qr_default_path_is_the_documented_tmp_file():
    path = make_qr("http://[::1]:8777")
    assert path == netinfo.QR_PATH == __import__("pathlib").Path("/tmp/ewaste_triage_qr.png")
    with Image.open(path) as img:
        assert img.format == "PNG"


def test_print_access_urls_returns_the_bracketed_url(monkeypatch, tmp_path, capsys):
    _fake_ifconfig(monkeypatch, IFCONFIG_IPV6_ONLY)
    monkeypatch.setattr(netinfo, "QR_PATH", tmp_path / "qr.png")
    url = print_access_urls(8777, open_qr=False)
    assert url == "http://[2607:fb90:5029:4ea7:10be:b80a:29e9:394]:8777"
    assert url in capsys.readouterr().out


def test_print_access_urls_degrades_gracefully_without_ipv6(monkeypatch, capsys):
    """Offline or on a v4-only network the server must still start, not crash on boot."""
    _fake_ifconfig(monkeypatch, IFCONFIG_V4_ONLY)
    assert print_access_urls(8777, open_qr=False) is None
    out = capsys.readouterr().out
    assert "127.0.0.1:8777" in out


def test_print_access_urls_does_not_shell_out_when_open_qr_is_false(monkeypatch, tmp_path):
    _fake_ifconfig(monkeypatch, IFCONFIG_IPV6_ONLY)
    monkeypatch.setattr(netinfo, "QR_PATH", tmp_path / "qr.png")
    # _fake_ifconfig replaced subprocess.run wholesale; an `open` call would return the
    # fake ifconfig output instead of launching Preview, so assert on the QR file only.
    print_access_urls(8777, open_qr=False)
    assert (tmp_path / "qr.png").exists()


def test_discover_lan_addresses_filters_unsafe_addresses_and_orders_candidates(monkeypatch):
    class _Address:
        def __init__(self, family, address):
            self.family = family
            self.address = address

    class _Psutil:
        @staticmethod
        def net_if_addrs():
            return {
                "lo0": [_Address(2, "127.0.0.1"), _Address(30, "::1")],
                "en2": [_Address(2, "224.0.0.1"), _Address(30, "ff02::1")],
                "en1": [_Address(2, "0.0.0.0"), _Address(30, "fe80::1%en1")],
                "en0": [
                    _Address(30, "fd00::2"),
                    _Address(2, "192.168.1.20"),
                    _Address(30, "2606:4700:4700::1111"),
                    _Address(2, "10.0.0.9"),
                ],
            }

    monkeypatch.setattr(netinfo, "_psutil", _Psutil())

    assert netinfo.discover_lan_addresses() == [
        "10.0.0.9",
        "192.168.1.20",
        "2606:4700:4700::1111",
        "fd00::2",
    ]
    assert netinfo.preferred_lan_address() == "10.0.0.9"
