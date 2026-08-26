import argparse
import json
from pathlib import Path

from .db import SessionLocal
from .services.subscriptions import parse_subscription, sync_nodes


def main() -> None:
    parser = argparse.ArgumentParser(prog="nextgateway-subscription")
    parser.add_argument("command", choices=("inspect", "sync"))
    parser.add_argument("file", type=Path)
    parser.add_argument("--source-ref", default="provider-primary")
    arguments = parser.parse_args()
    parsed = parse_subscription(arguments.file.read_bytes())
    output = {
        "format": parsed.format,
        "protocol_counts": parsed.protocol_counts,
        "supported_nodes": len(parsed.nodes),
        "unsupported_count": parsed.unsupported_count,
        "invalid_count": parsed.invalid_count,
        "sha256": parsed.sha256,
    }
    if arguments.command == "sync":
        with SessionLocal() as session:
            diff = sync_nodes(session, parsed, arguments.source_ref)
        output["diff"] = {
            "added": diff.added,
            "updated": diff.updated,
            "unchanged": diff.unchanged,
            "missing": diff.missing,
        }
    print(json.dumps(output, sort_keys=True))
