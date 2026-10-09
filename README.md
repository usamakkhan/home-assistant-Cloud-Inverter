# ☀️ Cloud Inverter for Home Assistant

<p align="center"><img src="custom_components/cloud_inverter/brand/icon.png" alt="Cloud Inverter icon" width="112"></p>

<p align="center">
  <a href="https://github.com/usamakkhan/home-assistant-Cloud-Inverter/releases"><img alt="Release" src="https://img.shields.io/github/v/release/usamakkhan/home-assistant-Cloud-Inverter?color=blue"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="https://github.com/usamakkhan/home-assistant-Cloud-Inverter/actions"><img alt="Validation" src="https://img.shields.io/github/actions/workflow/status/usamakkhan/home-assistant-Cloud-Inverter/hacs-validation.yml?branch=main&label=validation"></a>
</p>

Read SolarMax/Senergy inverter telemetry in Home Assistant through **one of two setup choices**:

- 🏠 **Get Data Locally using Inverter IP:** Home Assistant reads the inverter's Modbus/TCP bridge directly. No portal login or separate analyzer process is needed.
- ☁️ **CloudInverter.net:** Home Assistant reads the vendor's HTTPS API using your portal account.

The integration creates sensor entities for available measurements. It does not provide inverter setting controls. Supported readings vary with device, firmware, and selected source.

> [!IMPORTANT]
> On the installation reported by the project owner, the **inverter uploads data to CloudInverter.net about every five minutes**. A Home Assistant cloud refresh can happen more often, but it may receive the **same uploaded reading** until the inverter sends its next update. The integration does not control the inverter's upload schedule.

## 🧭 Choose your data source

| | 🏠 Direct inverter LAN | ☁️ CloudInverter.net |
| --- | --- | --- |
| Setup label | **Get Data Locally using Inverter IP** | **CloudInverter.net** |
| Home Assistant connects to | Inverter LAN IP and Modbus/TCP port | Vendor HTTPS API |
| Default interval | **180 seconds** between collection attempts | **30 seconds** between API requests |
| Adjustable interval | **10–900 seconds** in Options | **30–900 seconds** in Options |
| Default port / unit | **502 / 1**, both editable | Not applicable |
| Portal credentials | Not required | Required |
| Internet for readings | Not required | Required |
| Hardware profile | SolarMax/Senergy PV9000/ONYX register profile | Supported portal response fields |

```mermaid
flowchart LR
    I["☀️ Inverter"] -->|"reported cloud upload: about 5 min"| C["☁️ CloudInverter.net"]
    H["🏠 Home Assistant"] -->|"cloud API check: 30 s default"| C
    H -->|"direct Modbus read: 180 s default"| I
    classDef device fill:#FFF3C4,stroke:#C68810,color:#242424
    classDef ha fill:#D8F3E5,stroke:#1E8250,color:#242424
    classDef cloud fill:#DCEBFF,stroke:#3271BD,color:#242424
    class I device
    class H ha
    class C cloud
```

The diagram shows the two available paths; select one when adding the integration. The reported five-minute upload is **device-to-cloud traffic**, while the 30-second and 180-second values are **Home Assistant read intervals**. A direct LAN capture can be delayed by a quiet window around the estimated cloud upload period, so its actual spacing may exceed 180 seconds.

## 📊 What data appears in Home Assistant?

Depending on the source and inverter, readings can cover:

- **Solar production:** PV power, input voltage/current, and MPPT values.
- **Grid:** import/export power, voltage, current, and energy counters when provided.
- **Battery:** state of charge, charge/discharge power, voltage/current, and energy when reported.
- **Loads and outputs:** available household, backup, and generator-side measurements.
- **Device health:** operating mode, temperatures, status, and selected device metadata.

Cloud and direct LAN paths have different field sets. A missing register or portal field is not treated as zero. Home Assistant assigns entity IDs when it creates entities, so check your device page for the actual names. The app does **not** invent readings before a successful capture.

## 🚀 Install in Home Assistant

### Option A: HACS

1. In HACS, add `https://github.com/usamakkhan/home-assistant-Cloud-Inverter` as a **custom Integration repository**.
2. Install **Cloud Inverter** from HACS.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**, search for **Cloud Inverter**, and choose your data source.

### Option B: manual installation

