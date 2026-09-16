# AT&T Router Reboot for Home Assistant

Home Assistant custom integration to reboot an AT&T residential gateway on
demand or on a schedule, and to watch its uptime and broadband statistics.
Built and verified against a BGW320-500 on firmware 6.35.8. Other BGW-series
gateways share the same web interface; see Supported devices.

Everything talks to the gateway over your local network. No AT&T account, no
cloud.

## What you get

One device, "AT&T Gateway", with these entities. All of the sensors are read
from pages the gateway serves without a login, so they work even before
you have entered an access code, and a wrong code never blanks them.

| Entity | Type | What it is |
|---|---|---|
| Reboot | button | Logs in to the gateway and submits its own restart form. |
| Uptime | sensor | Seconds since the gateway last booted. Resets to near zero after a reboot, which is how you can tell one worked. |
| WAN IP address | sensor | The public IPv4 address on the broadband side. |
| Line rate | sensor | The broadband link speed in Mbit/s. |
| Downstream data, Upstream data | sensor | IPv4 byte counters, shown in GB. They reset when the gateway reboots. |
| Receive errors, Transmit errors | sensor | IPv4 error counters. |
| Reachable | binary sensor | On when the gateway answered the last poll. Stays available while everything else is unavailable, so the fault is visible. |
| Internet connection | binary sensor | On when the gateway reports its broadband link up. Deliberately separate from Reachable: a gateway can answer perfectly while its upstream is down. |

Uptime, the WAN address, the line rate and all of the counters are diagnostic
entities; Reboot and Internet connection are the ones for a dashboard.

### Actions

| Action | Does | Fields |
|---|---|---|
| `att_router_reboot.reboot` | Reboots the gateway now, the same way the button does. | None. The integration manages one gateway, so there is nothing to target. |

The action is registered when Home Assistant starts, so an automation that
calls it while the integration is not loaded gets a clear "not loaded" error
rather than an unknown-action error.

## Supported devices

| Gateway | Firmware | Status |
|---|---|---|
| BGW320-500 | 6.35.8 | Verified: the parser and the login are built against pages recorded from this unit. |
| BGW320-505 | any | Same web interface. No report from one as of 2026-09-16; open an issue if you run it. |
| BGW210-700 | any | Same web interface family (`sysinfo.ha`, `broadbandstatistics.ha`, `restart.ha`). No report from one as of 2026-09-16. |

The gateway must serve its web interface over HTTPS on its LAN address, which
every BGW does by default. A field the parser does not recognise reads as
unknown rather than as a wrong number.

## Use cases

- Reboot the gateway from a dashboard button instead of walking to it.
- Reboot it on a schedule (nightly, or one night a week) without writing an
  automation, with a guard against rebooting a gateway that has only just come
  up.
- Reboot it automatically when the internet connection has been down for a
  while, from an automation on the Internet connection sensor.
- Know when the public IP address changes, and when the gateway rebooted on
  its own.

## Requirements

- Home Assistant 2026.3 or newer. (The integration's own icon is served by
  Home Assistant from that release on; the code needs 2025.3.)
- An AT&T gateway reachable on your LAN, usually at `192.168.1.254`. Home
  Assistant must be able to reach that address - on a segmented network, put
  Home Assistant where it can route to the gateway.
- The device access code printed on the gateway's label. This is what its web
  interface logs in with. It is needed for the reboot, not for the statistics.

## Installation

1. Copy `custom_components/att_router_reboot` into your Home Assistant
   `custom_components` directory, or add this repository to HACS as a custom
   repository and install it from there.
2. Restart Home Assistant.
3. Settings -> Devices & services -> Add integration -> "AT&T Router Reboot".
4. Enter the gateway address and the device access code. The integration logs
   in before it saves anything, so a wrong code is caught here.
5. Open the integration's Configure to set an automatic reboot schedule. This
   step is optional.

Only one gateway can be added to a Home Assistant instance.

### Discovery

There is none, and there cannot be. Add the gateway by address. Measured on
a BGW320-500 in AT&T IP passthrough mode on 2026-09-05, the gateway answers no
SSDP search (`ssdp:all`, `upnp:rootdevice` and both InternetGatewayDevice
targets were tried from two hosts that reach it, one of them over a route
pinned to the WAN interface), serves no UPnP description on port 1900, 49152,
5000 or 80, and announces nothing over mDNS. Its web interface has no UPnP
settings at all. It is also the LAN's DHCP server rather than a client, so it
never sends the DHCP request Home Assistant's DHCP discovery listens for.

