# SolarMax PV9000 Analyzer

A local CloudInverter-style portal and investigation tool for the SolarMax
PV9000 Wi-Fi module, with a separate Home Assistant cache connector.

Telemetry uses read-only FC03 commands. Physical changes remain off until a
local editing session is acknowledged; v0.10 supports reviewed FC06 work-mode and grid-charge
changes. It currently supports:

- device/network reachability and TCP port checks;
- raw Modbus/TCP holding-register reads (function `03`);
- bounded, rate-limited discovery scans;
- 113 documented or cloud-validated SolarMax Onyx/Senergy real-time fields using efficient block reads;
- decoded operating mode and four diagnostic/error bitfields;
- device identity and safe configuration reads that explicitly exclude the Wi-Fi password;
- a non-invasive vulnerability audit covering selected exposed services,
  unauthenticated/plaintext Modbus evidence, documented control and credential
  risks, and prioritized mitigations;
- interpretation of returned words as unsigned/signed integers, hexadecimal,
  ASCII, and 32-bit values;
- JSON export of all observations for comparison and reverse engineering.
- a polished multi-view local-cloud dashboard with Overview, Analytics,
  Accuracy, Telemetry, Device, Security, Explorer and Home Assistant workspaces;
- automatic five-second cached UI updates with a 180-second start-to-start
  Local collection preset, capture-duration and missed-cadence reporting;
- durable SQLite/WAL storage of every exact full snapshot and acquisition event,
  restored automatically after an application restart;
- exact decoded display precision by default, with optional display-only rounding;
- animated source/destination balance charts and a selectable 15-minute to
  24-hour local SVG history graph;
- animated directional Solar/Grid/Battery/Backup/GEN/Normal energy flow;
- automatic flow placement: grid import and battery discharge are sources;
  grid export and battery charging are destinations. Confirmed-zero nodes and
  connections disappear from the diagram and remain in its quiet zero-value
  strip. Unknown readings stay visible; display rounding never hides a flow;
- compact flow columns with restrained, color-matched directional particles
  and position transitions. Motion is illustrative, only runs for fresh
  readings, can be switched off, and respects reduced-motion preferences;
- a practical workspace layout with grouped monitoring/engineering navigation,
  a compact collection drawer, power cards and a battery/system summary;
- dedicated bookmarkable pages using `/?page=overview`, `/?page=powerflow`,
  `/?page=analytics`, `/?page=telemetry`, `/?page=controls`, and the other sidebar
  destinations. Navigation uses real links with normal Back/new-tab behavior.
  Existing hash bookmarks still work; all pages share the same local collector;
- a full-page detailed power schematic with separate MPPT readouts, voltage and
  signed current, battery SOC, directional particle streams, and an isolated
  grid-only Normal Load path. The source sum is calculated, not measured
  inverter output; paths are logical, not an installation wiring diagram;
- a signed-power table alternative to the flow diagram, plus a cache-only
  Refresh dashboard action separate from Capture inverter;
- searchable telemetry with group and non-zero/unknown filters, preserved
  expanded groups during refresh, and exact filtered CSV export;
- power/battery/solar chart presets and CSV export of the selected series and
  time window; missing values stay blank and display rounding is not exported;
- graph crosshair, highlighted series points, and an exact-value floating
  tooltip on hover or tap; keyboard arrows inspect samples, Home/End jump,
  and Escape dismisses the tooltip;
- honest chart gaps for missing values and acquisition intervals longer than
  the greater of 3 minutes or 2.5 times the configured polling interval;
  unknown readings stay unknown, and incomplete balances never show proportions;
- shared sample-health, sample-age and running-app/read-only indicators;
  failed cache refreshes retain previous readings but stop flow animations;
- a five-second-refreshing acquisition log with background/manual source,
  success or error state, duration, field count, and key power values;
- cached `/api/ha`, `/api/history`, and `/api/activity` feeds plus a Home Assistant custom
  integration, REST fallback package, and Lovelace starter dashboard;
- timestamp-aware comparison against manually supplied CloudInverter values;
- a compact single-phase view with measured zero and capability-derived
  not-applicable channels retained in a side reference rail;
- a read-back inventory of 194 portal/protocol settings, with only the two
  individually validated changes exposed inside an acknowledged editing session.
- a separate Knox neighbor service on port `8767`, its own SQLite telemetry and
  alert stores, a protocol-neutral ingest contract, and an OpenAPI document;
- a dedicated Solar fleet comparison page with exact synchronized hover,
  raw W, W/panel, W/kWp and DC-nameplate-utilization views using configured
  panel counts and nameplate ratings;
