#!/usr/bin/env python3
"""Build a gateway ``/apps`` config for a world from the apps it declares.

Datasets name their apps the way the authoring platform did ("Excel", "Word");
the OSS servers use their generic names (``spreadsheets``, ``documents``). This
module owns that mapping so a converter never has to hardcode it.

Usage:
    python build_mcp_config.py --world-id world_abc --worlds world_descriptions.json
    python build_mcp_config.py --all            # every OSS server
"""

import argparse
import json
import sys
from typing import Any

STDIO = {"transport": "stdio", "command": "uv", "args": ["run", "python", "main.py"]}


def _server(cwd: str, env: dict[str, str]) -> dict[str, Any]:
    return {**STDIO, "cwd": cwd, "env": {**env, "MCP_TRANSPORT": "stdio"}}


# Keyed by the service_id used across Mercor exports; the value is the server
# name the gateway namespaces tools under.
SERVERS: dict[str, tuple[str, dict[str, Any]]] = {
    "svc_a3ac7e47956c43048235dbd25d8c849d": (
        "calendar_server",
        _server(
            "/app/mcp_servers/calendar/mcp_servers/calendar_server",
            {"APP_CALENDAR_DATA_ROOT": "/.apps_data/calendar"},
        ),
    ),
    "svc_eec407c6dffc45579b7a4025f8439fe2": (
        "chat_server",
        _server(
            "/app/mcp_servers/chat/mcp_servers/chat_server",
            {"HAS_STATE": "true", "STATE_LOCATION": "/.apps_data/chat"},
        ),
    ),
    "svc_bd6a6280b337424cb5e6e4959301520f": (
        "code_execution_server",
        _server(
            "/app/mcp_servers/code/mcp_servers/code_execution_server",
            {"SANDBOX_ROOT": "/filesystem"},
        ),
    ),
    "svc_2293fbde36334312996ecfeaca4e978b": (
        "sheets_server",
        _server(
            "/app/mcp_servers/spreadsheets/mcp_servers/sheets_server",
            {"APP_SHEETS_ROOT": "/filesystem"},
        ),
    ),
    "svc_aba5e37188c745fba2bbd575545a9743": (
        "filesystem_server",
        _server(
            "/app/mcp_servers/filesystem/mcp_servers/filesystem_server",
            {"APP_FS_ROOT": "/filesystem", "SERVER_NAME": "filesystem_server"},
        ),
    ),
    "svc_56aff339e48c4f0aaa111988ca7c0b12": (
        "mail_server",
        _server(
            "/app/mcp_servers/mail/mcp_servers/mail_server",
            {"APP_MAIL_DATA_ROOT": "/.apps_data/mail"},
        ),
    ),
    "svc_bd0089edc9eb45df9b459b7b9d47f44f": (
        "pdf_server",
        _server(
            "/app/mcp_servers/pdfs/mcp_servers/pdf_server", {"APP_PDF_ROOT": "/filesystem"}
        ),
    ),
    "svc_8361cf10b2f84ed78225902d0a6a4255": (
        "slides_server",
        _server(
            "/app/mcp_servers/presentations/mcp_servers/slides_server",
            {"APP_SLIDES_ROOT": "/filesystem"},
        ),
    ),
    "svc_5d56252d4260473284737585ad91eeb3": (
        "docs_server",
        _server(
            "/app/mcp_servers/documents/mcp_servers/docs_server",
            {"APP_DOCS_ROOT": "/filesystem"},
        ),
    ),
    "svc_f5802ff259f6474b8f27bd11cd42e4fe": (
        "edgar_sec",
        _server(
            "/app/mcp_servers/edgar_sec/mcp_servers/edgar_sec",
            {
                "EDGAR_OFFLINE_MODE": "false",
                "EDGAR_USER_AGENT": "${EDGAR_USER_AGENT:-archipelago harbor@example.com}",
            },
        ),
    ),
    "svc_0f1a736de09143968916bf5816b9b36c": (
        "fmp_server",
        _server(
            "/app/mcp_servers/fmp/mcp_servers/fmp_server",
            {"FMP_OFFLINE_MODE": "false", "FMP_API_KEY": "${FMP_API_KEY}"},
        ),
    ),
}

# Fallback for exports that carry a display name but no service_id.
NAME_ALIASES: dict[str, str] = {
    "calendar": "svc_a3ac7e47956c43048235dbd25d8c849d",
    "chat": "svc_eec407c6dffc45579b7a4025f8439fe2",
    "code execution": "svc_bd6a6280b337424cb5e6e4959301520f",
    "excel": "svc_2293fbde36334312996ecfeaca4e978b",
    "spreadsheets": "svc_2293fbde36334312996ecfeaca4e978b",
    "filesystem": "svc_aba5e37188c745fba2bbd575545a9743",
    "mail": "svc_56aff339e48c4f0aaa111988ca7c0b12",
    "pdfs": "svc_bd0089edc9eb45df9b459b7b9d47f44f",
    "powerpoint": "svc_8361cf10b2f84ed78225902d0a6a4255",
    "presentations": "svc_8361cf10b2f84ed78225902d0a6a4255",
    "word": "svc_5d56252d4260473284737585ad91eeb3",
    "documents": "svc_5d56252d4260473284737585ad91eeb3",
    "edgar sec": "svc_f5802ff259f6474b8f27bd11cd42e4fe",
    "fmp": "svc_0f1a736de09143968916bf5816b9b36c",
}

# Servers that reach the public internet; a world using one cannot run offline.
NETWORK_SERVERS = frozenset({"edgar_sec", "fmp_server"})


def resolve(app: dict[str, str]) -> tuple[str, dict[str, Any]]:
    """Map one declared app onto its OSS server config."""
    entry = SERVERS.get(app.get("service_id", ""))
    if entry is None:
        alias = NAME_ALIASES.get(app.get("service_name", "").strip().lower())
        entry = SERVERS.get(alias or "")
    if entry is None:
        raise KeyError(
            f"no OSS MCP server for app {app!r};"
            " add it to harbor/tools/build_mcp_config.py"
        )
    return entry


def build_mcp_config(apps: list[dict[str, str]]) -> dict[str, Any]:
    servers = dict(resolve(app) for app in apps)
    return {"mcpServers": servers}


def requires_network(config: dict[str, Any]) -> bool:
    return bool(NETWORK_SERVERS & set(config.get("mcpServers", {})))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worlds", help="world_descriptions.json")
    parser.add_argument("--world-id")
    parser.add_argument("--all", action="store_true", help="emit every OSS server")
    args = parser.parse_args()

    if args.all:
        config = {"mcpServers": dict(SERVERS.values())}
    else:
        if not (args.worlds and args.world_id):
            parser.error("--worlds and --world-id are required unless --all is given")
        worlds = json.loads(open(args.worlds).read())
        world = next((w for w in worlds if w["world_id"] == args.world_id), None)
        if world is None:
            sys.exit(f"world not found: {args.world_id}")
        config = build_mcp_config(world.get("apps", []))

    json.dump(config, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
