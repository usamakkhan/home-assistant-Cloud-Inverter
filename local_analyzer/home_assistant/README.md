# Use the SolarMax local analyzer with Home Assistant

The [installation guide](../../INSTALL.md) covers downloading the repository,
installing the main integration, starting the analyzer, and connecting it to
Home Assistant step by step.

The analyzer runs on a computer that can reach the inverter's LAN Modbus/TCP
bridge. Home Assistant reads the analyzer's cached `/api/ha` response over
HTTP. The dashboard and Home Assistant share one primary collector; adding a
Home Assistant integration does **not** create another inverter connection.

```text
PV9000 Wi-Fi bridge --Modbus/TCP--> local_analyzer/app.py
                                      |-- dashboard and SQLite history
                                      +-- cached /api/ha --> Home Assistant
```

There are three current ways to use local readings with Home Assistant:

1. **Cloud Inverter integration → Direct inverter LAN**: Home Assistant reads
   the PV9000 bridge itself. No separate analyzer process is needed; see the
   [direct installation steps](../../INSTALL.md#2b-connect-directly-from-home-assistant).
2. **Standalone SolarMax Local Cloud Connector**: the
   `custom_components/solarmax_pv9000` directory in this folder. It asks for
   the analyzer's full base URL and a cache scan interval.
3. **REST package**: `solarmax_rest_package.yaml` creates a smaller set of
   sensors without a custom integration.

Choose **one** option per inverter so the same readings do not appear twice
or create two local Modbus readers.
The cloud-login source of the main Cloud Inverter integration is a separate
choice and does not use this analyzer.
Existing Cloud Inverter **Local analyzer** entries remain supported, but that
choice is no longer offered when adding a new Cloud Inverter entry.

## 1. Start the analyzer

From the `local_analyzer` directory on an always-on computer, replace
`INVERTER_LAN_IP` with your inverter Wi-Fi bridge's address:

```shell
python app.py --no-browser --bind 0.0.0.0 --port 8765 --no-peer-api --monitor-host INVERTER_LAN_IP --monitor-interval 180 --monitor-mode cooperative
```

Python 3.11 or newer is needed for the analyzer. The command starts a
Cooperative local collector with a 180-second target and exposes the cached
HTTP API on port `8765`. `--no-peer-api` avoids opening the optional neighbor
comparison port; omit it if you use the comparison service.

To use another analyzer HTTP port, change `--port`, for example:

```shell
python app.py --no-browser --bind 0.0.0.0 --port 9000 --no-peer-api --monitor-host INVERTER_LAN_IP --monitor-interval 180 --monitor-mode cooperative
```

Then enter `http://ANALYZER_LAN_IP:9000` in the standalone connector.
Existing main-integration analyzer entries can change Port to 9000 in
**Options**. The inverter's
Modbus/TCP port is a separate service, normally `502`; do not enter `502` as
the analyzer HTTP port.

The analyzer binds to `127.0.0.1` if `--bind` is omitted. Use
`--bind 0.0.0.0` only when Home Assistant is on another computer and the LAN
firewall restricts access to trusted clients. The HTTP API has no general
login; some endpoints can change collection mode or start diagnostics.
Do not forward the analyzer or inverter ports from your router.

The analyzer starts in Original/cloud-only mode if no `--monitor-interval` is
given. In that mode it does not perform automatic inverter captures and
`/api/ha` returns HTTP 503 until a real sample exists. The sample addresses
in the source are placeholders; set your own inverter and analyzer LAN
addresses locally.

## 2. Verify reachability

From a device on the same network as Home Assistant, open:

```text
http://ANALYZER_LAN_IP:8765/api/config
http://ANALYZER_LAN_IP:8765/api/ha
```

Use your chosen port in both URLs. `/api/config` should return analyzer
metadata and collector status. `/api/ha` returns the latest cached snapshot
after a successful capture; HTTP 503 before then is expected. Cooperative
quiet windows and capture time can make the first wait longer than three
minutes.

`0.0.0.0` is a bind address, **not** the Host or URL to enter in Home
Assistant. Use the analyzer computer's reachable LAN IP or hostname.

## 3. Existing Cloud Inverter analyzer entries

Entries created with the earlier **Local analyzer** choice continue reading
the analyzer's cached `/api/ha` endpoint. Their **Options** menu can still
change analyzer Host, HTTP Port, and Home Assistant cache scan interval.
The cache scan does not change the analyzer's inverter collection target.
For a new analyzer connection, use the standalone connector below.

## 4. Standalone connector for new installations

The standalone connector has its own domain and is separate from the main
Cloud Inverter integration:

1. Copy this folder's `custom_components/solarmax_pv9000` into
   `/config/custom_components/solarmax_pv9000`. Verify that
   `/config/custom_components/solarmax_pv9000/manifest.json` exists.
2. Restart Home Assistant, add **SolarMax Local Cloud Connector**, and enter
   the **full base URL**, such as `http://ANALYZER_LAN_IP:8765`. Do not append
   `/api/ha`.
3. Keep its 180-second default cache interval or choose 10–300 seconds.

This connector defines 47 sensor descriptions for PV/MPPT, grid, battery,
Backup, GEN, Normal Load, operating mode, and energy counters. Availability
depends on the analyzer payload; a missing value is not made into a zero.
Its setup expects the analyzer to report read-only mode, so start the
analyzer without `--enable-inverter-controls` when using this alternative.

## 5. REST package alternative

Replace `ANALYZER_IP` in `solarmax_rest_package.yaml` with the analyzer
computer's IP or hostname and adjust the port if needed. Copy the file to
`/config/packages/solarmax_rest_package.yaml`. If packages are not already
enabled, add this to `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Restart Home Assistant. The REST package uses a 180-second HTTP scan and
creates fewer entities than the custom integrations. It does not contact the
inverter directly.

## Energy Dashboard and sample Lovelace view

The local integrations expose named lifetime energy sensors for solar
generation, grid import/export, and battery charge/discharge where the
analyzer can provide them. In Home Assistant's Energy Dashboard, select the
generated entities by their actual names and verify units and increasing
totals before using them for statistics. Entity IDs are assigned by Home
Assistant and may differ from examples.

`lovelace_dashboard.yaml` is a starter dashboard. It contains example
`sensor.*` IDs that may need to be replaced with IDs from your installation.
The same applies to any automations you create from these sensors.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Integration not shown | Confirm its `manifest.json` is directly under the expected `/config/custom_components/DOMAIN` directory, then restart Home Assistant. |
| Cannot connect during setup | Test `/api/config` from the Home Assistant network; check the analyzer process, firewall, Host, and Port. |
| Entry loads but sensors are unavailable | Check `/api/ha`. Confirm a real inverter capture succeeded and the collector is not in Original mode. |
| Wrong or stale values | Compare the analyzer's captured timestamp, collector status, and stored history. Home Assistant cache scans do not force a fresh inverter read. |
| Cloud uploads stop or datalogger turns red | Restore Original/cloud-only mode, then try Cooperative collection at 180 seconds. Avoid a 10-second direct inverter target on the reported setup. |

The analyzer database and exported readings can contain device identifiers
and energy-use patterns. Keep them local and replace account IDs or serials
with `ABCDE123456789` in shared diagnostics.

## Sign conventions and control scope

For the local mapped measurements, positive grid power means import and
negative means export. Negative battery power means charging; positive
means discharging. Backup, GEN, and Normal Load are model-dependent
circuits, not universally fixed household appliances.

Both Home Assistant integrations and the REST package are sensor-only.
They do not expose inverter-setting writes. The analyzer has a separate
experimental physical-control path, disabled by default and deliberately
guarded with a placeholder serial in this public copy. Do not treat a
dashboard control candidate as a validated write for another inverter.
