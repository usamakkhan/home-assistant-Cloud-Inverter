# ☀️ Solar Touch installation guide

This guide installs the Solar Touch integration in Home Assistant and connects it through either **Get Data Locally using Inverter IP** or **CloudInverter.net**. Local collection runs inside Home Assistant.

## Before you start

| Source | Requirements | Default Home Assistant interval |
| --- | --- | --- |
| 🏠 Direct inverter LAN | Home Assistant can reach the inverter's SolarMax/Senergy PV9000 Modbus/TCP bridge | **180 seconds** between collection attempts |
| ☁️ CloudInverter.net | A portal account with an inverter and internet access from Home Assistant | **300 seconds (5 minutes)** between API requests |

The inverter on the reported installation uploads to CloudInverter.net **about every five minutes**. Cloud API polling does not change that device upload schedule. Direct LAN collection uses a separate interval and may be delayed around estimated upload windows.

Examples in this guide use `192.168.50.10` as an **example inverter IP** and `ABCDE123456789` as an **example serial**. Replace these locally; do not publish your real address or serial in screenshots or issues.

## 1. Install the integration

Use **HACS** or **manual installation**. Both provide the same integration.

### HACS

1. Install and open [HACS](https://www.hacs.xyz/docs/use/) in Home Assistant.
2. Add `https://github.com/usamakkhan/home-assistant-Solar-Touch` as a custom **Integration** repository. See the [HACS custom repository guide](https://www.hacs.dev/docs/faq/custom_repositories/) if the menu has changed.
3. Find **Solar Touch** in HACS and install it.
4. **Restart Home Assistant.** A pending restart in HACS means Home Assistant has not yet loaded the new files.

### Manual

1. Download the [latest release](https://github.com/usamakkhan/home-assistant-Solar-Touch/releases) or the repository ZIP.
2. Copy the whole `custom_components/cloud_inverter` directory into Home Assistant's `/config/custom_components/` directory. Check that `/config/custom_components/cloud_inverter/manifest.json` exists.
3. Restart Home Assistant. Copying files does not load a new integration until restart.

If **Solar Touch** is absent from **Settings → Devices & services → Add integration**, verify the destination path has only one `custom_components` directory level, then restart again.

## 2A. Connect directly to the inverter

1. Find the **inverter's LAN IP** in your network configuration. Confirm Home Assistant can reach its Modbus/TCP bridge. The default Modbus/TCP port is **502**, but the setup form allows an override.
2. In Home Assistant, open **Settings → Devices & services → Add integration → Solar Touch** and select **Get Data Locally using Inverter IP**.
3. Enter the inverter's IP, such as `192.168.50.10`. Enter the inverter's **Modbus/TCP port** separately; leave it at `502` unless your bridge uses another port. Leave **Modbus unit ID** at `1` unless your device requires another value.
4. Leave **Inverter collection interval** at **180 seconds** initially. Submit the form.
5. Home Assistant sends a read-only request for register `0x1001`. If the IP, port, unit ID, or response fails, correct the form and retry.
6. Check the **confirmation page** for the tested IP, port, unit ID, and raw register value. Submit again to create the integration entry.
7. Wait for the first full capture. It may wait for an estimated cloud quiet window. Open the new device to inspect its available sensors.

The IP probe proves that this endpoint answered one Modbus request; full sensor coverage depends on the model and firmware. Direct collection runs inside Home Assistant and requires no separate program or HTTP service.

### Adjust direct collection

Open the Solar Touch entry's **Options** to change the inverter IP, Modbus/TCP port, unit ID, or collection interval. The interval accepts **10–900 seconds**. The default is **180 seconds**.

> [!CAUTION]
> On the reported installation, a 10-second local polling interval interrupted cloud uploads and made the datalogger light turn red. Start at 180 seconds, observe the datalogger and portal over several five-minute upload cycles, and change the interval only if your hardware tolerates it. Estimated quiet windows can delay a capture; they cannot guarantee cloud delivery.

## 2B. Connect to CloudInverter.net

1. In Home Assistant, open **Settings → Devices & services → Add integration → Solar Touch** and select **CloudInverter.net**.
2. Enter your portal username and password. If your account has multiple inverters, select the intended device.
3. Wait for the first API update and inspect the new device's sensors.
4. If needed, open **Options** to change the API refresh interval (**30–900 seconds**). The default is **300 seconds (5 minutes)**.

The inverter reportedly uploads to the portal about every five minutes. Two API checks can still show the same values if upload timing and API polling do not align. An explicit interval saved earlier in Options remains in effect after an update until you change it.

If the integration rejects credentials that work on the website, verify account details and portal availability, then collect a **sanitized** Home Assistant error for an issue. Website and API behavior can differ. Never share passwords, session tokens, account IDs, or real serials.

### Configure the Energy dashboard

In **Settings → Dashboards → Energy**, assign **Total Energy** to solar production, **Grid Import Total** to grid energy imported, and **Grid Export Total** to grid energy exported. For a supported home battery, use **Battery Charge Total** for energy going into the battery and **Battery Discharge Total** for energy coming out. These are cumulative kWh counters; Home Assistant measures their increases. A lifetime reading is the starting point for future increases, not energy consumed or produced on the day you add it. Select each production stream once; do not add both **Daily Energy** and **Total Energy** for the same inverter.

If a sensor is absent from the Energy selector, find it in **Settings → Developer Tools → States** and check for a numeric state, `device_class: energy`, `state_class: total_increasing`, and `unit_of_measurement: kWh`. Then inspect **Settings → Developer Tools → Statistics** for an error on that entity and confirm Recorder has not excluded it. See the [Home Assistant Energy FAQ](https://www.home-assistant.io/docs/energy/faq/) and the [README Energy guide](README.md#-add-cloudinverternet-sensors-to-the-energy-dashboard).

## Upgrade from an older analyzer based setup

The current release does not include the former standalone analyzer application, its HTTP source, or its companion Home Assistant connector. If you previously created a **Local analyzer** entry in Solar Touch:

1. Open **Settings → Devices & services → Solar Touch** and remove the old Local analyzer entry.
2. Add Solar Touch again and select **Get Data Locally using Inverter IP**.
3. Enter the **inverter's own IP**, not the old analyzer computer's IP. Use its Modbus/TCP port (normally `502`) and unit ID (normally `1`).
4. Review dashboards and automations that use old entity IDs, as removing the old entry may remove those entities.

Existing **direct inverter LAN** and **CloudInverter.net** entries do not need to be recreated. If you previously ran the analyzer on another computer, stopping that separate process is an action on that computer; updating this Home Assistant integration does not stop it for you.

## Updating and troubleshooting

- **HACS:** install the update in HACS, then restart Home Assistant.
- **Manual:** replace `/config/custom_components/cloud_inverter` with the new integration directory and restart Home Assistant.
- **Solar Touch missing:** check `/config/custom_components/cloud_inverter/manifest.json` and restart.
- **Direct IP check fails:** check the inverter's IP, Modbus/TCP port, unit ID, network route, and bridge availability from the Home Assistant host.
- **Direct check succeeds but sensors are unavailable:** wait for the full capture and quiet window, confirm PV9000 profile compatibility, and inspect sanitized Modbus errors in Home Assistant logs.
- **Cloud readings repeat:** allow for the reported five-minute inverter upload period; API polling can receive the previous snapshot.
- **Datalogger turns red or cloud updates stop:** increase the direct collection interval or stop local collection while checking hardware behavior.
- **Old Local analyzer entry fails:** remove that entry and add the direct source using the inverter's own LAN IP.

For temporary debug logs:

```yaml
logger:
  logs:
    custom_components.cloud_inverter: debug
```

Remove credentials, tokens, account identifiers, serials, MAC addresses, and private LAN addresses from logs before sharing them. See the [README](README.md), [changelog](CHANGELOG.md), and [issue tracker](https://github.com/usamakkhan/home-assistant-Solar-Touch/issues) for more details.