- persistent freshness, raw-fault and opt-in sustained-performance alert states.
  Comparative performance starts in calibration mode and is suppressed when
  samples are missing or light is below the configured floor.

## Example network details

- Wi-Fi module: `192.168.50.10`
- MAC address example: `AA-BB-CC-DD-EE-FF`
- Open service: TCP `502`
- The example module uses a cloud service and may contact it periodically.
- A read of holding register `0` receives Modbus exception `02` (illegal data
  address), confirming a functioning Modbus/TCP endpoint.

## Run

For Home Assistant setup, including the analyzer startup command, integration
copy path, URL, verification, and troubleshooting, see
[`home_assistant/README.md`](home_assistant/README.md).

Python 3.11 or newer is sufficient; there are no third-party dependencies.
The addresses and serial in this package are examples. Set your own inverter LAN
address before enabling collection; no live telemetry is filled in with sample
measurements. The physical-control serial guard is intentionally a placeholder
(`ABCDE123456789`) in this shared copy, so reviewed setting uploads require
local configuration before use.

```powershell
python app.py
```

Open <http://127.0.0.1:8765>. The app binds to localhost only.
Use `python app.py --no-browser` when running it as a background process.
The same command also starts the independent Knox API at
<http://127.0.0.1:8767/v1>. Use `--no-peer-api` only when that listener is not
wanted, or run `python knox_api.py` as a standalone service.

To enable local collection at the recommended three-minute target, enter your
inverter's LAN address and use Cooperative mode:

```powershell
python app.py --no-browser --monitor-interval 180 --monitor-mode cooperative --monitor-host INVERTER_LAN_IP
```

Run the automated tests with:

```powershell
python -m unittest discover -s tests -v
```

## Safe investigation workflow

1. Use **Connection check**.
2. Capture a **Known PV9000 live profile** snapshot.
3. Export the snapshot JSON after each run.
4. Capture again while values visibly change (PV production, household
   load, battery charge), then compare exports. Correlated changing words are
   candidates for measurements.
5. Only rely on values after they have been validated against the
inverter display or vendor app.

The known profile was identified from the Senergy/APD Modbus v1.2 map and
validated locally: model `SM-ONYX-UL-6KW`, 230 V / 50 Hz / 6000 W ratings, and
coherent live PV, grid, backup/load, and battery readings. Serial numbers are
visible only in raw single-register reads and are not shown in the dashboard.

Version 0.4 capability detection reports two physical MPPTs and exposes the
applicable fields from the 113-field combined protocol/cloud-validated map
without mislabeling register ranges reused by other models. It also decodes
inverter mode and four diagnostic bitfields. Cloud comparison identified
`0x2002` as the raw BMS status and validated the multifunction GEN-port block
at `0x136A`-`0x137D` (voltage, current, power, frequency, daily energy, and
total energy). The port may be generator input, smart-load output, or
AC-coupled inverter input depending on configuration. Seven non-zero words
remain intentionally unlabelled pending corroboration: `0x1026`, `0x1036`,
`0x104A`, plus `0x1365`, `0x1366`, `0x1367`, and `0x1369`. The latter four
form three likely 32-bit fields in the model extension at `0x1364`-`0x1369`,
but their semantics are not assigned from plausible values alone.

Version 0.5 adds a CloudInverter-aligned presentation and comparison layer.
Cloud reference values are entered in the local UI as canonical numeric units
(W, V, A, Hz, %, °C and kWh), either field-by-field or as JSON/key-value text.
The analyzer then captures local Modbus data and reports per-field deltas,
tolerances and timestamps. A cloud reference more than 90 seconds from the
local capture is marked stale because household power can change faster than
CloudInverter's update cycle.

This installation is treated as single-phase with two MPPTs. L2/L3 voltage,
current and power values are verified as zero and moved to the side reference
rail; unavailable MPPT3-MPPT9 channels are shown as capability-derived virtual
zeros without reading model-reused register ranges. The firmware mirrors the
common AC frequency into the unused L2/L3 frequency words, so those two words
are labeled as protocol mirrors rather than falsely reported as extra phases.

Installation-specific load meanings are:

- **Backup Load:** essential/light whole-house circuits that remain battery
  backed during an outage;
- **GEN smart load:** the high-power circuit for AC, heater and water geyser;
  during an outage, the circuit’s availability is governed by the configured
  battery threshold;
- **Normal Load:** grid-only, not battery backed, and currently unused.

The remote-settings workspace inventories 194 portal fields, schedule groups,
and documented protocol parameters. Off-grid start SOC is NOT
assumed to control GEN; Capacity Mode is SOC-versus-voltage battery management,
not output voltage/frequency. See [control research and safeguards](CONTROL_RESEARCH.md).

