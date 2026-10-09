 Cloud Inverter Home Assistant Integration

A Home Assistant integration for monitoring Cloud Inverter (SenergyTec) solar systems with real-time data updates.

## Local analyzer and Home Assistant connector

For local collection without a CloudInverter login, see the separate
[SolarMax local analyzer](local_analyzer/README.md). Its
[Home Assistant setup guide](local_analyzer/home_assistant/README.md) explains
how to run the analyzer on your LAN and install its read-only connector. The
local analyzer uses a 180-second collection preset and example network and
serial values; enter your own inverter LAN address before enabling collection.

The Cloud Inverter integration documented below remains the cloud-login option.

> Inspired by [DESS Monitor Integration](https://github.com/Antoxa1081/home-assistant-dess-monitor), designed specifically for Cloud Inverter systems.

 Features

✅ Real-time Monitoring
- Solar PV power generation (current & daily)
- Battery status (SOC, SOH, voltage, current)
- Grid import/export tracking
- Home load consumption
- Heavy load monitoring
- On-grid load (EV charger) support

✅ Multi-MPPT Support
- Track up to 2 MPPT trackers
- Individual voltage, current, and power monitoring

✅ Energy Statistics
- Daily energy production
- Total energy production (all-time)
- Self-consumption rate
- Self-sufficiency rate
- Battery charge/discharge tracking

✅ System Information
- Inverter temperature
- WiFi signal strength
- Operating mode and status
- Firmware versions
- Real-time connectivity status

 Installation

 Method 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots (⋯) → Custom Repositories
3. Add repository:
   - URL**: `https://github.com/usamakkhan/home-assistant-Cloud-Inverter`
   - Category**: Integration
4. Click Add
5. Search for **"Cloud Inverter"** and install
6. Restart Home Assistant

 Method 2: Manual Installation

1. Download the repository as ZIP
2. Copy `custom_components/cloud_inverter/` from the archive to `config/custom_components/cloud_inverter/`.
3. Restart Home Assistant

 Setup

 Configuration

1. Go to Settings → Devices & Services → Integrations
2. Click Create Integration → Search for **"Cloud Inverter"**
3. Enter your credentials:
   - Username**: Your CloudInverter.net username
   - Password**: Your CloudInverter.net password
4. Select your inverter from the list
5. Complete setup

That's it! The integration will automatically create sensors for all your inverter data.

 Supported Devices

- ✅ SM-ONYX-UL-6KW (tested)
- ✅ Any Cloud Inverter device (model support auto-detection)

 Available Sensors

 Solar Production
- `sensor.solar_pv_current_power` - Real-time solar output
- `sensor.solar_production_today` - Daily energy
- `sensor.solar_production_all_time` - Total energy
- `sensor.peak_power_today` - Peak output

 MPPT Tracking
- `sensor.solar_mppt1_power` - MPPT1 power output
- `sensor.solar_mppt2_power` - MPPT2 power output
- `sensor.solar_mppt1_voltage` - MPPT1 voltage
- `sensor.solar_mppt2_voltage` - MPPT2 voltage
- `sensor.solar_mppt1_ampere` - MPPT1 current
- `sensor.solar_mppt2_ampere` - MPPT2 current

 Battery Management
- `sensor.battery_soc` - State of Charge (%)
- `sensor.battery_soh` - State of Health (%)
- `sensor.battery_voltage` - Current voltage
- `sensor.battery_ampere` - Current charging/discharging current
- `sensor.battery_charge_power` - Charging power
- `sensor.battery_discharge_power` - Discharging power
- `sensor.battery_type` - Battery type
- `sensor.battery_capacity` - Battery capacity

 Grid Management
- `sensor.grid_voltage` - Grid voltage
- `sensor.grid_current` - Grid current
- `sensor.grid_frequency` - Grid frequency
- `sensor.grid_export_today` - Energy exported today
- `sensor.grid_export_total` - Total energy exported
- `sensor.grid_import_today` - Energy imported today
- `sensor.grid_import_total` - Total energy imported

 Home Load (EPS)
- `sensor.home_load_power` - Current consumption
- `sensor.home_load_today` - Daily consumption
- `sensor.home_load_total` - Total consumption

 Heavy Load (Generator)
- `sensor.heavy_load_power` - Current usage
- `sensor.heavy_load_today` - Daily usage
- `sensor.heavy_load_total` - Total usage

 On-Grid Load (EV Charger)
- `sensor.on_grid_load_power` - Current usage
- `sensor.on_grid_load_today` - Daily usage
- `sensor.on_grid_load_total` - Total usage

 System Information
- `sensor.inverter_temperature` - Operating temperature
- `sensor.inverter_status` - Connection status
- `sensor.inverter_wifi_strength` - WiFi signal strength
- `sensor.self_consumption_rate` - Daily self-consumption %
- `sensor.self_sufficiency_rate` - Daily self-sufficiency %

 Configuration Options

The integration uses automatic discovery. No YAML configuration needed!

 Update Interval

The default update interval is 60 seconds**. To modify:

1. Go to Settings → Devices & Services
2. Find your Cloud Inverter device
3. Click the three dots → System Options
4. Adjust scan interval as needed

 Automations & Templates

Create automations based on sensor values:

```yaml
automation:
  - alias: "Low Battery Alert"
    trigger:
      platform: numeric_state
      entity_id: sensor.battery_soc
      below: 20
    action:
      service: notify.notify
      data:
        message: "Battery level is below 20%"
```

 API Details

This integration connects to your Cloud Inverter's cloud API:
- Base URL**: `https://www.cloudinverter.net`
- Update Frequency**: 60 seconds (configurable)
- Authentication**: Username + Password. Requests are signed from their current fields.

Home Assistant stores the username and password in the integration's config entry. The cloud API token is kept in memory for the active session. Protect Home Assistant backups and do not share config entries or unredacted logs.

 Troubleshooting

 Integration won't load
- Verify your username and password are correct
- Check your internet connection
- Ensure your Cloud Inverter device is online
- If login fails while the website works, enable the logger below and check the `Cloud Inverter login rejected` status and code. Share only those values when reporting the issue; replace account IDs and serial numbers with `ABCDE123456789` and remove passwords, tokens, and cookies.

 Sensors showing "unavailable"
- Check Home Assistant logs for errors
- Verify inverter is producing data
- Try reloading the integration

 View Logs

```yaml
logger:
  logs:
    custom_components.cloud_inverter: debug
```

 Contributing

Found an issue? Have a suggestion?
- 🐛 [Report a bug](https://github.com/usamakkhan/home-assistant-Cloud-Inverter/issues)
- ✨ [Request a feature](https://github.com/usamakkhan/home-assistant-Cloud-Inverter/issues)

 License

MIT License - See LICENSE file

 Support

For issues specific to:
- Integration: [GitHub Issues](https://github.com/usamakkhan/home-assistant-Cloud-Inverter/issues)
- Cloud Inverter Device**: Contact your device manufacturer

---

Made with ❤️ for solar enthusiasts
