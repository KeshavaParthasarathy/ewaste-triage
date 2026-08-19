# Experiment log

## Phase 0 — hotspot viability test — 2026-08-19

**Result: PASS.** The phone reached the laptop over Personal Hotspot and uploaded a photo.

Server-side evidence:

```
PAGE LOAD from 2607:fb90:5029:4ea7:3c6a:b0fa:9154:c091
           UA: Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X)
UPLOAD     3,275,899 bytes, filename=image.jpg
```

### The assumption that was wrong

The plan expected an IPv4 hotspot subnet at `172.20.10.x`. **That network does not exist
on this carrier.** T-Mobile (IPv6 prefix `2607:fb90`) runs IPv6-only, and the Mac gets:

```
inet  192.0.0.2 netmask 0xffffffff     <- /32 CLAT stub, not a LAN address
inet6 2607:fb90:5029:4ea7:...:394 prefixlen 64  clat46
```

`clat46` is 464XLAT. A server bound to `0.0.0.0` is unreachable here. It must bind `::`.

### Findings

| Question | Answer |
|---|---|
| AP client isolation? | **No.** Phone and Mac share a `/64`; they route directly. |
| `capture="environment"` over plain http on a LAN IP? | **Works.** Camera opened, photo uploaded. |
| HEIC on the upload path? | **Not an issue.** iOS delivered `image.jpg`. |
| macOS firewall prompt? | **N/A.** Firewall is disabled on this machine. |
| Upload size without downscaling | 3.27 MB — confirms client-side resize is required |
| Phone OS | iOS 18.7 |

### Consequences for the build

1. Server binds `::`, not `0.0.0.0`.
2. Address discovery is not `ipconfig getifaddr en0` — that returns nothing useful here.
   Read the stable global IPv6 from `ifconfig en0`.
3. The URL is ~50 characters and cannot reasonably be typed on a phone. Generate a QR
   code at server startup. This is an improvement for the fair: judges scan and try it
   on their own phones.
4. The carrier-assigned IPv6 address **may change** when the hotspot reconnects. The QR
   must be regenerated at startup, never printed once and trusted.
