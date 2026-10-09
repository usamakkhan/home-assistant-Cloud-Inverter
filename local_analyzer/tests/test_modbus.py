import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solarmax_analyzer.discovery import validate_host
from solarmax_analyzer.modbus import ModbusClient, interpret_registers
from solarmax_analyzer.profile import SPECS, decode_register_map, decode_value, read_profile_snapshot


class FakeSocket:
    def __init__(self, response: bytes):
        self.response = response
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def settimeout(self, _):
        pass

    def close(self):
        pass

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        result, self.response = self.response[:size], self.response[size:]
        return result


class ModbusTests(unittest.TestCase):
    def test_profile_reuses_static_metadata_for_ten_second_cycles(self):
        calls=[]
        model=b"SM-ONYX-UL-6KW".ljust(16,b"\0")
        model_words=list(struct.unpack(">8H",model))
        class Client:
            def __init__(self,*_args,**_kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*_args): pass
            def read_holding_registers(self,address,count,unit):
                calls.append((address,count,unit))
                registers=[0]*count
                if address==0x1A3B:
                    registers[0]=2
                    registers[0x1A48-0x1A3B]=1
                elif address==0x1A00:
                    registers=model_words
                return SimpleNamespace(
                    ok=True,registers=registers,error=None,exception_name=None,
                    to_dict=lambda:{"ok":True,"registers":registers,"interpretation":interpret_registers(registers)},
                )
        cache={}
        with patch("solarmax_analyzer.profile.ModbusClient",Client),patch("solarmax_analyzer.profile.time.sleep"):
            first=read_profile_snapshot("192.168.50.10",metadata_cache=cache)
            first_calls=len(calls)
            second=read_profile_snapshot("192.168.50.10",metadata_cache=cache)
        self.assertFalse(first["metadata_cached"])
        self.assertTrue(second["metadata_cached"])
        self.assertEqual(first["model"],"SM-ONYX-UL-6KW")
        self.assertEqual(first_calls,6)
        self.assertEqual(len(calls)-first_calls,4)

    def test_successful_holding_register_read(self):
        body = bytes([3, 4]) + struct.pack(">HH", 2301, 0xFFFF)
        frame = struct.pack(">HHHB", 1, 0, len(body) + 1, 1) + body
        fake = FakeSocket(frame)
        with patch("socket.create_connection", return_value=fake):
            result = ModbusClient("127.0.0.1").read_holding_registers(100, 2, 1)
        self.assertTrue(result.ok)
        self.assertEqual(result.registers, [2301, 65535])
        self.assertEqual(fake.sent[7], 3)

    def test_exception_response(self):
        body = bytes([0x83, 2])
        frame = struct.pack(">HHHB", 1, 0, len(body) + 1, 1) + body
        with patch("socket.create_connection", return_value=FakeSocket(frame)):
            result = ModbusClient("127.0.0.1").read_holding_registers(0, 1, 1)
        self.assertFalse(result.ok)
        self.assertEqual(result.exception_name, "illegal_data_address")

    def test_read_only_device_identification_parses_objects(self):
        vendor = b"Voltronic"
        product = b"Infini"
        body = bytes([0x2B, 0x0E, 0x01, 0x01, 0x00, 0x00, 0x02, 0x00, len(vendor)]) + vendor
        body += bytes([0x01, len(product)]) + product
        frame = struct.pack(">HHHB", 1, 0, len(body) + 1, 1) + body
        fake = FakeSocket(frame)
        with patch("socket.create_connection", return_value=fake):
            result = ModbusClient("127.0.0.1").read_device_identification(1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["objects"]["0"]["text"], "Voltronic")
        self.assertEqual(result["objects"]["1"]["text"], "Infini")
        self.assertEqual(fake.sent[7:], bytes([0x2B, 0x0E, 0x01, 0x00]))

    def test_session_reuses_one_tcp_connection(self):
        body1 = bytes([3, 2]) + struct.pack(">H", 10)
        body2 = bytes([3, 2]) + struct.pack(">H", 20)
        frame1 = struct.pack(">HHHB", 1, 0, len(body1) + 1, 1) + body1
        frame2 = struct.pack(">HHHB", 2, 0, len(body2) + 1, 1) + body2
        fake = FakeSocket(frame1 + frame2)
        with patch("socket.create_connection", return_value=fake) as connect:
            with ModbusClient("127.0.0.1") as client:
                first = client.read_holding_registers(100, 1, 1)
                second = client.read_holding_registers(101, 1, 1)
        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(connect.call_count, 1)

    def test_interpretation(self):
        value = interpret_registers([0x4142, 0xFFFF])
        self.assertEqual(value["ascii"], "AB..")
        self.assertEqual(value["signed16"], [16706, -1])
        self.assertEqual(value["uint32_big_endian"], [0x4142FFFF])

    def test_ip_literal_validation(self):
        self.assertEqual(validate_host("192.168.50.10"), "192.168.50.10")
        with self.assertRaises(ValueError):
            validate_host("example.com")

    def test_write_sized_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            ModbusClient("127.0.0.1").read_holding_registers(0, 126, 1)

    def test_profile_signed_and_scaled_values(self):
        registers = {
            0x1048: 0,
            0x1049: 45070,
            0x1300: 0xFFFF,
            0x1301: 0xA358,
            0x2000: 100,
        }
        decoded = decode_register_map(registers)
        self.assertEqual(decoded["pv_power"]["value"], 4507.0)
        self.assertEqual(decoded["grid_power"]["value"], -2372.0)
        self.assertEqual(decoded["battery_soc"]["value"], 100)

    def test_signed_32_bit_decode(self):
        self.assertEqual(decode_value([0xFFFF, 0xFF9C], "s32"), -100)

    def test_complete_documented_realtime_map(self):
        self.assertEqual(len(SPECS), 113)
        self.assertEqual(len({spec.key for spec in SPECS}), 113)

    def test_cloud_validated_gen_port_and_bms_fields(self):
        decoded = decode_register_map({
            0x136A: 2508,
            0x136B: 0,
            0x136C: 702,
            0x136D: 0,
            0x136E: 15773,
            0x1379: 5017,
            0x137A: 0,
            0x137B: 989,
            0x137C: 10,
            0x137D: 18146,
            0x2002: 193,
        })
        self.assertEqual(decoded["gen_port_voltage"]["value"], 250.8)
        self.assertEqual(decoded["gen_port_current"]["value"], 7.02)
        self.assertEqual(decoded["gen_port_power"]["value"], 1577.3)
        self.assertEqual(decoded["gen_port_frequency"]["value"], 50.17)
        self.assertEqual(decoded["gen_port_energy_today"]["value"], 9.89)
        self.assertEqual(decoded["gen_port_energy_total"]["value"], 6735.06)
        self.assertEqual(decoded["battery_bms_status"]["value"], 193)

    def test_mode_and_error_bit_decoding(self):
        decoded = decode_register_map({0x101D: 3, 0x101E: 0b1001})
        self.assertEqual(decoded["inverter_mode"]["label"], "On-grid")
        self.assertEqual(
            decoded["error_1"]["active_flags"],
            ["Inverter over DC-bias current", "Inverter over temperature"],
        )

    def test_mppt_capability_filter_avoids_reused_registers(self):
        decoded = decode_register_map(
            {0x1010: 2500, 0x1088: 165, 0x1089: 5609, 0x108A: 16, 0x108B: 32768},
            mppt_count=2,
        )
        self.assertIn("pv1_voltage", decoded)
        self.assertNotIn("pv7_voltage", decoded)
        self.assertNotIn("pv7_power", decoded)


if __name__ == "__main__":
    unittest.main()
