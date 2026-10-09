# Changelog

## 1.4.0 — 2026-10-09

- Remove the former standalone analyzer application, its companion Home
  Assistant connector, and the legacy cached HTTP source from this repository.
- Keep direct inverter LAN collection inside Home Assistant as the local
  setup choice. Existing direct and cloud entries continue to work.
- Older Local analyzer entries require manual replacement with a direct LAN
  entry because they do not contain the inverter's LAN IP. Review old entity
  IDs in dashboards and automations after replacement.
- Simplify source specific code, translations, and installation instructions.

## 1.3.5 — 2026-10-09

- Change the default CloudInverter.net API refresh from 30 to 300 seconds to
  match the approximately five-minute inverter upload cadence reported for
  this installation. Keep the editable cloud range at 30–900 seconds.
- Preserve any refresh interval already saved in an entry's Options.
- Clarify the distinction between inverter uploads and Home Assistant API
  requests in the README and installation guide.

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
- Keep direct LAN collection as the local setup choice.
- Update setup and installation documentation to match the two-choice flow.

## 1.3.2 — 2026-10-09

- Display the existing integration icon in the repository README.
- Document when Home Assistant can show bundled integration brand images.

## 1.3.1 — 2026-10-09

- Keep valid local sensors available when one optional PV9000 register block
  cannot be read, while marking that capture as incomplete.
- Add a configurable Modbus unit ID to direct Home Assistant setup and
  Options. The default remains 1, with existing device identities preserved.
- Make direct LAN collection the default setup choice.
- Add regression tests and restore push/PR validation in GitHub Actions.
- Add the MIT license and package existing icon and logo artwork in the
  integration's `brand/` directory for Home Assistant and HACS validation.

## 1.3.0 — 2026-10-09

- Add **Direct inverter LAN** collection inside Home Assistant using the
  read-only SolarMax PV9000 Modbus profile and sensor mapping.
- Add separate inverter IP and Modbus/TCP port fields (default 502), plus an
  editable collection interval (default 180 seconds).
- Delay captures around heuristic cloud upload windows and document the
  limits of this precaution.
- Add direct setup instructions and capture tests using sample LAN data.

## 1.2.0 — 2026-10-09

- Generate fresh CloudInverter.net API signatures for requests and report
  authentication failures separately from accounts with no inverter groups.
- Add editable Home Assistant refresh intervals and detailed installation
  and troubleshooting documentation using sample device identifiers.
