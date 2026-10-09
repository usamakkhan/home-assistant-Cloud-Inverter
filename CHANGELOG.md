# Changelog

## 1.3.4 — 2026-10-09

- Rename the direct setup choice to **Get Data Locally using Inverter IP**.
- Before saving a direct entry, test the configured IP, TCP port, and Modbus
  unit ID with a read-only PV9000 register request. Show the response in a
  separate confirmation step.
- Use the same Modbus check when changing direct connection settings in
  Options, and explain test failures in the setup form.

## 1.3.3 — 2026-10-09

- Simplify new Cloud Inverter setup to two choices: **Direct inverter LAN**
  and **CloudInverter.net**.
- Keep existing Local analyzer config entries and their Options working.
  New installations that need the separate analyzer dashboard can use its
  standalone Home Assistant connector or REST package.
- Update setup and installation documentation to match the two-choice flow.

## 1.3.2 — 2026-10-09

- Display the existing integration icon in the repository README.
- Include a favicon for the separate local analyzer dashboard.
- Document when Home Assistant can show bundled integration brand images.

## 1.3.1 — 2026-10-09

- Keep valid local sensors available when one optional PV9000 register block
  cannot be read, while marking that capture as incomplete.
- Allow the separate analyzer's Home Assistant cache to remain available
  through normal cooperative quiet windows; stale or undated samples still
  become unavailable.
- Add a configurable Modbus unit ID to direct Home Assistant setup and
  Options. The default remains 1, with existing device identities preserved.
- Make direct LAN collection the default setup choice.
- Add regression tests and restore push/PR validation in GitHub Actions.
- Add the MIT license and package existing icon and logo artwork in the
  integration's `brand/` directory for Home Assistant and HACS validation.

## 1.3.0 — 2026-10-09

- Add **Direct inverter LAN** as a third Cloud Inverter source. Home
  Assistant runs the read-only SolarMax PV9000 Modbus capture and sensor
  mapping itself, without a separate analyzer process.
- Add separate inverter IP and Modbus/TCP port fields (default 502), plus an
  editable collection interval (default 180 seconds).
- Delay captures around heuristic cloud upload windows and document the
  limits of this precaution. Keep the separate analyzer option for its
  dashboard and history.
- Add direct setup instructions and capture tests using sample LAN data.

## 1.2.0 — 2026-10-09

- Generate fresh CloudInverter.net API signatures for requests and report
  authentication failures separately from accounts with no inverter groups.
- Add a local analyzer source to the Cloud Inverter Home Assistant integration.
  It reads the analyzer's cached LAN endpoint without another inverter
  connection or cloud credentials.
- Add editable Home Assistant refresh intervals. The local source defaults to
  180 seconds; cloud refresh defaults to 30 seconds.
- Give the local source separate Host and Port settings. Port defaults to
  8765 and can be changed during setup or in Options.
- Add the SolarMax PV9000 local analyzer and its Home Assistant alternatives.
  Inverter collection is off by default; Cooperative collection has a
  recommended 180-second target.
- Add detailed installation, operation, and troubleshooting documentation.
  Examples use sample addresses and serials instead of personal device data.

The local analyzer is a separate application. Its own version is currently
0.12.0.