1. Download the [latest release](https://github.com/usamakkhan/home-assistant-Cloud-Inverter/releases) or the repository ZIP.
2. Copy the entire `custom_components/cloud_inverter` directory into Home Assistant's `/config/custom_components/` directory. The result should contain `/config/custom_components/cloud_inverter/manifest.json`.
3. Restart Home Assistant, then add **Cloud Inverter** from **Settings → Devices & services**.

See the [detailed installation guide](INSTALL.md) for step-by-step setup, network checks, updating, and the optional standalone analyzer. HACS and manual installation provide the same two setup choices.

## 🏠 Set up direct inverter LAN access

1. Confirm that **Home Assistant itself** can reach the inverter's LAN IP. Use `192.168.50.10` as an example; replace it privately with your inverter's address.
2. Add **Cloud Inverter → Get Data Locally using Inverter IP**.
3. Enter the **Inverter LAN IP**. Leave the separate **Modbus/TCP port** at `502` and **unit ID** at `1` unless your bridge requires other values.
4. Leave the **collection interval** at `180` seconds to start. You can change it later in **Options**.
5. Submit the form. Home Assistant probes read-only Modbus register `0x1001` and shows the IP, port, unit ID, and returned raw value on a **confirmation page**. Check these before the final submit.
6. Confirm to create the entry and allow the first full capture. Check the new device's sensors after it completes.

The initial probe confirms that a Modbus response came from the entered endpoint; it does not guarantee that every register on every model/firmware is supported. Direct collection runs **inside Home Assistant**. It does not need the standalone analyzer's HTTP port `8765`.

> [!CAUTION]
> A 10-second interval is permitted, but frequent Modbus reads **interrupted cloud delivery and turned the datalogger light red on the reported installation**. Start at 180 seconds, observe the datalogger and portal over multiple five-minute upload cycles, and adjust only if your hardware tolerates it. The collector uses estimated quiet windows near the five-minute boundary; these cannot guarantee uninterrupted cloud uploads because the actual upload phase can vary.

## ☁️ Set up CloudInverter.net

1. Add **Cloud Inverter → CloudInverter.net**.
2. Enter your portal username and password. Choose an inverter if the account has more than one.
3. Wait for the first API update, then inspect the device and sensor states.
4. If desired, change the API refresh interval in **Options** (30–900 seconds).

At the default 30-second interval, Home Assistant can ask the API several times during one reported five-minute inverter upload cycle. Repeated values during that period can be normal. Changing the Home Assistant refresh interval does **not** change how often the inverter transmits to the vendor.

Credentials are stored in the Home Assistant config entry; the API session token is kept in memory. Protect Home Assistant backups. If website login works but integration login fails, check the portal/API status and share only sanitized logs in an issue.

## 🧰 Optional standalone analyzer

The repository also contains [`local_analyzer/`](local_analyzer/README.md), a **separate** SolarMax PV9000 dashboard and history application. You do not need it for either of the two Cloud Inverter setup choices. It can be useful when you want a dedicated local dashboard, stored capture history, or its additional analysis features.

For a new Home Assistant connection to that separate application, follow its [Home Assistant connector or REST package guide](local_analyzer/home_assistant/README.md). Older **Local analyzer** config entries in Cloud Inverter remain supported, but that entry type is no longer offered as a new setup choice. Avoid running two Modbus collectors against the same inverter unless you deliberately need both and have checked the effect on cloud uploads.

## 🔧 Troubleshooting

| Symptom | Check |
| --- | --- |
| **Cloud Inverter** is missing after installation | Verify `/config/custom_components/cloud_inverter/manifest.json` exists, remove any extra directory nesting, and restart Home Assistant. |
| Portal website accepts login but the integration rejects it | Verify the same account, current portal availability, and the sanitized Home Assistant API error. Website and API responses can differ. Never post credentials or tokens. |
| Direct IP check fails | Verify the inverter IP, Modbus/TCP port (default `502`), unit ID (default `1`), LAN routing, and bridge availability from the Home Assistant host. Port `8765` belongs to the optional analyzer, not direct setup. |
| IP check succeeds but sensors are unavailable | The probe checks one register. Verify the PV9000-compatible profile, wait for the full capture and quiet window, then inspect sanitized Modbus errors in Home Assistant logs. |
| Cloud readings repeat | Check the reading timestamp and allow for the reported **about-five-minute** inverter upload cadence. More frequent API requests can return the same snapshot. |
| Cloud uploads stop or datalogger turns red | Increase the direct collection interval or stop local collection while you check the hardware. The reported installation had this behavior with 10-second polling. |
| Optional analyzer readings are old or unavailable | Check its dashboard capture time and `/api/ha` response. Before its first capture, that endpoint can return HTTP `503`. |

Temporary debug logging:

```yaml
logger:
  logs:
    custom_components.cloud_inverter: debug
```

Remove or redact passwords, tokens, account IDs, serials, MAC addresses, and private LAN addresses before sharing logs or screenshots. Documentation examples use `ABCDE123456789` as a sample serial. Historical Git commits may contain older example values; review them before reposting material.

## 🧪 Development, support, and license

- Run the integration tests with `python -m unittest discover -s tests -v`. They cover signing, URL validation, direct Modbus checks, capture behavior, and freshness logic; they do not replace a real inverter and Home Assistant test.
- The standalone analyzer has its own tests under `local_analyzer/tests`; see its [README](local_analyzer/README.md).
- Review release changes in the [changelog](CHANGELOG.md) and report reproducible problems through [GitHub Issues](https://github.com/usamakkhan/home-assistant-Cloud-Inverter/issues), using sanitized details.
- This repository uses the [MIT License](LICENSE). Bundled integration icons live in [`brand/`](custom_components/cloud_inverter/brand); [Home Assistant's brand image guidance](https://developers.home-assistant.io/docs/core/integration/brand_images/) explains how Home Assistant displays integration assets.