### Installation parameters

| Field | Default | What it is |
|---|---|---|
| Host | `192.168.1.254` | The gateway's LAN address. |
| Device access code | none, required | The code on the gateway's label. Stored in the config entry, never logged, redacted from diagnostics. |
| Verify the gateway's certificate | off | The gateway ships a self-signed certificate on its LAN address, so leave this off unless you have installed your own trusted certificate on it. |

### Configuration parameters

Settings -> Devices & services -> AT&T Router Reboot -> Configure.

| Option | Default | What it is |
|---|---|---|
| Schedule | Off | `Off`, `Daily` or `Weekly`. Off leaves rebooting entirely to the button, the action and your own automations. |
| Time of day | 04:00:00 | Local time at which a scheduled reboot runs. Ignored when the schedule is off. |
| Day of week | Sunday | Used only by a weekly schedule. |

A scheduled reboot is skipped when the gateway has been up for less than 30
minutes. That stops a schedule firing right after a manual reboot, or a gateway
stuck in a restart loop, from power-cycling the one device the house depends on
for internet. The skip is logged at info.

A failed scheduled reboot raises a repair notice under Settings -> System ->
Repairs, because nobody is watching a timer fire at four in the morning. The
notice names the error, says what to check, and clears itself the next time a
scheduled reboot succeeds. A rejected access code raises a re-authentication
prompt instead.

### Reconfiguring

Settings -> Devices & services -> AT&T Router Reboot -> the three dots ->
Reconfigure changes the access code or the certificate check. Leave the access
code blank to keep the stored one; the stored code is never shown. The address
must still answer as the same gateway: if you move the gateway to a new
address, delete the entry and add it again.

If a reboot is refused because the access code has changed, the integration
starts a re-authentication flow and Home Assistant asks for the new code.

### Removing it

Settings -> Devices & services -> AT&T Router Reboot -> the three dots ->
Delete. That removes the entry, its device and every entity. Nothing is written
to the gateway, so there is nothing to undo on it. To remove the code as well,
delete `custom_components/att_router_reboot` (or uninstall it in HACS) and
restart Home Assistant.

## How it updates

- Statistics are polled every two minutes from `sysinfo.ha` and
  `broadbandstatistics.ha`, which the gateway serves without authentication.
  Model, serial, firmware and MAC are read once when the entry loads. If the
  broadband page cannot be read, the last statistics are kept and uptime is
  still updated. If the uptime page cannot be read, everything but Reachable
  becomes unavailable and the log says so once.
- Reboot happens only when asked: the button, the action or the schedule. It
  logs in the way the gateway's own web page does. The access code is hashed
  (`md5(code + nonce)`) against a per-request nonce, over a session of its own
  that keeps the gateway's cookie. It then replays the gateway's own restart
  form rather than posting a hardcoded body. If a firmware update renames a
  form field, replaying still submits the right thing. A refresh is requested
  straight after, so Uptime shows the reset within a poll or two of the gateway
  coming back.

## Examples

Reboot the gateway when the internet has been down for ten minutes, but only
if it has been up long enough that this is not a loop:

```yaml
automation:
  - alias: Reboot the gateway when the internet stays down
    triggers:
      - trigger: state
        entity_id: binary_sensor.at_t_gateway_internet_connection
        to: "off"
        for: "00:10:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.at_t_gateway_uptime
        above: 1800
    actions:
      - action: button.press
        target:
          entity_id: button.at_t_gateway_reboot
```

Reboot every Sunday at 04:00 with the action instead of the built-in schedule,
for people who want it alongside other steps:

```yaml
automation:
  - alias: Weekly gateway reboot
    triggers:
      - trigger: time
        at: "04:00:00"
    conditions:
      - condition: time
        weekday: [sun]
    actions:
      - action: att_router_reboot.reboot
```

Say when the public address changes:

```yaml
automation:
  - alias: Public IP changed
    triggers:
      - trigger: state
        entity_id: sensor.at_t_gateway_wan_ip_address
    conditions:
      - "{{ trigger.from_state.state not in ['unknown', 'unavailable'] }}"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "The public IP is now {{ trigger.to_state.state }}."
```

## Known limitations

- Only reboot, uptime and broadband statistics are implemented. The gateway
  exposes far more (NAT tables, per-port LAN counters, fibre diagnostics); this
  integration is scoped to fixing and watching a gateway, not managing one.
