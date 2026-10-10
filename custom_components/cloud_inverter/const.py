"""Constants for the Solar Touch integration."""

DOMAIN = "cloud_inverter"

# API Constants
API_BASE_URL = "https://www.cloudinverter.net/dist/server/api/CodeIgniter/index.php/Senergytec/web/v2/Inverterapi"

# API Endpoints
ENDPOINT_LOGIN = f"{API_BASE_URL}/UserLogin_v1"
ENDPOINT_MEMBER_DATA = f"{API_BASE_URL}/GetMemberData"
ENDPOINT_ALL_MEMBERS = f"{API_BASE_URL}/getAllAllMember"
ENDPOINT_GROUP_LIST = f"{API_BASE_URL}/GroupList"
ENDPOINT_GROUP_DETAIL = f"{API_BASE_URL}/GroupDetailList"
ENDPOINT_INVERTER_DETAIL = f"{API_BASE_URL}/InverterDetailInfoNewone"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_GOODS_ID = "goods_id"
CONF_MEMBER_AUTO_ID = "member_auto_id"
CONF_TOKEN = "token"
CONF_SOURCE = "source"
SOURCE_CLOUD = "cloud"
SOURCE_DIRECT = "direct"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_DIRECT_PORT = 502
DEFAULT_DIRECT_UNIT_ID = 1
DEFAULT_DIRECT_SCAN_INTERVAL = 180

# Cloud API polling (seconds). The inverter uploads to the vendor roughly every
# five minutes on my installation; faster polling usually repeats data.
UPDATE_INTERVAL = 300
MIN_CLOUD_SCAN_INTERVAL = 30

# Sensor Types - Photovoltaic (Solar)
SENSOR_PV_POWER = "pv_power"
SENSOR_PV_VOLTAGE_MPPT1 = "pv_voltage_mppt1"
SENSOR_PV_VOLTAGE_MPPT2 = "pv_voltage_mppt2"
SENSOR_PV_CURRENT_MPPT1 = "pv_current_mppt1"
SENSOR_PV_CURRENT_MPPT2 = "pv_current_mppt2"
SENSOR_PV_POWER_MPPT1 = "pv_power_mppt1"
SENSOR_PV_POWER_MPPT2 = "pv_power_mppt2"

# Sensor Types - Production
SENSOR_DAILY_ENERGY = "daily_energy"
SENSOR_TOTAL_ENERGY = "total_energy"
SENSOR_PEAK_POWER_TODAY = "peak_power_today"

# Sensor Types - Grid
SENSOR_GRID_VOLTAGE = "grid_voltage"
SENSOR_GRID_CURRENT = "grid_current"
SENSOR_GRID_FREQUENCY = "grid_frequency"
SENSOR_GRID_POWER = "grid_power"
SENSOR_GRID_EXPORT_TODAY = "grid_export_today"
SENSOR_GRID_IMPORT_TODAY = "grid_import_today"
SENSOR_GRID_EXPORT_TOTAL = "grid_export_total"
SENSOR_GRID_IMPORT_TOTAL = "grid_import_total"

# Sensor Types - Battery
SENSOR_BATTERY_VOLTAGE = "battery_voltage"
SENSOR_BATTERY_CURRENT = "battery_current"
SENSOR_BATTERY_POWER = "battery_power"
SENSOR_BATTERY_SOC = "battery_soc"
SENSOR_BATTERY_SOH = "battery_soh"
SENSOR_BATTERY_CHARGING_POWER = "battery_charging_power"
SENSOR_BATTERY_DISCHARGING_POWER = "battery_discharging_power"
SENSOR_BATTERY_CHARGE_TODAY = "battery_charge_today"
SENSOR_BATTERY_DISCHARGE_TODAY = "battery_discharge_today"
SENSOR_BATTERY_CHARGE_TOTAL = "battery_charge_total"
SENSOR_BATTERY_DISCHARGE_TOTAL = "battery_discharge_total"
SENSOR_BATTERY_TYPE = "battery_type"
SENSOR_BATTERY_CAPACITY = "battery_capacity"

# Sensor Types - Home Load (EPS)
SENSOR_HOME_VOLTAGE = "home_voltage"
SENSOR_HOME_CURRENT = "home_current"
SENSOR_HOME_FREQUENCY = "home_frequency"
SENSOR_HOME_POWER = "home_power"
SENSOR_HOME_ENERGY_TODAY = "home_energy_today"
SENSOR_HOME_ENERGY_TOTAL = "home_energy_total"

# Sensor Types - Heavy Load (Generator)
SENSOR_HEAVY_VOLTAGE = "heavy_voltage"
SENSOR_HEAVY_CURRENT = "heavy_current"
SENSOR_HEAVY_FREQUENCY = "heavy_frequency"
SENSOR_HEAVY_POWER = "heavy_power"
SENSOR_HEAVY_ENERGY_TODAY = "heavy_energy_today"
SENSOR_HEAVY_ENERGY_TOTAL = "heavy_energy_total"

# Sensor Types - On-Grid Load
SENSOR_LOAD_VOLTAGE = "load_voltage"
SENSOR_LOAD_CURRENT = "load_current"
SENSOR_LOAD_FREQUENCY = "load_frequency"
SENSOR_LOAD_POWER = "load_power"
SENSOR_LOAD_ENERGY_TODAY = "load_energy_today"
SENSOR_LOAD_ENERGY_TOTAL = "load_energy_total"

# Sensor Types - System
SENSOR_INVERTER_TEMP = "inverter_temperature"
SENSOR_WIFI_STRENGTH = "wifi_strength"
SENSOR_INVERTER_STATUS = "inverter_status"
SENSOR_OPERATING_MODE = "operating_mode"
SENSOR_SELF_CONSUMPTION_RATE = "self_consumption_rate"
SENSOR_SELF_SUFFICIENCY_RATE = "self_sufficiency_rate"

# Sensor Types - Device Info
SENSOR_MODEL = "model"
SENSOR_SERIAL_NUMBER = "serial_number"
SENSOR_FIRMWARE_VERSION = "firmware_version"
