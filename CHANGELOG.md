# Changelog

## 1.5.0 — 2026-10-09

- License this release under the **PolyForm Strict License 1.0.0**. The new
  terms permit noncommercial use but do not permit redistribution or modified
  versions without separate permission from the copyright holder.
- Update README license information and badge. Earlier releases under MIT
  retain their original terms; this change does not alter those grants.
- No integration behavior or existing Home Assistant entity IDs change.

## 1.4.3 — 2026-10-09

- Give each CloudInverter.net inverter its own sensor unique IDs, so multiple
  configured inverters can register their full sensor sets. Migrate existing
  cloud sensor registry records in place to preserve entity IDs, names, and
  dashboard references.
- Use Home Assistant's managed HTTP session for cloud requests.
- Mark an individual cloud sensor unavailable when its reading is missing or
  invalid, while leaving other sensors from the same update available.

## 1.4.2 — 2026-10-09

- Keep cloud energy and other numeric sensors numeric when the portal returns
  a formatted number, and leave missing or invalid readings without a numeric
  state instead of sending text into Home Assistant statistics.
- Mark direct LAN daily energy counters as `total_increasing`, so Home
  Assistant treats the daily reset as a new meter cycle.
- Document which lifetime counters belong in the Energy dashboard and how to
  troubleshoot a missing sensor in its selectors. Existing entity IDs remain
  the same.

## 1.4.1 — 2026-10-09

- Use a verified absolute public URL for the README icon so it renders in
  HACS's repository details view as well as on GitHub.
- Make other README links absolute so they also work inside HACS.

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

Consolidated changes originally published throughout the 1.3 series:

- Add read-only SolarMax/Senergy PV9000 direct Modbus/TCP collection **inside
  Home Assistant**, with local sensor mapping and no cloud login.
- Offer two new setup choices: **Get Data Locally using Inverter IP** and
  **CloudInverter.net**. Direct LAN is the default choice.
- Provide separate inverter IP, Modbus/TCP port (default `502`), unit ID
  (default `1`), and collection interval (default `180` seconds) fields.
- Test the direct IP, port, and unit ID with read-only register `0x1001`
  before creating an entry. Show the result on a confirmation screen and
  repeat the check when direct connection settings change in Options.
- Continue collecting valid local readings if an optional register block
  fails, while recording that the capture is incomplete. Delay captures
  around estimated cloud upload windows as a precaution.
- Change the default CloudInverter.net API refresh to `300` seconds to match
  the approximately five-minute inverter upload period reported on this
  installation. The cloud interval remains editable from `30–900` seconds;
  any explicitly saved interval remains in effect.
- Add the MIT license, bundled brand artwork, regression tests, GitHub
  validation, and detailed setup and troubleshooting guidance.

This is a historical release. Version 1.4.0 later removed the separate
standalone analyzer and its legacy cached HTTP source; new installations
should use the latest 1.4.x release.

## 1.2.0 — 2026-10-09

- Generate fresh CloudInverter.net API signatures for requests and report
  authentication failures separately from accounts with no inverter groups.
- Add editable Home Assistant refresh intervals and detailed installation
  and troubleshooting documentation using sample device identifiers.
