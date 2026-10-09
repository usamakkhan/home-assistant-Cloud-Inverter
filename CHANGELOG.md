# Changelog

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
