# Changelog

## v1.5.5 — Solar Touch — 2026-10-09

- Add separate instantaneous battery charging and discharging power sensors for
  direct inverter LAN, splitting the signed local battery reading (negative is
  charging). Missing or invalid readings remain unavailable.
- Label existing cloud battery power sensors as instantaneous without changing
  their unique IDs. Label direct solar power and signed battery power likewise.
- Keep power readings in W with `device_class: power` and `state_class:
  measurement`; battery state of charge in `%` with `device_class: battery` and
  `state_class: measurement`; and cumulative energy counters in kWh or Wh with
  `device_class: energy` and `state_class: total_increasing`.
- Clarify Energy dashboard setup when a disabled direct entry leaves a stale
  solar source reference. The license remains PolyForm Strict.

## v1.5.4 — Solar Touch — 2026-10-09

This release consolidates the changes made since [Cloud Inverter
v1.2.0](https://github.com/usamakkhan/home-assistant-Solar-Touch/releases/tag/v1.2.0).
The v1.5.0–v1.5.3 releases were withdrawn from the official release list;
their changes are included here. The installed Home Assistant integration
continues to use the `cloud_inverter` domain and directory, so existing entries,
entity IDs, dashboards, and automations do not need to be recreated.

### Solar Touch name and distribution

- Rename the Home Assistant and HACS display name, setup screen, new entry and
  device names, documentation, and GitHub repository to **Solar Touch**. Existing
  automatically generated entry titles are updated; custom titles remain.
- Keep **CloudInverter.net** as the vendor service name in the cloud setup choice
  and cloud API messages. Update repository, issue, installation, badge, and
  icon links to the Solar Touch repository.
- Bundle integration icon/logo assets and provide detailed HACS, manual
  installation, Energy dashboard, upgrade, and troubleshooting instructions.

### Direct inverter LAN collection

- Add read-only SolarMax/Senergy PV9000/ONYX Modbus/TCP collection **inside Home
  Assistant**. It requires no cloud account or separate analyzer process.
- Present two setup choices: **Get Data Locally using Inverter IP** (default)
  and **CloudInverter.net**. Retire the old standalone analyzer and its cached
  HTTP source. Old analyzer entries must be removed and replaced with a direct
  inverter LAN entry; they lack the inverter IP needed for automatic migration.
- Provide separate inverter IP, Modbus/TCP port (default `502`), unit ID
  (default `1`), and collection interval (default `180` seconds) fields. The
  direct interval is editable from `10–900` seconds in Options.
- Before saving a direct entry, probe read-only register `0x1001` and show the
  IP, port, unit ID, and response for confirmation. Recheck direct connection
  settings when they change in Options.
- Keep valid local measurements when an optional register block fails, record
  incomplete captures, and delay polling near estimated cloud upload windows.
  A short interval can still interrupt the datalogger's cloud uploads.

### Cloud polling and Home Assistant sensors

- Set CloudInverter.net API polling to `300` seconds by default, matching the
  approximately five-minute upload cadence reported for this installation.
  The interval remains editable from `30–900` seconds; saved choices persist.
- Give each cloud inverter its own sensor unique IDs. Migrate older registry
  records in place to preserve existing entity IDs and dashboard references.
- Use a Home Assistant managed HTTP session. Treat empty API responses as failed
  refreshes so setup retries or entities become unavailable until a successful
  poll; keep device identity tied to the selected inverter.
- Keep numeric portal readings numeric even when formatted with separators.
  Missing or invalid readings become unavailable rather than corrupting Home
  Assistant statistics or being reported as false zero battery power.
- Skip unnecessary entity state updates when a cloud snapshot has not changed.
- Add **Instantaneous Power Import** and **Instantaneous Power Export** (W) from
  signed Grid Power: positive means import, negative means export. Retain the
  original signed Grid Power sensor. Rename the existing PV Power display to
  **Instantaneous Solar Production** without changing its unique ID.
- Mark daily energy sensors as `total_increasing` so Home Assistant handles
  their reset. Document which lifetime kWh counters to select in the Energy
  dashboard; live power sensors in W are for instantaneous dashboards.

### License and validation

- License the current release under **PolyForm Strict 1.0.0**. Earlier copies
  distributed under MIT retain the permissions granted to those recipients;
  removing their official release listings cannot revoke those permissions.
- The integration tests pass. HACS validation currently fails its license
  identification check because GitHub reports PolyForm Strict as `NOASSERTION`.
  Manual installation remains documented.

## v1.2.0 — Cloud Inverter — 2026-10-09

- Generate fresh CloudInverter.net API signatures for requests and distinguish
  authentication failure from an account with no inverter groups.
- Add an editable Home Assistant refresh interval and installation and
  troubleshooting documentation with sample device identifiers.
