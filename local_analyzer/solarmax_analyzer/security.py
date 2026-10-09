from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from .discovery import check_tcp, validate_host
from .modbus import ModbusClient


# This is deliberately a small, low-rate service check. The Wi-Fi bridge has
# already shown that connection bursts can make it temporarily unresponsive.
SELECTED_PORTS: tuple[tuple[int, str], ...] = (
    (21, "FTP"),
    (22, "SSH"),
    (23, "Telnet"),
    (53, "DNS"),
    (80, "HTTP"),
    (443, "HTTPS"),
    (502, "Modbus/TCP"),
    (802, "Modbus Security/TLS"),
    (1883, "MQTT"),
    (8080, "Alternate HTTP"),
    (8883, "MQTT/TLS"),
    (8899, "Common serial/Wi-Fi bridge"),
    (10000, "Common device service"),
)


def build_findings(
    open_ports: set[int],
    modbus_read: dict[str, Any],
    observed_rate_instability: bool = True,
) -> list[dict[str, Any]]:
    readable = bool(modbus_read.get("ok"))
    findings: list[dict[str, Any]] = []

    if readable:
        findings.extend(
            (
                {
                    "id": "SMX-LOCAL-001",
                    "severity": "high",
                    "status": "confirmed",
                    "title": "Unauthenticated operational-data access",
                    "evidence": (
                        "A function-03 holding-register request returned inverter "
                        "data without credentials or a session handshake."
                    ),
                    "impact": (
                        "Any host that can reach TCP 502 can read operating state, "
                        "energy data, device identity, and readable configuration."
                    ),
                    "remediation": (
                        "Restrict TCP 502 with a firewall allow-list to the Home "
                        "Assistant collector and place the inverter on an isolated IoT VLAN."
                    ),
                },
                {
                    "id": "SMX-LOCAL-002",
                    "severity": "high",
                    "status": "confirmed",
                    "title": "Plaintext, unauthenticated Modbus/TCP",
                    "evidence": (
                        "The audit exchanged a valid bare Modbus/TCP frame on port "
                        "502. No TLS or message authentication was used."
                    ),
                    "impact": (
                        "A device on the same reachable network can observe or alter "
                        "traffic in transit and can impersonate a client."
                    ),
                    "remediation": (
                        "Do not route port 502 outside the trusted collector segment. "
                        "Use firewalling or a secure gateway/VPN where traffic crosses networks."
                    ),
                },
            )
        )

    if 502 in open_ports and 802 not in open_ports:
        findings.append(
            {
                "id": "SMX-LOCAL-003",
                "severity": "medium",
                "status": "confirmed",
                "title": "Secure Modbus/TLS service not exposed",
                "evidence": (
                    "TCP 502 was reachable while the standard Modbus Security port "
                    "802 did not accept a connection during the selected-port check."
                ),
                "impact": "The local interface offers no detected encrypted Modbus alternative.",
                "remediation": (
                    "Compensate with network segmentation and an allow-list. If the "
                    "vendor supplies authenticated TLS firmware, prefer it after validation."
                ),
            }
        )

    findings.extend(
        (
            {
                "id": "SMX-LOCAL-004",
                "severity": "high",
                "status": "not tested",
                "title": "Potential unauthenticated control writes",
                "evidence": (
                    "The vendor register map labels operating-mode, power-limit, and "
                    "inverter-control registers as read/write. This analyzer did not send a write."
                ),
                "impact": (
                    "If the bridge accepts those write functions without authorization, "
                    "a reachable host could change inverter behavior or stop output."
                ),
                "remediation": (
                    "Treat TCP 502 as a control interface even when Home Assistant only "
                    "reads it; permit only the collector and block all other clients."
                ),
            },
            {
                "id": "SMX-LOCAL-005",
                "severity": "high",
                "status": "not tested",
                "title": "Potential Wi-Fi credential exposure in register map",
                "evidence": (
                    "The documented map marks Wi-Fi SSID register 0x3060 and password "
                    "register 0x3070 as read/write. The audit deliberately did not read either block."
                ),
                "impact": (
                    "If readable through the unauthenticated bridge, stored network "
                    "credentials could be disclosed to any host with port-502 access."
                ),
                "remediation": (
                    "Isolate the module, use a dedicated IoT SSID with no access to "
                    "trusted devices, and rotate that credential if exposure is suspected."
                ),
            },
        )
    )

    if observed_rate_instability:
        findings.append(
            {
                "id": "SMX-LOCAL-006",
                "severity": "medium",
                "status": "observed",
                "title": "Service availability degrades under request bursts",
                "evidence": (
                    "During earlier read-only discovery, rapid short-lived connections "
                    "made the ESP-based bridge temporarily unresponsive. The audit did not repeat a stress test."
                ),
                "impact": (
                    "Aggressive polling or a noisy LAN client may interrupt telemetry "
                    "and possibly the vendor cloud connection."
                ),
                "remediation": (
                    "Use one collector, keep reads serialized, start with a 2-5 second "
                    "poll interval, and back off after timeouts."
                ),
            }
        )

    findings.append(
        {
            "id": "SMX-LOCAL-007",
            "severity": "info",
            "status": "observed externally",
            "title": "Periodic dependency on vendor cloud DNS",
            "evidence": (
                "AdGuard Home shows this module resolving www.cloudinverter.net about "
                "every five minutes. This audit did not intercept or decrypt cloud traffic."
            ),
            "impact": (
                "Cloud data content, transport encryption, authentication, and server "
                "behavior remain outside this local Modbus assessment."
            ),
            "remediation": (
                "Monitor DNS and egress destinations. Block cloud egress only after "
                "confirming that local telemetry and required inverter functions remain stable."
            ),
        }
    )
    return findings


