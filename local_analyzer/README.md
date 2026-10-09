# SolarMax PV9000 local analyzer

For the complete Home Assistant installation sequence, start with the
[installation guide](../INSTALL.md).

Version `0.12.0` of this standalone Python application reads a supported
SolarMax/Senergy PV9000 inverter through its LAN Modbus/TCP bridge, stores
captures locally, and serves a dashboard plus a cached Home Assistant feed.
It does not require a CloudInverter.net login. It is separate from the
repository's Home Assistant integration and must keep running for local
Home Assistant sensors to update.

This code was developed around the `SM-ONYX-UL-6KW` / PV9000 family. The
113-entry profile combines documented and locally investigated mappings;
another model or firmware can return fewer valid measurements. The repository
contains sample addresses and `ABCDE123456789` instead of a personal serial.
No sample measurement is substituted for a missing live reading.

## Quick start

Python 3.11 or newer is required. The analyzer itself uses the Python standard
library; Home Assistant has its own dependencies. Run commands from this
`local_analyzer` directory.

```shell
python app.py
```

Open `http://127.0.0.1:8765`. The dashboard binds to localhost by default.
Starting with no monitor flags selects **Original/cloud-only** mode: automatic
local inverter reads are off. Enter your actual inverter LAN address before
enabling collection; `192.168.50.10` in the files is only a sample.

To start Cooperative collection with a three-minute target:

```shell
python app.py --no-browser --monitor-host INVERTER_LAN_IP --monitor-interval 180 --monitor-mode cooperative
```

For Home Assistant on another LAN host, expose the dashboard on a trusted
interface and keep the same collection target:

```shell
python app.py --no-browser --bind 0.0.0.0 --port 8765 --monitor-host INVERTER_LAN_IP --monitor-interval 180 --monitor-mode cooperative
```

`0.0.0.0` is a listen address, not the address to enter in Home Assistant. Use
the analyzer computer's LAN IP or hostname there. The dashboard HTTP server
does not provide user authentication. Some API requests can change collection
mode or start diagnostic reads. Restrict the dashboard port to trusted LAN
clients with a firewall and do not forward ports `8765` or `502` to the
internet. The optional peer API uses port `8767` by default and should be
restricted too.

See the [Home Assistant guide](home_assistant/README.md) for installation,
Host/Port fields, and the cached-data architecture.

## Collection modes and timing

| Mode | Behavior |
| --- | --- |
| Original/cloud-only | No automatic local inverter reads; startup default unless `--monitor-interval` is set. |
| Cooperative | Direct local reads with quiet windows around the expected cloud cycle. Recommended when retaining cloud delivery matters. |
| Local | Direct local reads without cloud quiet windows. It can compete with the datalogger's cloud session. |
| Maintenance | Automatic collection off; enables explicit diagnostics and the separately guarded settings workflow. |

The interval field in the dashboard and `--monitor-interval` command target
the time between starts of inverter captures. Valid dashboard values are
10–900 seconds; the preset is **180 seconds**. Cooperative quiet windows,
capture duration, or failures can make the actual gap longer. Two consecutive
capture failures return the primary collector to Original mode. Mode changes
made in the dashboard are not persisted across process restarts.

You *can* set a 10-second target. On the reported installation, frequent
direct polling at 10 seconds stopped CloudInverter uploads and made the
datalogger indicator red. This is an observation from that setup, not a
guarantee for every device. Use Cooperative mode and a longer target if the
cloud feed matters.

The **Home Assistant cache scan** is a separate interval. Its default is also
180 seconds, but changing it only changes how often Home Assistant reads
`/api/ha`. It does not change the inverter collector's interval or create
another Modbus connection.

