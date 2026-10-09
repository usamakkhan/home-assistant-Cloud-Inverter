"""Evidence-backed settings catalog and narrowly opt-in physical controls.

CloudInverter's public GroupDevice bundle is the primary source for portal
fields. A source mapping is NOT proof that a particular firmware supports it.
No arbitrary-address write API is exposed. See CONTROL_RESEARCH.md.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import secrets
import threading
import time

from .modbus import ModbusClient
from .features import FEATURES

PORTAL_SOURCE = "https://www.cloudinverter.net/dist/p__GroupDevice__index.d67a3a6e.async.js"
PROTOCOL_SOURCE = "https://sunvec.es/wp-content/uploads/2023/05/Modbus-Protocol-V1.2.pdf"
EXPECTED_MODEL = "SM-ONYX-UL-6KW"
EXPECTED_SERIAL = "ABCDE123456789"


def field(key, name, address, group="Remote settings", kind="number", *, unit="", scale=1, options=None, gate=None, notes="", words=1):
    return dict(key=key, name=name, address=address, address_hex=f"0x{address:04X}" if address is not None else "Unresolved",
                group=group, kind=kind, unit=unit, scale=scale, options=options, protocol_gate=gate, notes=notes,
                words=words, source=PORTAL_SOURCE, evidence="Portal source mapped", write_implemented=key in ("work_mode", "grid_charge"))


CONTROL_FIELDS = [
    field("work_mode", "Work mode", 0x2100, kind="select", options={0:"Self-consumption",1:"Feed-in priority",3:"Back-up mode"}, notes="Portal offers legacy time-based mode (2) only below protocol value 1047. It is not offered as a local write."),
    field("time_control", "Time-based Control", 0x214C, kind="select", options={0:"Off",1:"On"}, gate=1047),
    field("capacity_mode", "Capacity Mode", 0x2124, kind="select", options={0:"SOC (%)",1:"Voltage (V)"}, gate=1049, notes="Battery threshold basis, not AC output voltage or frequency."),
    field("grid_charge", "Charge by Grid", 0x2115, kind="select", options={0:"Off",1:"On"}, notes="Changes grid consumption. Existing battery limits remain in force."),
    field("grid_end_soc", "Grid charge end SOC", 0x2117, unit="%", notes="Used with SOC capacity mode and grid charging enabled."),
    field("grid_end_voltage", "Grid charge end voltage", 0x2148, unit="V", scale=10, gate=1049, notes="Used with voltage capacity mode and grid charging enabled."),
]
for slot in range(3):
    base = 0x2101 + slot * 5
    extended = 0x2168 + slot * 8
    group = f"Charge / discharge schedule {slot + 1}"
    CONTROL_FIELDS.append(field(f"schedule_{slot+1}_repeat", "Recurrence", base, group, "select", options={0:"Once",1:"Every day"}))
    for offset, key, label in ((1,"charge_start","Charge start"),(2,"charge_end","Charge end"),(3,"discharge_start","Discharge start"),(4,"discharge_end","Discharge end")):
        CONTROL_FIELDS.append(field(f"schedule_{slot+1}_{key}", label, base+offset, group, "time"))
    for offset, key, label, unit, scale, words in ((0,"charge_power","Maximum charge power","W",1,2),(2,"charge_soc","Charge end SOC","%",1,1),(3,"charge_voltage","Charge end voltage","V",10,1),(4,"discharge_power","Maximum discharge power","W",1,2),(6,"discharge_soc","Discharge end SOC","%",1,1),(7,"discharge_voltage","Discharge end voltage","V",10,1)):
        CONTROL_FIELDS.append(field(f"schedule_{slot+1}_{key}",label,extended+offset,group,unit=unit,scale=scale,words=words,gate=1049,notes="Firmware branch and SOC/voltage mode determine applicability; not enabled for local writes."))

# The newer portal branch has packed schedule flags and up to six time slots.
# Inventory the branch without pretending that it applies to this inverter.
for slot in range(6):
    CONTROL_FIELDS.append(field(f"new_schedule_{slot+1}", f"New-generation time slot {slot+1}", 0x2600+slot*8,
                                "Other firmware branches", "readonly", words=8,
                                notes="Packed mode, recurrence/day mask, start/end, 32-bit power, SOC, voltage and date. Portal chooses 3 or 6 slots by firmware family; not read or enabled on this model."))
def protocol_field(key,name,address,group="Protocol candidates",kind="readonly",**kwargs):
    item=field(key,name,address,group,kind,**kwargs)
    item.update(source=PROTOCOL_SOURCE,evidence="APD v1.2 documented; device verification pending",write_implemented=False)
    return item


for key,name,address,unit,scale in (
    ("gen_mode","GEN port mode (code meanings unverified)",0x2122,"",1),
    ("gen_min_pv","Minimum PV power for smart load on",0x212B,"W",1),
    ("gen_start","Smart-load turn-on SOC",0x212C,"%",1),
    ("gen_stop","Smart-load turn-off SOC",0x212D,"%",1),
    ("gen_grid","Smart load always on with grid (0/1)",0x212E,"",1),
    ("gen_start_voltage","Smart-load turn-on voltage",0x2130,"V",10),
    ("gen_stop_voltage","Smart-load turn-off voltage",0x2131,"V",10),
):
    CONTROL_FIELDS.append(protocol_field(key,name,address,"GEN · AC, Heater & Water Geyser","number",unit=unit,scale=scale,
        notes="Documented smart-load/GEN parameter. Verify port mode, capacity basis, threshold relationship and firmware on this installation before enabling writes."))

# All remaining hybrid parameter addresses in APD v1.2, excluding entries
# already represented by portal fields or the original read-back inventory.
for address,name,unit,scale in (
    (0x2110,"Battery chemistry / BMS type","",1),(0x2111,"BMS communication address","",1),
    (0x2112,"Lead-acid battery capacity","Ah",1),(0x2113,"Lead-acid discharge cutoff","V",10),(0x2114,"Lead-acid charge cutoff","V",10),
    (0x2123,"Lithium battery activation","",1),(0x2125,"Maximum grid input","W",1),
    (0x2126,"Maximum generator charging","W",1),(0x2127,"Maximum generator input","W",1),(0x2128,"Generator connected to grid port","",1),
    (0x2129,"Generator start SOC","%",1),(0x212A,"Generator stop SOC","%",1),
    (0x212F,"Off-grid startup voltage","V",10),(0x2132,"Backup minimum output voltage","V",10),(0x2133,"Backup maximum output voltage","V",10),
    (0x2134,"Generator start battery voltage","V",10),(0x2135,"Generator stop battery voltage","V",10),
    (0x2136,"Generator maximum runtime","min",1),(0x2137,"Generator downtime","min",1),
    (0x2138,"Inverter turn-on SOC","%",1),(0x2139,"Inverter turn-off SOC","%",1),
    (0x213A,"Inverter turn-on voltage","V",10),(0x213B,"Inverter turn-off voltage","V",10),(0x213C,"AC-coupled high frequency","Hz",100),
    (0x2141,"Normal-load support","",1),(0x2143,"Parallel operation","",1),
    (0x2144,"Forced charging start SOC","%",1),(0x2145,"Forced charging end SOC","%",1),
    (0x2146,"Forced charging start voltage","V",10),(0x2147,"Forced charging end voltage","V",10),
    (0x2149,"Grid feed-in enable","",1),(0x2150,"Maximum forced grid charging","W",1),
):
    CONTROL_FIELDS.append(protocol_field(f"protocol_{address:04x}",name,address,unit=unit,scale=scale,
        notes="Documented parameter, not a verified setting for this firmware or battery. Generator input is distinct from the user's GEN smart-load output."))

# Shared inverter controls: inventory only. No automatic read of these ranges,
# no Wi-Fi credential extraction, and no protection/EEPROM or shutdown writes.
SHARED_PARAMETERS = [
    (0x3000,"Clock year"),(0x3001,"Clock month/day"),(0x3002,"Clock hour/minute"),(0x3003,"Clock second"),
    (0x303E,"Modbus unit address"),(0x304C,"RS485 baud rate"),(0x3060,"Wi-Fi network name"),(0x3070,"Wi-Fi password (never read here)"),
    (0x30B0,"Meter address"),(0x30B1,"Meter model"),(0x30B2,"Meter power direction"),(0x30B3,"Power limit source"),(0x30B4,"CT ratio"),(0x30B5,"Meter position"),(0x30B9,"Maximum grid export power"),
    (0x5000,"First grid connection delay"),(0x5001,"Grid reconnection delay"),
    (0x5018,"Ten-minute sustained-voltage limit"),(0x5019,"Reconnect power ramp"),(0x501A,"Over-frequency droop"),(0x501B,"Insulation resistance threshold"),(0x501E,"Over-voltage derating point"),
    (0x501F,"High-frequency trip time high word"),(0x5020,"Low-frequency trip time high word"),
    (0x5021,"Over-frequency derating start"),(0x5022,"Over-frequency derating end"),(0x5025,"High-voltage trip time high word"),(0x5026,"Low-voltage trip time high word"),(0x5029,"First-connection power ramp"),
    (0x5030,"Reactive power mode"),(0x5031,"Static power factor"),(0x5033,"Reactive response time"),
    (0x5063,"Low-voltage ride-through threshold"),(0x5064,"High-voltage ride-through threshold"),(0x5065,"Fault ride-through mode"),(0x5066,"FRT zero-current trigger"),(0x5067,"FRT voltage-jump trigger"),
    (0x506C,"Level-2 high-frequency trip time high word"),(0x506D,"Level-2 low-frequency trip time high word"),
    (0x507F,"Over-frequency reference power"),(0x5081,"Under-frequency power-rise start"),(0x5082,"Under-frequency power-rise end"),(0x5083,"Under-frequency droop"),(0x5084,"Under-frequency reference power"),
    (0x5101,"Grid regulation profile"),(0x5104,"Static output derating"),(0x5106,"MPPT shade management"),(0x5107,"Shade-management interval"),
    (0x510E,"Anti-islanding detection"),(0x5112,"Low-voltage ride-through detection"),(0x5114,"Static reactive power"),(0x5115,"Resistance adjustment"),(0x5117,"Insulation-resistance detection"),(0x5118,"Ground-current detection"),(0x511D,"High-grid-voltage load derating"),
    (0x6001,"Inverter power on / shutdown"),(0x600F,"Dynamic power factor"),(0x6010,"Dynamic reactive power"),
]
for level,base in ((1,0x5002),(2,0x500A)):
    for offset,category in enumerate(("High frequency","Low frequency","High voltage","Low voltage")):
        SHARED_PARAMETERS.extend(((base+offset,f"{category} level {level} limit"),(base+4+offset,f"{category} level {level} trip-time low word")))
for base,label in ((0x503C,"Volt-VAR node voltage"),(0x5040,"Volt-VAR node reactive setting"),(0x505A,"Watt-VAR node power"),(0x505E,"Watt-VAR node reactive setting")):
    SHARED_PARAMETERS.extend((base+i,f"{label} {i+1}") for i in range(4))
for base,label in ((0x5049,"Volt-Watt charge derating voltage"),(0x504B,"Volt-Watt output derating voltage"),(0x504D,"Volt-Watt charge percentage"),(0x504F,"Volt-Watt output percentage")):
    SHARED_PARAMETERS.extend((base+i,f"{label} {i+1}") for i in range(2))
for address,name in SHARED_PARAMETERS:
    CONTROL_FIELDS.append(protocol_field(f"shared_{address:04x}",name,address,"Advanced shared parameters",
        notes="Inventory only; not read by this settings panel. Firmware applicability, electrical protection requirements, scaling and permitted values must be validated. Credential fields are intentionally excluded from reads."))


for feature in FEATURES:
    if any(s["address"] == feature.address for s in CONTROL_FIELDS):
        continue
    item = field("advanced_"+feature.key,feature.name,feature.address,"Protocol candidates","readonly",notes=feature.notes)
    item.update(source=PROTOCOL_SOURCE,evidence="Protocol read-back candidate; not portal-validated",risk=feature.risk)
    CONTROL_FIELDS.append(item)


def catalog(raw=None, enabled=False):
    raw = raw or {}
    result = []
    for spec in CONTROL_FIELDS:
        row = dict(spec)
        words = [raw.get(spec["address"] + i) for i in range(spec["words"])] if spec["address"] is not None else []
        value = None
        if spec["kind"] != "readonly" and words and all(w is not None for w in words):
            if spec["kind"] == "time":
                hour, minute = words[0] >> 8, words[0] & 255
                value = f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else None
            elif len(words) == 1:
                value = words[0] / spec["scale"] if spec["scale"] != 1 else words[0]
            elif len(words) == 2:
                value = (words[0] << 16) + words[1]  # portal Hm(high, low); not telemetry word order
        row.update(current_value=value, raw_words=words, upload_enabled=enabled and spec["write_implemented"],
                   write_tested_on_device=False)
        result.append(row)
    return result


def ascii_words(words):
    return b"".join(w.to_bytes(2,"big") for w in words).decode("ascii",errors="replace").strip("\0 ")


def read_words(client, address, count, unit):
    result = client.read_holding_registers(address,count,unit)
    if not result.ok or result.registers is None or len(result.registers) != count:
        raise ValueError(f"Read failed at 0x{address:04X}: {result.error or result.exception_name or 'incomplete response'}")
    return result.registers


class ControlService:
    def __init__(self, collector, io_lock, *, enabled=False, client_factory=ModbusClient, clock=time.monotonic):
        self.collector, self.io_lock = collector, io_lock
        self.enabled, self.client_factory, self.clock = enabled, client_factory, clock
        self.session_active = False
        self.resume_state = None
        self.pending = {}
        self.audit = deque(maxlen=100)
        self.lock = threading.Lock()

    def _write_target(self):
        self.collector.ensure_maintenance()
        state = self.collector.status()
        if not 1 <= state["unit_id"] <= 247:
            raise ValueError("Controls require a unicast unit 1..247")
        return state["host"], state["unit_id"]

    def session_status(self):
        with self.lock:
            resume_mode = self.resume_state.get("mode") if self.resume_state else None
            return {
                "enabled": self.enabled,
                "session_active": self.session_active,
                "resume_mode": resume_mode,
            }

    def begin_session(self, confirmation):
        if confirmation != f"ENABLE {EXPECTED_SERIAL}":
            raise ValueError("Confirm the physical-inverter editing session first")
        with self.lock:
            if self.session_active:
                return self.session_status_unlocked()
            previous = self.collector.status()
            self.collector.set_mode("maintenance", confirmed=True)
            self.resume_state = {
                "mode": previous["mode"],
                "interval_seconds": previous["interval_seconds"],
                "quiet_window_seconds": previous["quiet_window_seconds"],
            }
            self.enabled = True
            self.session_active = True
            self.pending = {}
            self.audit.append({
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "status": "editing_session_started",
                "resume_mode": previous["mode"],
            })
            return self.session_status_unlocked()

    def session_status_unlocked(self):
        resume_mode = self.resume_state.get("mode") if self.resume_state else None
        return {
            "enabled": self.enabled,
            "session_active": self.session_active,
            "resume_mode": resume_mode,
        }

    def end_session(self):
        with self.lock:
            previous = dict(self.resume_state) if self.resume_state else None
            was_active = self.session_active
            self.enabled = False
            self.session_active = False
            self.resume_state = None
            self.pending = {}
            if was_active:
                self.audit.append({
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "status": "editing_session_ended",
                    "resume_mode": previous.get("mode") if previous else None,
                })
        current = self.collector.status()
        if was_active and previous and current["mode"] == "maintenance":
            mode = previous["mode"]
            self.collector.set_mode(
                mode,
                interval_seconds=previous["interval_seconds"],
                quiet_window_seconds=previous["quiet_window_seconds"],
                confirmed=mode != "original",
            )
        return self.session_status()

    def _identity(self, client, unit):
        model = ascii_words(read_words(client,0x1A00,8,unit))
        serial = ascii_words(read_words(client,0x1A10,8,unit))
        if model != EXPECTED_MODEL or serial != EXPECTED_SERIAL:
            raise ValueError("Device identity differs from the configured inverter; controls blocked")
        return dict(model=model,serial=serial)

    def read(self):
        raw, errors = {}, []
        with self.collector.temporary_read_session() as (host, unit, generation):
            if not 1 <= unit <= 247:
                raise ValueError("Settings reads require a unicast unit 1..247")
            with self.io_lock, self.client_factory(host,timeout=2) as client:
                self.collector.ensure_read_session(generation)
                identity = self._identity(client,unit)
                for index, (address,count) in enumerate(((0x1A18,1),(0x2100,34),(0x2122,27),(0x2141,1),(0x2143,7),(0x214C,1),(0x2150,1),(0x2168,24))):
                    self.collector.ensure_read_session(generation)
                    try:
                        raw.update({address+i:v for i,v in enumerate(read_words(client,address,count,unit))})
                    except ValueError as exc:
                        errors.append(str(exc))
                    if index != 7:
                        time.sleep(1)
        return dict(identity=identity,captured_at=datetime.now(timezone.utc).isoformat(),protocol_raw=raw.get(0x1A18),
                    fields=catalog(raw,self.enabled),errors=errors,read_only=True)

    def prepare(self, key, value):
        if not self.enabled:
            raise ValueError("Physical uploads are disabled. Start an editing session in the local Controls page; no change was sent.")
        spec = next((s for s in CONTROL_FIELDS if s["key"] == key), None)
        if not spec or not spec["write_implemented"]:
            raise ValueError("This control is not enabled for local writes")
        if type(value) is not int or value not in spec["options"]:
            raise ValueError("Invalid control value")
        host,unit = self._write_target()
        with self.io_lock, self.client_factory(host,timeout=2) as client:
            identity = self._identity(client,unit)
            old = read_words(client,spec["address"],1,unit)[0]
        if old not in spec["options"]:
            raise ValueError("Current value is not in the validated options; control blocked")
        if old == value:
            raise ValueError("No change: the inverter already reports this value")
        token = secrets.token_urlsafe(32)
        draft = dict(key=key,name=spec["name"],address=spec["address"],old=old,value=value,host=host,unit=unit,
                     identity=identity,expires=self.clock()+90,old_label=spec["options"][old],new_label=spec["options"][value])
        with self.lock:
            self.pending = {token:draft}  # supersede any previous review
        return dict(token=token,expires_in_seconds=90,**{k:v for k,v in draft.items() if k != "expires"})

    def apply(self, token, confirmation):
        if not self.enabled:
            raise ValueError("Physical uploads are disabled")
        with self.lock:
            draft = self.pending.pop(token,None)  # consumed even if I/O fails; never auto-retry writes
        if not draft or self.clock() > draft["expires"]:
            raise ValueError("Review expired or already used; review the change again")
        if confirmation != f"APPLY {EXPECTED_SERIAL}":
            raise ValueError("Exact confirmation is required")
        host,unit = self._write_target()
        if (host,unit) != (draft["host"],draft["unit"]):
            raise ValueError("Collector target changed; review again")
        event = dict(recorded_at=datetime.now(timezone.utc).isoformat(),key=draft["key"],before=draft["old"],requested=draft["value"],status="not_sent")
        try:
            with self.io_lock, self.client_factory(host,timeout=2) as client:
                self._identity(client,unit)
                old = read_words(client,draft["address"],1,unit)[0]
                if old != draft["old"]:
                    raise ValueError("Setting changed since review; nothing written")
                self.collector.ensure_maintenance()
                event["status"] = "outcome_unknown"
                client.write_single_register(draft["address"],draft["value"],unit)
                actual = read_words(client,draft["address"],1,unit)[0]
                event.update(readback=actual,status="verified" if actual == draft["value"] else "readback_mismatch")
                if actual != draft["value"]:
                    raise ValueError("Write acknowledged but read-back differs. Do not retry automatically; check the inverter.")
        except Exception as exc:
            event["error"] = str(exc)
            raise ValueError(f"{event['status']}: {exc}") from exc
        finally:
            with self.lock:
                self.audit.append(event)
        return event
