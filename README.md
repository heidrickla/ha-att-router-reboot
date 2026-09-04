# AT&T Router Reboot for Home Assistant

Local (no cloud) Home Assistant custom integration to **reboot an AT&T
residential gateway** on demand or on a schedule, and to watch its uptime and
broadband statistics. Built and verified against a **BGW320-500** on firmware
6.35.8; other BGW-series gateways share the same web interface and should work,
but are untested here.

Everything talks to the gateway over your local network - no AT&T account, no
cloud.

## What you get

- A **Reboot** button and a `att_router_reboot.reboot` action.
- An optional **built-in schedule** (off / daily / weekly) for people who would
  rather not write an automation. A scheduled reboot is skipped if the gateway
  has only just come up, so it can never power-cycle your only internet
  connection in a loop.
- Sensors, all read from pages the gateway serves **without a login**:
  **Uptime**, **WAN IP address**, **Line rate**, **Downstream/Upstream data**
  (byte counters), and **Receive/Transmit errors**.
- Binary sensors: **Reachable** (did the gateway answer) and **Internet
  connection** (does the gateway report its broadband link up) - deliberately
  separate, because a gateway can answer perfectly while its upstream is down.

## Requirements

- Home Assistant 2024.12 or newer.
- An AT&T gateway reachable on your LAN, usually at `192.168.1.254`. Home
  Assistant must be able to reach that address - on a segmented network, put
  Home Assistant where it can route to the gateway.
- The **device access code** printed on the gateway's label. This is what its
  web interface logs in with; it is only needed for the reboot, not for the
  statistics.

## Installation

1. Copy `custom_components/att_router_reboot` into your Home Assistant
   `custom_components` directory (or install through HACS as a custom
   repository).
2. Restart Home Assistant.
3. Settings -> Devices & Services -> Add Integration -> "AT&T Router Reboot".
4. Enter the gateway address and the device access code.
5. Optionally open the integration's **Configure** to set an automatic reboot
   schedule.

## How it works

- **Statistics** come from `sysinfo.ha` and `broadbandstatistics.ha`, which the
  gateway serves without authentication. That is why the sensors work even
  before you have entered an access code, and why a wrong code never blanks
  them.
- **Reboot** logs in the way the gateway's own web page does - the access code
  is hashed (`md5(code + nonce)`) against a per-request nonce, over an isolated
  session - and then **replays the gateway's own restart form** rather than
  posting a hardcoded body. If a firmware update renames a form field, replaying
  still submits the right thing; a hardcoded guess against the device the whole
  house routes through would not.

## Known limitations

- Only reboot, uptime and broadband statistics are implemented. The gateway
  exposes far more (NAT tables, per-port LAN counters, fibre diagnostics); this
  integration is scoped to fixing and watching a gateway, not managing one.
- The reboot response is expected to drop as the gateway restarts; that is
  treated as success. If a reboot silently fails, the uptime sensor is the place
  it shows - it will not reset.
- Verified only against BGW320-500 / 6.35.8. Other models render the same pages
  with small differences; the parser degrades to "unknown" on a field it does
  not recognise rather than reporting a wrong number.

## Development

- `custom_components/att_router_reboot/parse.py` holds the HTML parsing and has
  no Home Assistant import, so `tests/test_parse.py` and `tests/test_api.py`
  run on a bare interpreter against saved real HTML (`tests/fixtures/`, with the
  household's WAN IP, MAC and serial replaced by documentation placeholders).
- The Home Assistant layer is under `tests/ha/` and runs in CI.
- Quality scale is tracked rule by rule in
  `custom_components/att_router_reboot/quality_scale.yaml`.

## License

Copyright (C) 2026 Lewis Heidrick.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See [LICENSE](LICENSE) for the full text.
