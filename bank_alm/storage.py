"""Preserve full segment evidence in gzip while keeping the dashboard portable."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

SEGMENT_FIELDS = {"asset_segment_flows", "asset_segment_sales", "asset_segment_inventory"}


def compact_analysis(analysis: dict, *, for_report: bool = False) -> dict:
    def scenario(saved: dict) -> dict:
        result = dict(saved)
        result["monthly"] = [{key: value for key, value in row.items() if key not in SEGMENT_FIELDS} for row in saved["monthly"]]
        result["initial_event"] = {key: value for key, value in saved["initial_event"].items() if key not in SEGMENT_FIELDS}
        return result
    result = dict(analysis)
    result["scenarios"] = [scenario(s) for s in analysis["scenarios"]]
    result["policies"] = {**analysis["policies"], "candidates": [{**policy, "scenarios": [] if for_report else [scenario(s) for s in policy["scenarios"]]} for policy in analysis["policies"]["candidates"]]}
    result["policy_analysis"] = {**analysis["policy_analysis"], "scenarios": [scenario(s) for s in analysis["policy_analysis"]["scenarios"]]}
    if for_report:
        result["report_payload_scope"] = "Displayed scenario ledgers and policy summary rows. Complete policy and per-band ledgers are in the accompanying evidence files."
    return result


def write_gzip_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(pending, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(value, stream, separators=(",", ":"), allow_nan=False)
    pending.replace(path)


def compact_challenges(value: object) -> object:
    if isinstance(value, dict):
        return {key: compact_challenges(item) for key, item in value.items() if key not in SEGMENT_FIELDS}
    if isinstance(value, list):
        return [compact_challenges(item) for item in value]
    return value


def read_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)
