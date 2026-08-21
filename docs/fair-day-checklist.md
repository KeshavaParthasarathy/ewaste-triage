# Fair-day checklist

Run this end-to-end at home at least twice, at least a week before the fair.

The network facts below come from the Phase 0 hotspot test (`docs/experiment-log.md`,
2026-08-19): the carrier is IPv6-only 464XLAT, so there is no `172.20.10.x` hotspot
subnet and `ipconfig getifaddr en0` gives nothing usable. The address is a ~50-character
IPv6 literal, which is why it is scanned rather than typed.

## The night before
- [ ] `git status` clean, everything committed
- [ ] `.venv/bin/python -m pytest tests/ -v` — all green
- [ ] `.venv/bin/python -m server.app --demo` lists 10-15 fallback photos
      (if it says "none", shoot them — see `data/demo_photos/README.md`)
- [ ] `models/best.pt` exists — the server refuses to boot without a trained checkpoint
- [ ] Laptop charged; charger packed
- [ ] Phone charged; **Low Power Mode OFF** (it disables Personal Hotspot)
- [ ] Screen recording of a working session saved to the laptop desktop

## Setup, in this order
- [ ] Phone: Settings → Personal Hotspot → Allow Others to Join
- [ ] Mac: join the phone's hotspot from the WiFi menu
- [ ] `.venv/bin/python -m server.netinfo` → prints the IPv6 URL, writes
      `/tmp/ewaste_triage_qr.png` and opens it in Preview; scan it with the phone
      (`server.app` runs the same thing at startup, so this step is just an early check)
      (fallback if it says "No global IPv6" or the QR will not open: `ifconfig en0 | grep
      inet6` and use the global address — the `fe80::` link-local one will not work)
- [ ] Note whether the IPv6 address changed since last run — it is carrier-assigned and
      may change on every hotspot reconnect, so never reuse yesterday's QR
- [ ] `caffeinate -i .venv/bin/python -m server.app`
      (startup must say `Running on all addresses (::)` — binding IPv4 would be unreachable here)
- [ ] Firewall: this Mac has it **off** (`/usr/libexec/ApplicationFirewall/socketfilterfw
      --getglobalstate` → `Firewall is disabled. (State = 0)`), so no incoming-connections
      prompt should appear. If one does, someone turned the firewall on — approve it.
- [ ] Phone Safari → `http://[<that-ipv6>]:8777` → take one photo → confirm a result
      (the square brackets are required for an IPv6 literal in a URL)
- [ ] Write the URL on a card next to the board

## If it breaks
1. Laptop asleep → wake it, the server survives under `caffeinate`
2. Phone lost the hotspot → toggle Personal Hotspot off and on, rejoin the Mac
3. Page loads but upload hangs → re-check the address: the hotspot may have reconnected
   with a new IPv6. Re-run `server.netinfo` and rescan. If the firewall got switched on,
   turn it off in System Settings → Network → Firewall.
4. Nothing works → classify a demo photo from the laptop and narrate it:
   `curl -s -F image=@data/demo_photos/<name>.jpg http://[::1]:8777/classify | .venv/bin/python -m json.tool`
5. Still nothing → play the screen recording

## What to say when a judge asks how it works
The model classifies the device from the outside. The part breakdown comes from a lookup
table keyed on that classification. It does not see inside the case, and it cannot tell
whether a part still works — which is why the teardown data matters.
