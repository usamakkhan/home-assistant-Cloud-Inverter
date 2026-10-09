import struct
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from solarmax_analyzer.controls import ControlService, EXPECTED_MODEL, EXPECTED_SERIAL, catalog
from solarmax_analyzer.modbus import ModbusClient, ModbusProtocolError


def encoded(text):
    return list(struct.unpack(">8H",text.encode().ljust(16,b"\0")))


class FakeClient:
    def __init__(self):
        self.words = {0x1A00:encoded(EXPECTED_MODEL),0x1A10:encoded(EXPECTED_SERIAL),0x2100:[3],0x2115:[1]}
        self.writes = []
        self.fail_write = False
        self.mismatch = False

    def __enter__(self): return self
    def __exit__(self,*_): pass
    def read_holding_registers(self,address,count,unit):
        return SimpleNamespace(ok=True,registers=self.words.get(address,[0]*count),error=None)
    def write_single_register(self,address,value,unit):
        self.writes.append((address,value,unit))
        if self.fail_write: raise TimeoutError("response lost")
        if not self.mismatch: self.words[address]=[value]


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.client=FakeClient()
        self.collector=Mock()
        self.collector.status.return_value={"host":"192.168.50.10","unit_id":1,"mode":"local","interval_seconds":10,"quiet_window_seconds":45}
        @contextmanager
        def read_session():
            yield "192.168.50.10",1,7
        self.collector.temporary_read_session.side_effect=read_session
        self.factory=Mock(return_value=self.client)
        self.now=100
        self.service=ControlService(self.collector,threading.Lock(),enabled=True,client_factory=self.factory,clock=lambda:self.now)

    def test_defaults_disabled_and_catalog_does_not_invent_values(self):
        self.service.enabled=False
        with self.assertRaises(ValueError): self.service.prepare("grid_charge",0)
        self.factory.assert_not_called()
        self.assertTrue(all(row["current_value"] is None for row in catalog()))
        fields={r["key"]:r for r in catalog({0x2115:0,0x2124:1,0x2148:500})}
        self.assertEqual(fields["grid_charge"]["current_value"],0)
        self.assertEqual(fields["grid_end_voltage"]["current_value"],50)
        self.assertEqual(fields["capacity_mode"]["address"],0x2124)
        self.assertEqual(fields["gen_start"]["address"],0x212C)
        self.assertFalse(fields["gen_start"]["write_implemented"])
        self.assertEqual(next(r for r in catalog({0x2168:1,0x2169:2}) if r['key']=='schedule_1_charge_power')['current_value'],65538)

    def test_prepare_only_reads_then_apply_verifies_and_consumes_token(self):
        draft=self.service.prepare("work_mode",0)
        self.assertEqual(self.client.writes,[])
        result=self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        self.assertEqual(result["status"],"verified")
        self.assertEqual(self.client.writes,[(0x2100,0,1)])
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        self.assertEqual(len(self.client.writes),1)

    def test_unsupported_invalid_and_noop_changes_blocked(self):
        for key,value in (("capacity_mode",0),("gen_start",50),("grid_charge",True),("grid_charge",2),("work_mode",2),("work_mode",3)):
            with self.assertRaises(ValueError): self.service.prepare(key,value)
        self.assertEqual(self.client.writes,[])

    def test_identity_mismatch_blocks_prepare_and_apply(self):
        draft=self.service.prepare("grid_charge",0)
        self.client.words[0x1A10]=encoded("OTHER")
        with self.assertRaises(ValueError): self.service.prepare("grid_charge",0)
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        self.assertEqual(self.client.writes,[])

    def test_expired_unconfirmed_and_changed_value_never_write(self):
        draft=self.service.prepare("grid_charge",0)
        self.now+=91
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        draft=self.service.prepare("grid_charge",0)
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"yes")
        draft=self.service.prepare("grid_charge",0)
        self.client.words[0x2115]=[0]
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        self.assertEqual(self.client.writes,[])

    def test_maintenance_and_target_checks_are_repeated(self):
        draft=self.service.prepare("grid_charge",0)
        self.collector.ensure_maintenance.side_effect=ValueError("Original mode")
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        self.assertEqual(self.client.writes,[])
        self.collector.ensure_maintenance.side_effect=None
        draft=self.service.prepare("grid_charge",0)
        self.collector.status.return_value={"host":"192.168.50.99","unit_id":1}
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        self.assertEqual(self.client.writes,[])

    def test_write_timeout_is_unknown_and_never_retried(self):
        draft=self.service.prepare("grid_charge",0)
        self.client.fail_write=True
        with self.assertRaisesRegex(ValueError,"outcome_unknown"): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        with self.assertRaises(ValueError): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)
        self.assertEqual(len(self.client.writes),1)
        self.assertEqual(self.service.audit[-1]["status"],"outcome_unknown")

    def test_readback_mismatch_not_claimed_successful(self):
        draft=self.service.prepare("grid_charge",0)
        self.client.mismatch=True
        with self.assertRaisesRegex(ValueError,"readback_mismatch"): self.service.apply(draft["token"],"APPLY "+EXPECTED_SERIAL)

    def test_fc06_exact_echo_and_allowlist(self):
        from test_modbus import FakeSocket
        pdu=struct.pack(">BHH",6,0x2115,0)
        fake=FakeSocket(struct.pack(">HHHB",1,0,6,1)+pdu)
        with patch("socket.create_connection",return_value=fake):
            with ModbusClient("127.0.0.1") as client:
                client.write_single_register(0x2115,0,1)
                for address,value,unit in ((0x6001,1,1),(0x2115,0,0),(0x2115,9,1),(0x2100,2,1)):
                    with self.assertRaises(ValueError): client.write_single_register(address,value,unit)
        self.assertEqual(fake.sent[7:],pdu)

    def test_fc06_bad_echo_and_exception_rejected(self):
        from test_modbus import FakeSocket
        for pdu in (struct.pack(">BHH",6,0x2115,1),bytes([0x86,3])):
            fake=FakeSocket(struct.pack(">HHHB",1,0,len(pdu)+1,1)+pdu)
            with patch("socket.create_connection",return_value=fake):
                with ModbusClient("127.0.0.1") as client:
                    with self.assertRaises(ModbusProtocolError): client.write_single_register(0x2115,0,1)
            self.assertEqual(len(fake.sent),12)

    def test_settings_read_excludes_credentials_and_retains_partial_failures(self):
        original=self.client.read_holding_registers
        visited=[]
        def read(address,count,unit):
            visited.append((address,count))
            if address in (0x1A00,0x1A10): return original(address,count,unit)
            if address==0x214C: return SimpleNamespace(ok=False,registers=None,error="unsupported",exception_name=None)
            values=[0]*count
            if address==0x2122:
                values[0x212C-address]=80
                values[0x212D-address]=60
            return SimpleNamespace(ok=True,registers=values,error=None)
        self.client.read_holding_registers=read
        with patch("solarmax_analyzer.controls.time.sleep"):
            result=self.service.read()
        self.assertEqual(len(result["errors"]),1)
        self.assertEqual(next(f for f in result["fields"] if f["key"]=="gen_start")["current_value"],80)
        self.assertIsNone(next(f for f in result["fields"] if f["key"]=="time_control")["current_value"])
        self.assertTrue(all(a<0x3000 for a,_ in visited))
        self.assertEqual(self.client.writes,[])
        self.collector.ensure_maintenance.assert_not_called()
        self.assertGreaterEqual(self.collector.ensure_read_session.call_count,9)

    def test_editing_session_pauses_and_restores_collection_without_writing(self):
        self.service.enabled=False
        started=self.service.begin_session("ENABLE "+EXPECTED_SERIAL)
        self.assertTrue(started["enabled"])
        self.assertTrue(started["session_active"])
        self.assertEqual(started["resume_mode"],"local")
        self.collector.set_mode.assert_called_once_with("maintenance",confirmed=True)
        self.assertEqual(self.client.writes,[])
        self.collector.status.return_value={"host":"192.168.50.10","unit_id":1,"mode":"maintenance","interval_seconds":10,"quiet_window_seconds":45}
        ended=self.service.end_session()
        self.assertFalse(ended["enabled"])
        self.collector.set_mode.assert_called_with("local",interval_seconds=10,quiet_window_seconds=45,confirmed=True)
        self.assertEqual(self.client.writes,[])

    def test_editing_session_requires_exact_acknowledgement(self):
        self.service.enabled=False
        with self.assertRaises(ValueError):
            self.service.begin_session("yes")
        self.collector.set_mode.assert_not_called()
        self.assertFalse(self.service.enabled)

    def test_catalog_coverage_unique_addresses_and_valid_time_decoding(self):
        rows=catalog({0x2102:0xFFFF,0x2103:0x173B})
        self.assertEqual(len(rows),194)
        self.assertEqual(len({r["address"] for r in rows}),len(rows))
        self.assertIsNone(next(r for r in rows if r["key"]=="schedule_1_charge_start")["current_value"])
        self.assertEqual(next(r for r in rows if r["key"]=="schedule_1_charge_end")["current_value"],"23:59")
        self.assertEqual(sum(r["write_implemented"] for r in rows),2)


if __name__ == "__main__": unittest.main()
