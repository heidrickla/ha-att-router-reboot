# Changelog

All notable changes to this integration are recorded here, newest first. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The newest version below is the version in `manifest.json` and in
`const.VERSION`. HACS installs the tagged release rather than the default
branch.

## [0.2.1] - 2026-09-16

### Changed

- `hacs.json` declares `"country": ["US"]`. The integration works only against
  an AT&T residential gateway, and AT&T sells that service only in the United
  States, so HACS's include rules require the key.
- The licence moves from GPL-3.0-or-later to MIT, decided by Lewis on
  2026-09-15 for all five Home Assistant repositories. No file here derives
  from a GPL-licensed work. `NOTICE` names the one third-party file, a captured
  gateway page carrying BSD-licensed md5.js, which keeps its own licence.
- `tools/validate_local.py` fails, rather than notes, when `documentation` or
  `issue_tracker` in `manifest.json` points at a private, loopback,
  link-local or reserved address, at `localhost`, at a `.local`, `.lan` or
  `.internal` name, or at a bare hostname. It also requires `country` in
  `hacs.json`.
- Diagnostics redact the config entry's options with the same key set as its
  data.

## [0.2.0] - 2026-09-05

### Changed

- `discovery` and `discovery-update-info` in `quality_scale.yaml` move from
  `todo` to `exempt`. The gateway was measured on 2026-09-05: in AT&T IP
  passthrough mode it answers no SSDP search from either of two hosts that
  reach it, serves no UPnP description on port 1900, 49152, 5000 or 80,
  announces nothing over mDNS, and its web interface carries no UPnP settings
  at all. The rule exempts a device that cannot be discovered, which this one
  cannot.
- README gains a Discovery section saying the gateway is added by address and
  why nothing can find it, and its Known limitations and Quality scale sections
  now match.
- The version in `manifest.json` and `const.VERSION` moves to 0.2.0, the first
  version carrying a git tag and a GitHub release.

## [0.1.0] - 2026-09-04

First working version. Everything below happened on the day the integration was
written and reviewed against the Integration Quality Scale.

### Added

- Reboot an AT&T BGW-series residential gateway from a button, from the
  `att_router_reboot.reboot` action, or on an optional built-in off / daily /
  weekly schedule. A scheduled reboot is skipped when the gateway has been up
  for less than 30 minutes, so a schedule cannot power-cycle the house's
  internet in a loop.
- Sensors read without a login: uptime, WAN IPv4 address, line rate, the IPv4
  byte counters (shown in GB) and the IPv4 error counters, plus Reachable and
  Internet connection binary sensors. Reachable stays available while the rest
  go unavailable, so the fault itself is visible.
- A repair notice when a scheduled reboot fails, because nobody is watching
  a timer fire. It names the error, says what to check, and clears itself the
  next time a scheduled reboot succeeds. A rejected access code raises a
  re-authentication prompt instead.
- Re-authentication: a rejected access code from the button, the action or the
  schedule asks for the new code rather than only failing.
- A reconfigure flow for the address, the access code and the certificate
  check. Leaving the access code blank keeps the stored one.
- Downloadable diagnostics, with the access code, host, serial, MAC and the
  public WAN IPv4 address redacted.
- Brand icon and logo shipped in `custom_components/att_router_reboot/brand/`,
  which Home Assistant serves for a custom integration from 2026.3.
- README sections for supported devices, use cases, every installation and
  configuration parameter with its default, reconfiguring, removal, the update
  cadence, three example automations and troubleshooting.
- `tools/validate_local.py`, an offline stand-in for hassfest and the HACS
  action plus the cross-file checks nothing else makes, including the quality
  scale against a pinned list of all 54 rules and against the mechanisms it
  claims. `tools/make_brand.py` regenerates the brand images.
- A GitHub `Tests` workflow that runs ruff, both test suites, `mypy --strict`
  with Home Assistant installed, the offline validator, hassfest and the HACS
  action on every push, with nothing allowed to fail quietly. Coverage is
  measured across both suites and the run fails below 95%.

### Changed

- Minimum Home Assistant is 2026.3.0 (`hacs.json`). The code needs 2025.3
  for `AddConfigEntryEntitiesCallback`; 2026.3 is the release that serves the
  in-repo brand images.
- The access code is a masked password field in the setup, reconfigure and
  re-authentication forms, and is never sent back to the browser as a default
  or a suggested value.
- Icons come from the device class wherever one supplies an icon. `icons.json`
  now covers only the WAN address, the two byte counters (deliberately
  directional, overriding the generic `data_size` icon) and the error counters.
- Setup and poll failures carry translation keys, so the integration card shows
  a real reason instead of an f-string.
- `quality_scale.yaml` states each rule as it stands, with a written reason on
  every exemption and on the two rules then still `todo` (both `exempt`
  since 2026-09-05, see 0.2.0).

### Fixed

- The reboot could not work at all. aiohttp's default cookie jar discards
  cookies set by an IP-address host, and the gateway is addressed by IP, so its
  `SessionID` never came back and the gateway served its "enable cookies" stub.
  Both sessions now come from `async_create_clientsession` with
  `cookie_jar=CookieJar(unsafe=True)`.
- The setup form accepted any access code. A login now has to produce the
  authenticated restart form; the cookies stub and a re-served login form both
  fail.
- The public WAN IPv4 address was not redacted from diagnostics: the redaction
  helper walks mappings, and the poll data is a dataclass. It is converted with
  `dataclasses.asdict` first.
- The reconfigure form pre-filled the stored access code as clear text.
- The reconfigure description claimed a gateway at a new address would be added
  as a new entry, which `single_config_entry` forbids. It now says to delete the
  entry and add the gateway again, as the README does.
- An SSL context was built on the event loop during setup and validation. The
  session's connector carries Home Assistant's context instead.
- `async_setup` had no `CONFIG_SCHEMA`, which hassfest warns about.

### Removed

- The `entry_id` field on the `att_router_reboot.reboot` action. It was accepted
  and ignored; the integration allows one entry, so the action takes no fields.

### Known limitations

- No discovery. `discovery` and `discovery-update-info` were filed `todo`
  pending a measurement from a host on the gateway's LAN. Superseded on
  2026-09-05: the measurement was taken and both rules are now `exempt`, see
  the entry above.
