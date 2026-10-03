"""Extract a dated Fed fitted curve from a verified, pinned source archive.

Normal use is offline. --from-treasury-snapshot imports the user's existing
Treasury project archive once; later builds have no dependency on that project.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "fed_curve"
SOURCE_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
NODES = [1 / 12, 0.25, 0.5, 1, 2, 3, 4, 5, 7, 10, 15, 20, 25, 30]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def zero_rate(parameters: dict, tenor: float) -> float:
    b0, b1, b2, b3 = [parameters[f"BETA{i}"] for i in range(4)]
    x1, x2 = tenor / parameters["TAU1"], tenor / parameters["TAU2"]
    l1, l2 = -math.expm1(-x1) / x1, -math.expm1(-x2) / x2
    return (b0 + b1 * l1 + b2 * (l1 - math.exp(-x1)) + b3 * (l2 - math.exp(-x2))) / 100


def prepare(as_of: str, import_directory: Path | None = None, *, write: bool = True, root: Path = ROOT) -> dict:
    raw_directory = root / "data" / "raw" / "fed_curve"
    requested = date.fromisoformat(as_of)
    if import_directory:
        origin = import_directory.resolve()
        archived = (origin / "feds200628.csv.gz").read_bytes()
        source = read_json(origin / "source_manifest.json")
        manifest = read_json(origin / "archive_manifest.json")
        if sha(archived) != manifest["archive_sha256"]:
            raise ValueError("Original Treasury archive SHA-256 does not match its manifest")
        if sha(gzip.decompress(archived)) != source["sha256"]:
            raise ValueError("Original Federal Reserve CSV does not match its acquisition manifest")
        raw_directory.mkdir(parents=True, exist_ok=True)
        for name in ("feds200628.csv.gz", "source_manifest.json", "archive_manifest.json"):
            shutil.copyfile(origin / name, raw_directory / name)

    archived = (raw_directory / "feds200628.csv.gz").read_bytes()
    manifest = read_json(raw_directory / "archive_manifest.json")
    source = read_json(raw_directory / "source_manifest.json")
    if source["source_url"] != SOURCE_URL:
        raise ValueError("Unrecognized Federal Reserve source URL")
    if sha(archived) != manifest["archive_sha256"] or len(archived) != manifest["archive_bytes"]:
        raise ValueError("Pinned Federal Reserve archive is inconsistent")
    if sha((raw_directory / "source_manifest.json").read_bytes()) != manifest["source_manifest_sha256"]:
        raise ValueError("Federal Reserve acquisition manifest is inconsistent")
    raw = gzip.decompress(archived)
    if sha(raw) != source["sha256"] or sha(raw) != manifest["uncompressed_sha256"]:
        raise ValueError("Pinned Federal Reserve source bytes are inconsistent")
    lines = raw.decode("utf-8-sig").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Date,BETA0"))
    rows = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    valid = []
    for row in rows:
        if not row.get("Date"):
            continue
        observed = date.fromisoformat(row["Date"])
        if observed > requested:
            continue
        try:
            parameters = {k: float(row[k]) for k in ("BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2")}
        except (ValueError, KeyError):
            continue
        if not all(math.isfinite(v) for v in parameters.values()) or min(parameters["TAU1"], parameters["TAU2"]) <= 0:
            continue
        valid.append((observed, row, parameters))
    if not valid:
        raise ValueError("No valid curve on or before the requested date")
    observed, row, parameters = max(valid, key=lambda item: item[0])
    if (requested - observed).days > 7:
        raise ValueError("Nearest fitted curve is more than seven calendar days old")
    differences = []
    for tenor in range(1, 31):
        published = float(row[f"SVENY{tenor:02}"]) / 100
        differences.append(abs(zero_rate(parameters, tenor) - published) * 10000)
    if max(differences) > 0.006:
        raise ValueError("Reconstructed curve fails published-zero comparison (0.006 bp tolerance)")
    selected_path = raw_directory / "selected_observation.json"
    selected_bytes = (json.dumps(row, indent=2) + "\n").encode("utf-8")
    if write:
        selected_path.write_bytes(selected_bytes)
    result = {
        "schema_version": 1,
        "as_of": observed.isoformat(),
        "requested_as_of": as_of,
        "source": SOURCE_URL,
        "source_page": source["source_page"],
        "source_sha256": source["sha256"],
        "source_captured_at": source["captured_at"],
        "raw_archive": "data/raw/fed_curve/feds200628.csv.gz",
        "selected_observation_sha256": sha(selected_bytes),
        "tenors_years": NODES,
        "zero_rates": [zero_rate(parameters, tenor) for tenor in NODES],
        "compounding": "annual continuously compounded decimal",
        "interpolation": "linear in zero rates; flat outside endpoint tenors",
        "parameters": parameters,
        "max_published_zero_error_bps": max(differences),
        "validation_tolerance_bps": 0.006,
        "limitations": [
            "Fitted off-the-run Treasury research curve, not executable prices or a bank funding curve.",
            "Observation date does not establish historical publication-time availability. This is the revised source vintage captured on " + source["captured_at"] + ".",
            "Sub-one-year fitted rates are model extrapolations; the source excludes Treasury bills. This matters for deposit and funding assumptions.",
        ],
    }
    destination = root / "data" / "processed" / "curve.json"
    if write:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2025-12-31")
    parser.add_argument("--from-treasury-snapshot", type=Path)
    args = parser.parse_args()
    curve = prepare(args.as_of, args.from_treasury_snapshot)
    print(f"Pinned curve {curve['as_of']}; maximum published-zero difference {curve['max_published_zero_error_bps']:.6f} bp")
