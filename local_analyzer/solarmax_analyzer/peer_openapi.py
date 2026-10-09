from __future__ import annotations

from typing import Any


def _json_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"type": "object", "additionalProperties": True}
            }
        },
    }


def _error_responses(*status_codes: int) -> dict[str, Any]:
    descriptions = {
        400: "Invalid request",
        403: "Local administration policy rejected the request",
        404: "Resource not found",
        409: "Operation conflicts with current state",
        500: "Unexpected service error",
    }
    return {
        str(code): {
            "description": descriptions[code],
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error"}
                }
            },
        }
        for code in status_codes
    }


def _get(
    operation_id: str,
    summary: str,
    *,
    parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "operationId": operation_id,
        "summary": summary,
        "responses": {
            "200": _json_response("Successful response"),
            **_error_responses(400, 404, 500),
        },
    }
    if parameters:
        operation["parameters"] = parameters
    return operation


def _post(operation_id: str, summary: str) -> dict[str, Any]:
    return {
        "operationId": operation_id,
        "summary": summary,
        "description": (
            "Available only to a loopback client using application/json and an "
            "approved local dashboard Origin. This operation never writes to an inverter."
        ),
        "x-local-only": True,
        "x-inverter-writes": False,
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object", "additionalProperties": True}
                }
            },
        },
        "responses": {
            "200": _json_response("Operation completed"),
            "201": _json_response("Telemetry sample accepted"),
            **_error_responses(400, 403, 409, 500),
        },
    }


def build_openapi_document(port: int) -> dict[str, Any]:
    """Return a tooling-friendly contract for the independent comparison API."""
    minutes = {
        "name": "minutes",
        "in": "query",
        "required": False,
        "schema": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 60},
        "description": "Trailing history window in minutes.",
    }
    device_id = {
        "name": "device_id",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "enum": ["primary", "neighbor"]},
        "description": "Primary SolarMax or configured neighbor stream.",
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Knox Neighbor Comparison API",
            "version": "1.0.0",
            "description": (
                "EyeBond callback / PI18 telemetry, normalized array comparison, and "
                "durable alerts. The collector uses read commands only; no Knox "
                "inverter-control or persistent logger-setting endpoint is exposed."
            ),
        },
        "servers": [{"url": f"http://127.0.0.1:{port}/v1"}],
        "paths": {
            "/": {"get": _get("getServiceRoot", "Service identity and discovery links")},
            "/status": {"get": _get("getStatus", "Protocol and collection status")},
            "/systems": {"get": _get("listSystems", "Both solar-array definitions")},
            "/systems/{device_id}/latest": {
                "get": _get("getLatestTelemetry", "Canonical latest telemetry", parameters=[device_id])
            },
            "/systems/{device_id}/history": {
                "get": _get(
                    "getTelemetryHistory",
                    "Independent telemetry history",
                    parameters=[device_id, minutes],
                )
            },
            "/comparison": {
                "get": _get(
                    "getComparison",
                    "Timestamp-aligned raw and normalized PV comparison",
                    parameters=[
                        minutes,
                        {
                            "name": "max_skew_seconds",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 120,
                                "default": 15,
                            },
                        },
                    ],
                )
            },
            "/alerts": {"get": _get("getAlerts", "Current evaluated alert states")},
            "/alerts/events": {
                "get": _get(
                    "getAlertEvents",
                    "Durable alert transition journal",
                    parameters=[{
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                    }],
                )
            },
            "/rules": {"get": _get("getAlertRules", "Alert rule configuration")},
            "/config": {"get": _get("getNeighborConfig", "Neighbor identity configuration")},
            "/admin/config": {
                "post": _post("updateNeighborConfig", "Update local neighbor configuration")
            },
            "/admin/probe": {
                "post": _post(
                    "probeNeighbor",
                    "Run one transient EyeBond callback and PI18 read-only fingerprint",
                )
            },
            "/admin/ingest": {
                "post": _post("ingestNeighborTelemetry", "Ingest a canonical analysis-tool sample")
            },
            "/admin/rules": {
                "post": _post("updateAlertRules", "Update alert rules atomically")
            },
        },
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {"error": {"type": "string"}},
                    "additionalProperties": False,
                }
            }
        },
    }
