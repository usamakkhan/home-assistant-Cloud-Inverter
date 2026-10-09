# Installation guide

This guide installs **Cloud Inverter** in Home Assistant and connects either
CloudInverter.net or a local SolarMax PV9000 analyzer. Choose one source when
adding the integration. The local analyzer is a separate Python application
that runs on a computer with access to the inverter; it does not run inside
Home Assistant.

## Before you start

| Source | You need | Default Home Assistant refresh |
| --- | --- | --- |
| CloudInverter.net | A working portal account, an inverter associated with it, and internet access from Home Assistant | 30 seconds |
| Local analyzer | Python 3.11+ on an always-on LAN computer, access to the inverter's Modbus/TCP bridge, and network access from Home Assistant to the analyzer | 180 seconds |

Download the repository with **Code → Download ZIP** on
[GitHub](https://github.com/usamakkhan/home-assistant-Cloud-Inverter), or clone
it with:

```shell
git clone https://github.com/usamakkhan/home-assistant-Cloud-Inverter.git
```

Keep the extracted repository directory available for the steps below.
Examples use `192.168.50.10` for the inverter,
`192.168.50.20` for the analyzer computer, and
`ABCDE123456789` for a sample serial. Replace these locally with your own
values; do not publish your values in issues or screenshots.

## 1. Install the Home Assistant integration

Use **either** HACS or manual installation. Both install the same
`cloud_inverter` integration.

### HACS

1. Install and open [HACS](https://www.hacs.xyz/docs/use/) in Home Assistant.
2. Open the HACS menu, select **Custom repositories**, and enter
   `https://github.com/usamakkhan/home-assistant-Cloud-Inverter`.
3. Choose **Integration** as the repository type and add it. See the
   [official HACS custom repository instructions](https://www.hacs.dev/docs/faq/custom_repositories/)
   if your HACS interface differs.
4. Find **Cloud Inverter** in HACS and install it.
5. Restart Home Assistant.

### Manual

1. In the downloaded repository, find `custom_components/cloud_inverter`.
2. Copy that entire directory to Home Assistant's configuration directory
   under `custom_components`. The result must contain:

   ```text
   /config/
   └── custom_components/
       └── cloud_inverter/
           ├── manifest.json
           ├── config_flow.py
           └── ...
   ```

   The configuration directory may have another host filesystem path; the
   directory Home Assistant sees as `/config` is the destination.
3. Restart Home Assistant. Copying files alone does not load a new integration.

If **Cloud Inverter** does not appear in **Settings → Devices & services →
Add integration**, check the directory nesting and `manifest.json`, then
restart again. Do not copy the entire repository into `custom_components`.

## 2A. Connect CloudInverter.net

1. In Home Assistant, open **Settings → Devices & services → Add integration**.
2. Search for **Cloud Inverter** and select **CloudInverter.net**.
3. Enter your portal username and password. If more than one inverter is
   associated with the account, select the intended inverter.
4. Open the new device and wait for its first sensor update.

The default cloud refresh is **30 seconds**. To change it later, open the
integration's **Options** and choose a value from **30–900 seconds**. This
refresh asks the vendor API for data; the vendor may update its underlying
reading on a different schedule.

If setup reports incorrect credentials while website login works, confirm the
account and portal service, then collect only a **sanitized** Home Assistant
log message and API status for an issue. Remove passwords, tokens, account
IDs, serials, and LAN addresses. Website login and API availability can
differ.

## 2B. Run the local analyzer

### Check the host and network

1. Choose an always-on Windows, Linux, or macOS computer that can reach the
   inverter's LAN bridge. This can be the Home Assistant host if it has Python
   3.11+ and the required network access.
2. Find the inverter's LAN IP and the analyzer computer's LAN IP. Use your
   router's device list or your existing network configuration. The inverter's
   Modbus/TCP service normally uses **port 502**; this is separate from the
   analyzer HTTP port.
3. Confirm Python 3.11 or newer: `python --version`. On systems where
   `python` is unavailable, use `python3` (common on Linux/macOS) or
   `py -3` (Windows) in the commands below.
4. Open a terminal in the downloaded repository's `local_analyzer` directory.
   The analyzer uses Python's standard library and does not require a
   `pip install` step.

### Start collection for Home Assistant

For Home Assistant on another LAN machine, run:

```shell
python app.py --no-browser --bind 0.0.0.0 --port 8765 --no-peer-api --monitor-host 192.168.50.10 --monitor-interval 180 --monitor-mode cooperative
```

Replace `192.168.50.10` with your inverter's LAN IP. Keep the terminal and
computer running for ongoing updates. `--bind 0.0.0.0` allows other LAN hosts
to reach the analyzer; it is **not** the address to enter in Home Assistant.
Allow inbound TCP **8765** to the analyzer computer from the Home Assistant
host in your local firewall. Keep the service on your trusted LAN; do not
forward this port through your router.

If Home Assistant runs on the same computer, you can omit
`--bind 0.0.0.0` and use `127.0.0.1` as the analyzer Host. If port 8765 is in
use, change `--port 8765` to an available port and enter the same port in
Home Assistant. The inverter's port 502 does not change with this setting.

The default when you start `python app.py` without monitor arguments is
**Original/cloud-only**: automatic inverter collection is off. The command
above explicitly starts **Cooperative** collection with a **180-second**
target. Cooperative cloud quiet windows may postpone a sample beyond that
target. You can change the analyzer's collection target in its dashboard.

Direct polling can be set as low as **10 seconds**, but frequent reads may
interrupt the inverter's cloud upload and make the datalogger light turn red.
Start at **180 seconds** and use Cooperative mode. If cloud uploads stop,
return to Original/cloud-only mode and inspect the collector status before
trying another interval.

### Check the analyzer

On the analyzer computer, open `http://127.0.0.1:8765` for the dashboard.
From the Home Assistant network, open
`http://192.168.50.20:8765/api/config`, replacing `192.168.50.20` with the
analyzer computer's address. A JSON configuration response confirms that the
HTTP service is reachable.

After a successful inverter capture, open
`http://192.168.50.20:8765/api/ha`. Before the first capture, this endpoint
returns HTTP **503**; wait for the analyzer's capture status to show a reading
before adding the Home Assistant source. If there are no captures, check the
inverter IP, bridge access, collector mode, and firewall.

### Add the local source to Home Assistant

1. Open **Settings → Devices & services → Add integration → Cloud Inverter**.
2. Choose **Local analyzer**.
3. Enter the analyzer computer's LAN IP or hostname in **Host**, such as
   `192.168.50.20`. Do not include `http://`, a port, or `/api/ha`.
4. Leave **Port** at **8765**, or enter the port chosen with `--port`.
5. Leave **Home Assistant cache scan** at **180 seconds**, or set a value
   from **10–900 seconds**.
6. Finish setup and open the created device to check sensor states.

The Home Assistant cache scan controls HTTP reads of the analyzer's stored
sample. The analyzer's **collection target** separately controls inverter
reads. Changing the cache scan does not change collection frequency. To edit
Host, Port, or cache scan later, open the integration's **Options**. To edit
collection, use the analyzer dashboard or restart it with a new
`--monitor-interval`.

Do not install the standalone `solarmax_pv9000` connector alongside this local
source for the same analyzer: that creates duplicate entities.

## Optional local Home Assistant methods

The recommended local method is **Cloud Inverter → Local analyzer** above.
Two alternatives are included for installations that need them:

- **Standalone connector:** Copy
  `local_analyzer/home_assistant/custom_components/solarmax_pv9000` to
  `/config/custom_components/solarmax_pv9000`, restart Home Assistant, and add
  **SolarMax Local Cloud Connector**. Enter the analyzer's full base URL
  (`http://192.168.50.20:8765`) and its cache scan interval. This connector
  requires analyzer controls to be disabled. Use it instead of the Cloud
  Inverter local source.
- **REST package:** Follow the
  [local Home Assistant guide](local_analyzer/home_assistant/README.md) to
  enable packages in `configuration.yaml`, set the analyzer URL in
  `solarmax_rest_package.yaml`, and restart Home Assistant. It exposes a
  smaller sensor set and should also be used instead of another local method.

## Updating and checks

For HACS installations, update Cloud Inverter through HACS and restart Home
Assistant. For manual installations, replace
`/config/custom_components/cloud_inverter` with the new repository copy and
restart. Update the separately running `local_analyzer` files when you want
its fixes; restart its process afterward. Preserve your local analyzer data
directory when replacing application files.

| Symptom | Check |
| --- | --- |
| Integration is missing | Verify `/config/custom_components/cloud_inverter/manifest.json`, then restart Home Assistant. |
| Cloud login fails | Confirm account credentials and portal availability; use sanitized logs to report the failing API status. |
| Local setup cannot connect | Open `http://ANALYZER_IP:PORT/api/config` from the Home Assistant network. Check Host, Port, bind address, process, and firewall. |
| `/api/ha` is HTTP 503 | Wait for a successful analyzer capture; check inverter IP and collector mode. |
| Local sensors are unavailable or old | Check `/api/ha`, the analyzer dashboard's capture time, and whether its process is still running. |
| Cloud uploads stop or datalogger turns red | Return to Original/cloud-only mode; use Cooperative collection at a 180-second target when trying again. |

See the [main README](README.MD), [analyzer guide](local_analyzer/README.md),
and [local Home Assistant guide](local_analyzer/home_assistant/README.md) for
feature descriptions and further troubleshooting.