Version 0.10 uses a dark energy-console interface with luminous flow paths,
branch tracing, quick navigation and focus mode. Rounding remains off by default;
all movement is presentation-only and never interpolates a measured number.

## Knox neighbor comparison (v0.12)

Open `/?page=systems` to configure and inspect the second array. The following
panel sizes are examples; replace them with your own installation settings:

- **My SolarMax:** 12 × 585 W = 7,020 Wp (7.02 kWp)
- **Neighbor Knox:** 10 × 585 W = 5,850 Wp (5.85 kWp)

The example logger at `192.168.50.40` is an EyeBond reverse-callback
client, not a Modbus/TCP server. The app listens locally on TCP `8899`, sends one
unicast callback trigger to UDP `58899`, then issues PI18 read commands over the
outbound logger session. Live identification returned collector PN
`ABCDE123456789`, logger firmware `3.5.1.3`, hardware `3.0.0.0`, protocol `PI18`,
and the inverter's 6 kW rating. Fast cycles read GS telemetry plus operating mode
and can record local samples at a configured interval.

No inverter write or durable logger-setting function is used. The logger's saved
cloud host (`ess.eybond.com`) is read and left unchanged. Local mode can still
briefly occupy the logger's single TCP session, so uninterrupted simultaneous
cloud delivery is not claimed. Select **Original/cloud** on the Systems page to
stop every local callback request; select **Local** to resume collection.
The Senergy/APD SolarMax register and control maps are never reused for Knox.

The API is a separate HTTP listener with a versioned contract:

```text
GET  http://127.0.0.1:8767/v1/status
GET  http://127.0.0.1:8767/v1/systems
GET  http://127.0.0.1:8767/v1/systems/{primary|neighbor}/latest
GET  http://127.0.0.1:8767/v1/systems/{primary|neighbor}/history?minutes=60
GET  http://127.0.0.1:8767/v1/comparison?minutes=60
GET  http://127.0.0.1:8767/v1/alerts
GET  http://127.0.0.1:8767/v1/alerts/events
GET  http://127.0.0.1:8767/v1/rules
GET  http://127.0.0.1:8767/v1/config
GET  http://127.0.0.1:8767/openapi.json
POST http://127.0.0.1:8767/v1/admin/config
POST http://127.0.0.1:8767/v1/admin/probe
POST http://127.0.0.1:8767/v1/admin/ingest
POST http://127.0.0.1:8767/v1/admin/rules
```

Admin endpoints accept only local clients with JSON and reject unapproved browser
origins. The ingest endpoint is for the local protocol-analysis adapter once it
has evidence; unknown fields remain absent/null, exact zero remains zero, and
NaN/infinity are rejected. Neighbor samples are written to
`data/telemetry-neighbor.sqlite3`; configuration and deduplicated alert
transitions are written to `data/peer-state.sqlite3`. The existing SolarMax
history stays in `data/telemetry.sqlite3`. The standalone API opens that primary
journal in enforced read-only mode.

Comparison uses a one-to-one, maximum-cardinality/minimum-total-skew match within
15 seconds and never interpolates. Aligned samples and actually comparable
samples are counted separately. Raw power is shown, but fair performance uses
W/kWp (and W/panel) because the arrays differ in size. Roof orientation, tilt,
shade, temperature, soiling and curtailment can still explain a sustained
difference, so the peer underperformance alert is disabled until explicitly
calibrated.

Each neighbor sample is bound to the saved host identity and a durable target
generation. Changing the target invalidates earlier probe evidence,
hides the former target's telemetry, and resets only neighbor alert timers.
Repeated copies of the same capture are idempotent. Device capture time remains
available for graph alignment while server receipt time is trusted for stream
freshness; captures more than five minutes in the future are rejected.

## Opt-in physical controls (experimental)

### Collection modes (v0.11)

The mode selector is visible on every dashboard page. Choose a mode, check the
inverter-access acknowledgement, then press **Apply mode**:

- **Local / direct Modbus collection:** periodic local telemetry without the
  Cooperative mode's quiet windows. Interval is a 10–900 second start-to-start
  target (180 seconds by default); if a read takes too long, the missed deadline is reported and no
  overlapping or burst capture is started. Feeds the dashboard and the separate HA cache; no cloud
  login is needed. Does not reroute DNS or disable the Wi-Fi module's cloud
  configuration, but may interfere with SolarTouch uploads.
- **Cooperative / scheduled cloud pauses:** the same local collector with
  heuristic quiet windows around the cloud cycle. These pauses can make the
  actual interval longer than 180 seconds.
