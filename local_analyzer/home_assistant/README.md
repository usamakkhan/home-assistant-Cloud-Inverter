# SolarMax Local Cloud Connector for Home Assistant

This is the **second application**. It is deliberately separate from the
SolarMax Local Cloud replacement in the project root:

1. **SolarMax Local Cloud** (`app.py`) talks to the inverter once, owns the
   historical analyzer/dashboard and caches telemetry.
2. **SolarMax Local Cloud Connector** (this folder) runs inside Home Assistant,
   reads only the first application's HTTP cache, and creates HA entities.

The connector contains no Modbus client and cannot scan, configure or write to
the inverter.

The recommended architecture is:

`Inverter Wi-Fi module → SolarMax Local Cloud → cached /api/ha → HA Connector`

This prevents Home Assistant and the browser dashboard from opening competing
Modbus sessions to the rate-sensitive ESP bridge. The analyzer performs one
safe read cycle and both the local GUI and Home Assistant consume its cache.

## Before you start

- Keep the analyzer running on a computer that can reach the inverter over your
  LAN. Home Assistant must be able to reach that computer on TCP port `8765`.
- Find the inverter's LAN IP and the analyzer computer's LAN IP. Replace
  `INVERTER_LAN_IP` and `ANALYZER_LAN_IP` below with those two different values.
  The `192.168.50.x` addresses in the sample files are examples.
- The analyzer itself runs on the other computer. Home Assistant can use the
  **Cloud Inverter** integration's Local analyzer option or the standalone
  connector in this folder. Choose one to avoid duplicate entities.

## 1. Run the analyzer as a LAN service

On the separate always-on Windows/Linux computer containing the local-cloud
application, run:

```powershell
python app.py --no-browser --bind 0.0.0.0 --monitor-interval 180 --monitor-mode cooperative --monitor-host INVERTER_LAN_IP
```

Run the command from the extracted `SolarMax-local-analyzer` folder. Keep the
terminal open or configure the command as a service after verifying it works.
The computer must have a stable LAN address. Restrict inbound TCP 8765 in its
firewall to the Home Assistant host and trusted administration devices. Never
forward port 8765 or inverter port 502 from the router to the internet.

Verify from another LAN device or from the Home Assistant host in a browser:

```text
http://ANALYZER_LAN_IP:8765/api/config
http://ANALYZER_LAN_IP:8765/api/ha
```

`/api/config` should return JSON. `/api/ha` should show the cached readings after
the first successful inverter capture. With the 180-second Cooperative target,
allow a few minutes; cloud quiet windows can extend the gap. Missing readings
remain missing instead of being replaced with sample values. Leave inverter
controls disabled when adding the connector; its setup checks for read-only mode.

## 2. Add it through the Cloud Inverter integration (recommended)

If you installed **Cloud Inverter** through HACS or copied
`custom_components/cloud_inverter` into Home Assistant, restart Home Assistant,
then open **Settings → Devices & services → Add integration**. Search for
**Cloud Inverter**, choose **Local analyzer**, and enter
`ANALYZER_LAN_IP` in **Host** and `8765` in **Port**. Port `8765` is the default;
change it if you started the analyzer with another `--port` value. Keep the
default 180-second cache scan interval or choose another value. No
CloudInverter.net username or password is required. Enter only the host in its
field, without `http://` or `/api/ha`. After setup, check the new device's
sensors after the first successful analyzer capture. You can change the host,
port, or Home Assistant cache scan interval later under the integration's
**Configure/Options** menu.
To change the inverter collection target, use the analyzer dashboard's
collection controls; its preset is 180 seconds.

## 3. Standalone connector (alternative)

1. Open Home Assistant's `/config` directory using its file editor, Samba share,
   SSH, or another file transfer method. Create `custom_components` if needed.
2. Copy the entire `home_assistant/custom_components/solarmax_pv9000` folder
   from this package into `/config/custom_components/solarmax_pv9000`.
   Check that `/config/custom_components/solarmax_pv9000/manifest.json` exists;
   do not add an extra `custom_components` directory level.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration** and search for
   **SolarMax Local Cloud Connector**.
5. Enter the analyzer URL in the form `http://ANALYZER_LAN_IP:8765` (no
   `/api/ha` suffix and no `0.0.0.0`). Keep the default scan interval at
   **180 seconds**, then submit the form.
6. Open the new SolarMax device in **Settings → Devices & services** and check
   that its sensors show readings after the first successful capture.

The HTTP scan reads the analyzer cache and does not trigger another inverter
request. Cooperative collection targets a new local sample every 180 seconds,
with longer gaps possible around cloud quiet windows. Ten-second direct
collection can stop CloudInverter uploads and turn the datalogger indicator red
on the reported installation.

The integration uses a config entry and a data-update coordinator. It creates
47 local entities covering PV1/PV2, grid, battery, Backup, GEN, Normal Load,
voltage, current, frequency, temperature, operating mode, daily energy and
lifetime energy. It is strictly read-only and exposes no switches, numbers or
inverter configuration entities.

For the Home Assistant Energy Dashboard, use:

- **Solar production:** Solar energy total
- **Grid consumption:** Grid imported energy total
- **Return to grid:** Grid exported energy total
- **Battery energy in:** Battery charged energy total
- **Battery energy out:** Battery discharged energy total

Copy `lovelace_dashboard.yaml` into a new raw-configuration dashboard if you
want the supplied starting layout. Home Assistant may choose slightly different
entity IDs; select the generated entities in the card editor if needed.

## Troubleshooting

- **Integration not listed:** Check the `manifest.json` path above, restart
  Home Assistant, then search again.
- **Cannot connect during setup:** Open `/api/config` from the Home Assistant
  network. Check the analyzer process, LAN IP, firewall rule for TCP `8765`, and
  that the URL uses `http://` with no API suffix. The setup also requires the
  analyzer to report read-only mode, so start it without inverter controls.
- **Entities unavailable or blank:** Check `/api/ha` and the analyzer's
  collection status. Confirm the inverter IP and Modbus/TCP access, then wait
  for a successful collection cycle. Home Assistant only reads cached results.
- **Cloud uploads stop or datalogger turns red:** Return the analyzer to
  Original/cloud-only mode, then try Cooperative mode at 180 seconds. Avoid
  10-second direct polling on the reported installation.

## 4. REST fallback

If you do not want a custom component, replace `ANALYZER_IP` in
`solarmax_rest_package.yaml`, place it under `/config/packages`, enable packages
from `configuration.yaml`, then restart Home Assistant:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

The REST form creates fewer entities but still uses one HTTP request for the
shared cached payload. Values are not rounded in either method.

## Sign conventions

- Grid power above zero means import; below zero means feed-in/export.
- Battery power below zero means charging; above zero means discharging.
- Backup Load is the essential/light battery-backed circuit.
- GEN is the high-power circuit for AC, heater and water geyser; its outage
  availability depends on the configured battery threshold.
- Normal Load is grid-only and currently unused.

## Configuration control

Do not expose inverter settings as Home Assistant switches yet. The analyzer
has read-back mappings for 16 candidate controls, but Modbus writes, bounds,
read-after-write verification and rollback are not implemented. Incorrect
battery, off-grid voltage/frequency or power-limit writes can de-energize
circuits or damage equipment.
