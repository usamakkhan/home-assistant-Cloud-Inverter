# Cloud Inverter for Home Assistant

<img src="custom_components/cloud_inverter/brand/icon.png" alt="Cloud Inverter solar panel icon" width="112">

A Home Assistant sensor integration with two setup choices:

**New installation?** Follow the [detailed installation guide](INSTALL.md)
for HACS or manual setup, cloud login, and direct LAN collection.
See the [changelog](CHANGELOG.md) for release changes.
The repository is available under the [MIT License](LICENSE).

| Source | Where readings come from | Credentials | Default Home Assistant refresh |
| --- | --- | --- | --- |
| CloudInverter.net | The vendor's HTTPS API | CloudInverter username and password | 30 seconds |
| Get Data Locally using Inverter IP | Home Assistant reads the SolarMax PV9000 Modbus/TCP bridge itself | No cloud login or separate analyzer | 180 seconds |

Choose a source when adding the integration. Existing **Local analyzer**
config entries continue to work, but new setup offers the direct LAN choice
instead of requiring a separate analyzer process.

**Get Data Locally using Inverter IP** runs the read-only PV9000 capture inside Home
Assistant. Enter the inverter's LAN IP, Modbus/TCP port (default 502), and
Modbus unit ID (default 1).
The integration spaces captures at 180 seconds by default and avoids
heuristic cloud upload windows. It requires Home Assistant to reach the
inverter directly. The separate analyzer remains available if you want its
dashboard and history.

## What is included

- `custom_components/cloud_inverter/`: the Home Assistant integration. Its cloud
  path defines 58 sensor descriptions, and its local path defines 47. A sensor
  can be unavailable when its source has no corresponding measurement.
- `local_analyzer/`: a standalone Python dashboard and collector for the
  SolarMax PV9000 family. It is a separate application, not something HACS runs
  inside Home Assistant.
- [Home Assistant local setup guide](local_analyzer/home_assistant/README.md):
  LAN commands, integration steps, a standalone connector alternative, and a
  REST package.

The integration ships [icon and logo assets](custom_components/cloud_inverter/brand)
in its `brand/` directory. Home Assistant 2026.3 and newer can display these
directly ([Home Assistant brand image documentation](https://developers.home-assistant.io/docs/core/integration/brand_images/));
older Home Assistant versions may show a generic integration icon.

Sensor coverage includes PV and MPPT readings, grid import/export, battery
state and energy, load circuits, and inverter status. The local feed additionally
exposes the analyzer's mapped PV9000 measurements. Availability depends on the
device, firmware, portal response, and successful captures. Home Assistant
assigns entity IDs when entities are created; do not assume a fixed
`sensor.*` ID from this README.

## Install the Home Assistant integration

### HACS

Add `https://github.com/usamakkhan/home-assistant-Cloud-Inverter` as a custom
**Integration** repository in HACS, install **Cloud Inverter**, and restart Home
Assistant. Follow HACS's current custom-repository controls if its menu labels
differ from those shown on your system.

### Manual

Copy the repository's `custom_components/cloud_inverter` directory to
`/config/custom_components/cloud_inverter`, including its `manifest.json` and
translations. Restart Home Assistant. The full directory tree must have only
one `custom_components` level.

## Add a cloud source

1. In Home Assistant, open **Settings → Devices & services → Add integration**.
2. Search for **Cloud Inverter** and choose **CloudInverter.net**.
3. Enter the account username and password. If the account has one inverter,
   setup selects it automatically; if it has several, choose one from the list.
4. Check the created device and sensor states after the first update.

The integration signs each API request from its current fields. The username
and password are stored in Home Assistant's config entry; the session token is
held in memory. Protect Home Assistant backups and do not post credentials,
tokens, cookies, or unredacted logs in issues.

The cloud coordinator defaults to a 30-second Home Assistant refresh. Its
**Options** form permits 30–900 seconds. A refresh asks the vendor API for data;
the API may update the underlying inverter reading on a different schedule.
Only the SolarMax/Senergy portal response shapes represented in the code have
been implemented. Other device models are not guaranteed to expose all fields.

## Add the direct LAN source

Choose **Get Data Locally using Inverter IP** in the setup form and follow the
[direct setup steps](INSTALL.md#2b-connect-directly-from-home-assistant).
Enter the inverter IP, port, and unit ID. Setup checks a read-only Modbus
register and shows the result before you confirm the entry. Collection then
runs within Home Assistant at a default 180-second interval.

The [separate analyzer](local_analyzer/README.md) remains available as an
optional dashboard and history application. To connect it to Home Assistant
for a new installation, use its [standalone connector or REST package](local_analyzer/home_assistant/README.md).
Existing Cloud Inverter **Local analyzer** entries retain their cached HTTP
behavior and Options form. Use only one local collector per inverter to avoid
duplicate readings.

The source files use sample LAN addresses and `ABCDE123456789` in place of a
real serial. Replace the sample host locally; no fake measurement is supplied
before a real capture.

## Sensor behavior and limits

- The integration creates sensor entities only. It does not expose Home
  Assistant switches or number entities for inverter settings.
- Missing, empty, or unsupported readings are not assumed to be zero. Cloud
  and local sources have different field sets and may show different sensor
  names.
- Local values are served from the analyzer's latest durable snapshot. If it
  has never captured a sample, `/api/ha` returns HTTP 503 and setup/update may
  report the analyzer unavailable.
- The local analyzer can retain an older cached sample. Check its capture time
  and collector status when freshness matters.
- The cloud path depends on the vendor API and internet access. A working
  website login does not by itself prove every API endpoint is healthy.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Integration not listed | Confirm `/config/custom_components/cloud_inverter/manifest.json` exists, then restart Home Assistant. |
| Cloud login rejected | Verify credentials and vendor availability. If the website works, report only the sanitized API status/code from logs; remove account IDs, serials, passwords, and tokens. |
| Local setup cannot connect | From the Home Assistant network, open `http://HOST:PORT/api/config`. Check analyzer process, Host, Port, and firewall. `0.0.0.0` is a bind address, not the Host to enter. |
| Direct setup cannot connect | Check that Home Assistant can reach the inverter's LAN IP and Modbus/TCP port (usually 502). The separate analyzer HTTP port 8765 does not apply. |
| Local sensors unavailable | Check `/api/ha` and the analyzer collector mode. Wait for a successful capture; Cooperative quiet windows can extend the first wait. |
| Cloud uploads stop or datalogger shows red | Restore the analyzer's Original/cloud-only mode, then try Cooperative mode at 180 seconds. Ten-second direct polling disrupted cloud delivery on the reported installation. |

For temporary debug logging, use:

```yaml
logger:
  logs:
    custom_components.cloud_inverter: debug
```

Review logs before sharing them. The current source files are sanitized, but
older Git commits may still contain historical example or installation values.

## Development

The repository's lightweight tests run with:

```shell
python -m unittest discover -s tests -v
```

These tests cover request signing and local URL validation. They do not replace
a live Home Assistant setup or physical inverter test. The analyzer has its own
tests under `local_analyzer/tests`; see its README.

Report reproducible issues through [GitHub Issues](https://github.com/usamakkhan/home-assistant-Cloud-Inverter/issues).