- **Original / cloud only:** local collection off; requires no acknowledgement
  to restore. Does not undo physical settings or cancel an in-flight request.
- **Maintenance / manual tools:** no automatic collector; explicit diagnostic
  reads and separately guarded control operations are available.

Every successful sample is appended to `data/telemetry.sqlite3`, including the
full decoded snapshot; chart and HA state are restored from that journal after
a restart. Local and Cooperative modes fall back to Original after two consecutive capture
failures. Local mode does not unlock inverter-setting writes. Startup still
defaults to Original; changing this option in the web UI is deliberate, not
automatic or persistent across a restart.

### Setting uploads

Open `http://127.0.0.1:8765` and use Remote settings → Read current settings.
The read temporarily reserves the shared connection and resumes Local collection
automatically; Maintenance mode is no longer required for read-back. To change
**work mode** or **Charge by Grid**, acknowledge **Start editing session**. The
app pauses collection, enables only those two candidates, and restores the prior
collection mode when the session ends. Select **one** change → Review changes →
confirm → Upload. Each review expires after 90 seconds. Device model and serial
must match this installation, the old value must remain unchanged, and read-back
must match the requested value. Controls work only through a same-origin local
browser, not the LAN HA connection. An uncertain response is never retried.

These commands have automated mock/protocol tests, **not a physical-device write
test**. They change energy behavior. Check backup requirements before changing
work mode. Battery limits, GEN thresholds and schedules remain locked. There is
no automatic rollback: an uncertain result requires inspecting actual state,
not sending another blind command. A reversal is a new reviewed change.
The last 100 upload attempts are held in memory and exportable from Remote
settings; they do not survive a server restart.

Restore Original stops future local collection and blocks controls; it does
**not** undo an already applied setting or cancel an in-flight Modbus frame.

Version 0.7 introduced the multi-view monitoring interface and animated directional
energy flow and balance visuals, selectable PV/grid/battery/Backup/GEN/Normal/SOC
graph series with exact-value hover inspection, a live acquisition log, and Home
Assistant support. The local CloudInverter replacement and HA connector remain
two separate applications: only this application contacts Modbus; the connector
reads its cached `/api/ha` endpoint. For an always-on HA feed, start this app
with `--bind 0.0.0.0`; see `home_assistant/README.md` for
the separately installable connector. Keep the analyzer LAN-only.

Version 0.10 retains the fail-safe datalogger control plane. The server always starts
in **Original / cloud-only** mode unless cooperative polling is explicitly
enabled. Original mode makes no connection to the inverter and can be restored
immediately from the Overview page. Cooperative mode uses one Modbus/TCP
session per full capture and reserves
a configurable quiet window before and after every observed five-minute vendor
cloud boundary. Two consecutive capture failures automatically return the app
to Original mode. **Maintenance** mode disables background polling and unlocks
manual diagnostics only after explicit confirmation.

The recommended startup setting is `--monitor-interval 180 --monitor-mode cooperative`.
You can set `--monitor-interval 10 --monitor-mode local`, but on the reported
installation a ten-second direct polling interval stopped CloudInverter uploads
and turned the datalogger indicator red. Use a longer interval if cloud delivery
is needed. Cooperative quiet windows can extend the three-minute target.
Frequent polling can still affect SolarTouch;
the app reports overruns and returns to Original after repeated failures.

The safe configuration view additionally reads firmware, hybrid work mode,
time schedule, battery and charge/discharge limits, inverter clock, RS485
configuration, and external meter/CT configuration. It never requests the
documented Wi-Fi password register at `0x3070`.

The vulnerability audit is intentionally evidence-preserving and safe. It
checks 13 selected TCP ports at a low rate and sends one function-03 model read.
It does not read the documented SSID/password blocks, send any write function,
guess credentials, stress the module, intercept cloud traffic, or claim that
untested write/credential risks are confirmed. Export the audit JSON to retain
the exact raw request and response frame.

The scanner is deliberately capped and rate-limited to one request per second.
During the initial investigation the ESP bridge temporarily stopped replying
after a burst of short-lived connections, even though port 502 remained open.
Avoid faster sustained polling until its stability and connection behavior are
understood. Modbus/TCP has no authentication, so keep TCP port 502 confined to
the trusted LAN and never forward it from the router to the internet.

## Cloud traffic capture limitation

A normal computer on a switched network cannot passively see traffic sent by a
different Wi-Fi client. Packet capture must run on the router/access point, on
the AdGuard host if it is also the gateway, or through a managed-switch mirror
port. DNS logs reveal the destination name and timing but not the telemetry
payload. Do not use ARP spoofing for this investigation.