- The reboot response is expected to drop as the gateway restarts; that is
  treated as success. If a reboot silently fails, the Uptime sensor is the
  place it shows - it will not reset.
- One gateway per Home Assistant instance, and the entry cannot follow the
  gateway to a new address; delete and re-add it.
- Verified only against BGW320-500 / 6.35.8. Other models render the same pages
  with small differences; the parser degrades to "unknown" on a field it does
  not recognise rather than reporting a wrong number.
- No discovery, and none is possible: the gateway offers no SSDP, no UPnP and
  no mDNS, and it is a DHCP server rather than a DHCP client. See Discovery
  above for what was measured. Add it by address.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Setup says "Could not reach the gateway at that address" | Home Assistant cannot route to the gateway, or the address is wrong. Open `https://<address>/` from the Home Assistant host's network; the BGW answers on 443 only. |
| Setup says "The access code was rejected" | The code is the **Device Access Code** on the gateway's label, not the Wi-Fi password. If you changed it in the gateway's web interface, use the new one. |
| Setup says "Unexpected error talking to the gateway" | The gateway answered with a page the integration did not expect; the log has the detail. The usual one is its "please enable cookies" page, meaning the session cookie is not round-tripping. This integration keeps cookies for the gateway's IP address on purpose, so that page means the firmware has changed. Report the log line. |
| Setup fails with the certificate check on | The gateway's certificate is self-signed. Turn the check off unless you installed your own trusted certificate on the gateway. |
| Everything is unavailable except Reachable, which is off | The gateway is not answering. The log has one line saying so and one when it recovers. |
| Internet connection is off but the sensors update | The gateway is up and its upstream is down. This is the case the Reboot button is for. |
| The Reboot button did nothing; Uptime did not reset | Look for "reboot returned HTTP" or "still on the login form" in the log. The first means the gateway refused the form; the second means the login did not stick and a reauth prompt has been raised. |
| The action says the integration is not loaded | The config entry is disabled, failed to set up or is still retrying. Its card under Devices & services says why. |
| A scheduled reboot did not happen | The gateway had been up for less than 30 minutes, logged at info as skipped, or the weekly schedule's day did not match. An attempt that failed raises a repair notice carrying the error. |

For more detail:

```yaml
logger:
  logs:
    custom_components.att_router_reboot: debug
```

Download diagnostics from the device page for a report with the access code,
host, serial, MAC and public IP address redacted.

## Development

- `parse.py`, `models.py` and `api.py` have no Home Assistant import, so
  `tests/test_parse.py` and `tests/test_api.py` run on a bare interpreter
  against saved real HTML (`tests/fixtures/`, with the household's WAN IP, MAC
  and serial replaced by documentation placeholders) and against aiohttp's
  real cookie jar.
- The Home Assistant layer is under `tests/ha/` and runs in the GitHub Tests
  workflow on every push, alongside `mypy --strict` with Home Assistant
  installed, hassfest and the HACS action.
- Coverage is measured over both suites into one file (the pure suite with
  `--cov`, then `tests/ha` with `--cov-append`) and the run fails below 95%.
  Measuring only the Home Assistant suite understates it, because those tests
  mock the client the pure suite exercises.
- `pyproject.toml` loads `tests/winposix.py` with `-p tests.winposix`, which
  runs the suite on a Windows workstation. Every function in it returns
  immediately off Windows, so Linux and CI read the same suite.
- `python tools/validate_local.py` runs the offline checks (manifest,
  translations, actions, icons, exception keys, the quality scale against the
  pinned rule list) before a push. It also fails on a development host named
  anywhere in the published tree, not only in `manifest.json`;
  `tools/_netblocks.py` pins the address space it refuses, and
  `ATT_ROUTER_DEV_HOSTNAMES` gives it the host names to refuse as well.
- `python tools/make_brand.py` regenerates the brand images.

## Quality scale

Built to Home Assistant's Integration Quality Scale, rule by rule, in
`custom_components/att_router_reboot/quality_scale.yaml`. Every rule is
listed; no rule is `todo`. `discovery` and `discovery-update-info` are `exempt`
on the measurement under Discovery - the rule allows it for a device that
cannot be discovered. The badge itself is only awarded to core integrations, so
the manifest claims no tier.

`CHANGELOG.md` records what changed in each version.

## License

MIT. Copyright (c) 2026 Lewis Heidrick. Full text in [LICENSE](LICENSE).

The captured gateway page at `tests/fixtures/restart_login.html` keeps its
vendor's BSD-licensed md5.js. [NOTICE](NOTICE) names it.