Useful startup flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--bind` | `127.0.0.1` | HTTP listen address; use `0.0.0.0` only on a trusted LAN. |
| `--port` | `8765` | Dashboard and cached API port. |
| `--monitor-host` | Sample `192.168.50.10` | Inverter Wi-Fi bridge IP; replace with your own. |
| `--monitor-interval` | `0` (collection off) | Start background collection at the given target; use `180` for the recommended three-minute target. |
| `--monitor-mode` | `cooperative` when monitoring is enabled | Cooperative or direct Local mode at startup. |
| `--cloud-quiet-window` | `45` seconds | Pause before and after the expected five-minute cloud boundary; accepted range 30–90. |
| `--peer-api-port` | `8767` | Independent comparison API listener. |
| `--no-peer-api` | Off | Do not start the comparison API. |
| `--no-browser` | Off | Do not open a browser on startup. |
| `--enable-inverter-controls` | Off | Opt in to experimental, guarded physical setting writes. |

The two HTTP listener ports must differ.

## Dashboard and measurements

The dashboard includes Overview, Power Flow, Analytics, System comparison,
Cloud accuracy, Telemetry, Measurements, Acquisition log, Fault words,
Inverter settings, Device tools, Security, Register explorer, and Home
Assistant pages. It presents the latest cached snapshot, time series,
activity, raw register evidence, and selected exports.

The known profile performs serialized read-only Modbus function-03 captures.
It includes PV/MPPT, grid, battery, load, GEN-port, operating mode, identity,
and diagnostic fields where supported. Capability filtering avoids claiming
that unused MPPT or phase channels are real measurements. A measured zero
remains zero; missing or unsupported values remain unavailable. Validate
uncertain field meanings against the inverter display and changing operating
conditions before relying on them.

Power-flow paths, source/destination balance, and animations are visual
interpretations of measured or derived values. They do not represent a
verified wiring diagram or prove that every load path is directly measured.
The Cloud accuracy page accepts manually supplied cloud reference readings
and compares them with a local snapshot using timestamps and per-field
deltas; it does not log in to the vendor API.

The Device, Security, and Register explorer pages provide bounded diagnostic
reads and exports. A discovery scan is rate-limited to one request per
second. The security view records selected port and read-only Modbus
observations; it is not a penetration test or proof that every documented
write is supported. Keep the inverter's Modbus port on a trusted LAN.

## Stored data and HTTP API

Successful primary snapshots and acquisition events are stored in
`data/telemetry.sqlite3` using SQLite/WAL. The data directory is created
locally when the app runs and is not part of the sanitized repository.
Treat live database files and exported JSON/CSV as private: they can contain
timestamps, device identifiers, and energy behavior.

The main HTTP server exposes, among others:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/config` | Version, collector state, sensor count, and feature information. |
| `GET /api/collector` | Current mode, target interval, next capture, and health. |
| `GET /api/ha` | Latest cached Home Assistant payload; returns HTTP 503 before the first capture. |
| `GET /api/history` | Stored time series for the requested window. |
| `GET /api/activity` | Acquisition events and errors. |
| `GET /api/latest` | Latest full snapshot and comparison structure. |

The dashboard also uses POST endpoints for explicit capture, collector mode,
and diagnostics. Physical setting endpoints have additional same-origin
local-browser checks. Home Assistant's integrations use only cached GET
requests. There is no password on the general dashboard/API, so network
restriction matters even when physical controls are disabled.

## Optional Knox neighbor comparison

The process normally starts a second HTTP API on `127.0.0.1:8767` (or the
address selected with `--bind`). `python knox_api.py` can instead run that API
as a separate process; do not start both on the same port. The comparison
page and `/v1` API keep peer telemetry and alert data in separate SQLite
files under `data/`.

The neighbor collector is configured for an EyeBond reverse-callback/PI18
path, using a UDP trigger and a returned TCP session. Its target host starts
unset; no neighbor device is contacted until configured and probed. The peer
collection target is preset to 180 seconds once configured. The example
array sizes in `solarmax_analyzer/peer.py` (12 × 585 W primary and 10 × 585 W
neighbor) are sample assumptions for W/panel and W/kWp comparisons. Correct
them for your arrays before interpreting comparative performance. The
underperformance alert starts disabled and needs calibration.

Freshness-alert defaults in `solarmax_analyzer/alerts.py` are 45 seconds,
which is shorter than the 180-second collection preset. Review those rules
for your cadence to avoid nuisance stale alerts. The peer decoder and
comparison are experimental; a configured endpoint alone is not proof of
protocol compatibility. The peer API's `/openapi.json` describes its
available routes.

## Physical settings and safeguards

Normal telemetry and Home Assistant sensors do not write inverter registers.
With `--enable-inverter-controls`, the analyzer contains an experimental
workflow for two reviewed function-06 settings: work mode and grid charging.
It requires an explicit local editing session, checks the current device
identity and old value, and reads back the result. It does not provide a
general write-register API or automatic rollback.

The published source deliberately uses placeholder serial
`ABCDE123456789` in the control guard and UI. It is not configured for an
actual inverter's physical writes. The write path has mocked/protocol tests,
not a physical-device acceptance test. Other battery, GEN, and schedule
controls remain locked.

## Verification and limitations

Run the analyzer tests from this directory:

```shell
python -m unittest discover -s tests -v
node --test tests/test_dashboard_ui.cjs
```

Node.js is needed only for the dashboard JavaScript test.
Some Python tests start loopback HTTP listeners, so a sandbox that denies
local sockets cannot run the entire suite. These tests do not establish
compatibility with an untested inverter or firmware. Check the actual
Modbus response, sample timestamp, and Home Assistant availability on your
own trusted LAN before using the measurements for automation.