def run_security_audit(host: str, unit_id: int = 1) -> dict[str, Any]:
    """Run a non-invasive assessment: connect checks plus one FC03 read.

    It never reads the credential blocks, sends a Modbus write, brute-forces a
    service, fingerprints a banner, or performs a load/denial-of-service test.
    """
    host = validate_host(host)
    if not 0 <= unit_id <= 255:
        raise ValueError("unit_id must be between 0 and 255")

    started = time.perf_counter()
    services = []
    for index, (port, name) in enumerate(SELECTED_PORTS):
        result = check_tcp(host, port=port, timeout=0.25)
        services.append(
            {
                "port": port,
                "service": name,
                "open": result["ok"],
                "elapsed_ms": result["elapsed_ms"],
                "error": result.get("error"),
            }
        )
        if index != len(SELECTED_PORTS) - 1:
            time.sleep(0.08)

    # Give the small bridge a pause after the connection checks, then make one
    # read that proves whether the exposed service actually speaks Modbus.
    time.sleep(0.75)
    model_read = ModbusClient(host, timeout=1.5).read_holding_registers(
        0x1A00, 8, unit_id
    ).to_dict()
    open_ports = {item["port"] for item in services if item["open"]}
    findings = build_findings(open_ports, model_read)
    severity_counts = {
        severity: sum(item["severity"] == severity for item in findings)
        for severity in ("critical", "high", "medium", "low", "info")
    }

    return {
        "ok": True,
        "host": host,
        "unit_id": unit_id,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "scope": {
            "safe": True,
            "actions": [
                "low-rate TCP connect checks on 13 selected ports",
                "one Modbus function-03 read of the model-identification block",
            ],
            "excluded": [
                "all Modbus writes",
                "Wi-Fi SSID/password register reads",
                "credential guessing",
                "denial-of-service or burst testing",
                "firmware extraction and CVE confirmation",
                "cloud-traffic interception or decryption",
            ],
        },
        "services": services,
        "modbus_evidence": model_read,
        "severity_counts": severity_counts,
        "findings": findings,
        "limitations": [
            "Closed means no TCP connection was accepted during this single check; it does not prove the service never exists.",
            "Potential write and credential findings come from the documented register permissions and remain deliberately untested.",
            "This is a local configuration/protocol assessment, not a firmware reverse-engineering or comprehensive penetration test.",
        ],
    }
