"""Pin public FDIC bytes and build a reconciled bank-level ALM opening snapshot.

Run with --refresh to fetch public data. Without it, verify and replay the pinned
source bundle, requiring only the Python standard library and no network.
Financial amounts in the FDIC source are thousands of USD; output is USD.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BUNDLE_PATH = RAW / "fdic_source_bundle.json"
OUTPUT = ROOT / "data" / "processed" / "bank_snapshot.json"
CERTIFICATE = 12368
AS_OF = "2025-12-31"
FIELDS = (
    "CERT,RSSDID,NAMEFULL,REPDTE,ASSET,CHBAL,CHBALI,SC,LNLSNET,LNLSGR,"
    "LIAB,EQ,EQTOT,EQCONSUB,DEP,DEPDOM,DEPFOR,DEPI,DEPIFOR,DEPNI,DEPNIFOR,"
    "FREPO,FREPP,OTHBOR,OTHBFHLB,SUBND,OA,ALLOTHL,INTINC,EINTEXP,NIM,NIMQ"
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def capture(label: str, url: str, suffix: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "bank-alm-research/0.1 (public-data research)"})
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
        metadata = {
            "source_id": label,
            "publisher": "Federal Deposit Insurance Corporation",
            "source_url": url,
            "final_url": response.url,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    path = RAW / f"{label}__{metadata['sha256'][:12]}.{suffix}"
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f"Content-addressed file collision: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    metadata["local_path"] = path.relative_to(ROOT).as_posix()
    write_json(path.with_suffix(path.suffix + ".manifest.json"), metadata)
    return metadata


def query_url(endpoint: str, filters: str, fields: str) -> str:
    return "https://api.fdic.gov/banks/" + endpoint + "?" + urllib.parse.urlencode(
        {"filters": filters, "fields": fields, "limit": 2, "format": "json"}
    )


def refresh_bundle() -> list[dict[str, object]]:
    sources = [
        capture("fdic_regions_identity", query_url("institutions", f"CERT:{CERTIFICATE}",
                "CERT,NAME,CITY,STALP,ACTIVE,CHRTAGNT,REGAGNT,DATEUPDT,NAMEHCR"), "json"),
        capture("fdic_regions_20251231", query_url("financials", f"CERT:{CERTIFICATE} AND REPDTE:20251231", FIELDS), "json"),
        capture("fdic_financial_field_definitions", "https://api.fdic.gov/banks/docs/risview_properties.yaml", "yaml"),
        capture("fdic_institution_field_definitions", "https://api.fdic.gov/banks/docs/institution_properties.yaml", "yaml"),
    ]
    return sources


def verified_bytes(source: dict[str, object], root: Path = ROOT) -> bytes:
    path = (root / str(source["local_path"])).resolve()
    if not path.is_relative_to((root / "data" / "raw").resolve()):
        raise ValueError("Pinned source must be under data/raw")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError(f"Source SHA-256 mismatch: {path}")
    return raw


def single_record(raw: bytes) -> tuple[dict[str, object], dict[str, object]]:
    payload = json.loads(raw)
    if payload["meta"]["total"] != 1 or len(payload["data"]) != 1:
        raise ValueError("Expected exactly one FDIC record")
    row = payload["data"][0]["data"]
    if int(row["CERT"]) != CERTIFICATE:
        raise ValueError("Certificate mismatch")
    return row, payload["meta"]


def definition_blocks(raw: bytes) -> dict[str, str]:
    """Preserve exact source YAML blocks without requiring a YAML dependency."""
    text = raw.decode("utf-8-sig")
    return {match.group(1): match.group(0).rstrip() for match in re.finditer(
        r"^      ([A-Z][A-Z0-9_]*):\n(?:(?!^      [A-Z][A-Z0-9_]*:).*(?:\n|$))*", text, re.MULTILINE
    )}


def build_snapshot(sources: list[dict[str, object]] | None = None, root: Path = ROOT) -> dict[str, object]:
    """Rebuild deterministically from pinned source bytes, with no network calls."""
    root = Path(root)
    if sources is None:
        sources = json.loads((root / "data" / "raw" / "fdic_source_bundle.json").read_text(encoding="utf-8"))["source_records"]
    by_id = {str(item["source_id"]): item for item in sources}
    identity, identity_meta = single_record(verified_bytes(by_id["fdic_regions_identity"], root))
    row, financial_meta = single_record(verified_bytes(by_id["fdic_regions_20251231"], root))
    defs = definition_blocks(verified_bytes(by_id["fdic_financial_field_definitions"], root))
    verified_bytes(by_id["fdic_institution_field_definitions"], root)
    if row["REPDTE"] != AS_OF.replace("-", ""):
        raise ValueError("Report date mismatch")
    if str(identity["NAME"]).upper() != str(row["NAMEFULL"]).upper():
        raise ValueError("Institution identity and financial record names differ")
    missing = set(FIELDS.split(",")) - set(row)
    if missing:
        raise ValueError(f"Missing source fields; never replace with zero: {sorted(missing)}")

    def usd(field: str) -> int:
        value = row[field]
        if value is None or isinstance(value, bool):
            raise ValueError(f"Missing or invalid monetary value: {field}")
        number = Decimal(str(value)) * 1000
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError(f"Invalid USD value: {field}")
        return int(number)

    # FREPP is funds/repos PURCHASED (a liability); FREPO is SOLD (an asset).
    wholesale = usd("FREPP") + usd("OTHBOR") + usd("SUBND")
    bs = {
        "cash": usd("CHBAL"),
        "securities": usd("SC"),
        "loans": usd("LNLSNET"),
        "other_assets": usd("ASSET") - usd("CHBAL") - usd("SC") - usd("LNLSNET"),
        "noninterest_deposits": usd("DEPNI"),
        "interest_deposits": usd("DEPI"),
        "wholesale_funding": wholesale,
        "other_liabilities": usd("LIAB") - usd("DEP") - wholesale,
        "equity": usd("EQTOT"),
    }
    residuals = {
        "assets_minus_liabilities_and_total_equity_usd": usd("ASSET") - usd("LIAB") - usd("EQTOT"),
        "total_equity_minus_bank_equity_and_noncontrolling_interests_usd": usd("EQTOT") - usd("EQ") - usd("EQCONSUB"),
        "deposits_minus_interest_and_noninterest_usd": usd("DEP") - usd("DEPI") - usd("DEPNI"),
        "deposits_minus_domestic_and_foreign_usd": usd("DEP") - usd("DEPDOM") - usd("DEPFOR"),
        "nii_minus_interest_income_less_expense_usd": usd("NIM") - (usd("INTINC") - usd("EINTEXP")),
        "modeled_assets_minus_source_assets_usd": sum(bs[k] for k in ("cash", "securities", "loans", "other_assets")) - usd("ASSET"),
        "modeled_funding_and_equity_minus_source_assets_usd": sum(bs[k] for k in ("noninterest_deposits", "interest_deposits", "wholesale_funding", "other_liabilities", "equity")) - usd("ASSET"),
    }
    if any(residuals.values()) or any(value < 0 for value in bs.values()):
        raise ValueError(f"Opening balance sheet reconciliation failed: {residuals}")
    selected = {}
    for field in FIELDS.split(","):
        block = defs.get(field)
        if not block:
            raise ValueError(f"No official field definition for {field}")
        title = re.search(r"^        title: (.*)$", block, re.MULTILINE)
        selected[field] = {"source_title": title.group(1) if title else None, "source_value": row[field], "official_definition_yaml": block}
    return {
        "schema_version": "bank-alm-snapshot-v1",
        "bank_name": identity["NAME"],
        "certificate": CERTIFICATE,
        "rssd_id": int(row["RSSDID"]),
        "as_of": AS_OF,
        "legal_entity": "FDIC-insured bank and its consolidated subsidiaries; not the bank holding company",
        "parent_holding_company": identity["NAMEHCR"],
        "headquarters": {"city": identity["CITY"], "state": identity["STALP"]},
        "source_units": "USD thousands",
        "output_units": "USD",
        "source_records": sources,
        "source_indexes": {"identity": identity_meta["index"], "financials": financial_meta["index"]},
        "balance_sheet_usd": bs,
        "totals_usd": {"assets": usd("ASSET"), "liabilities": usd("LIAB"), "deposits": usd("DEP"), "bank_equity": usd("EQ"), "total_equity": usd("EQTOT"), "noncontrolling_interests": usd("EQCONSUB"), "gross_loans": usd("LNLSGR"), "interest_bearing_cash": usd("CHBALI")},
        "earnings": {"period_start": "2025-01-01", "period_end": AS_OF, "period_basis": "Reported year-to-date; full calendar year at December 31", "annual_interest_income_usd": usd("INTINC"), "annual_interest_expense_usd": usd("EINTEXP"), "annual_nii_usd": usd("NIM"), "fourth_quarter_nii_usd": usd("NIMQ")},
        "field_mapping": {"cash": "CHBAL * 1000", "securities": "SC * 1000", "loans": "LNLSNET * 1000", "other_assets": "(ASSET - CHBAL - SC - LNLSNET) * 1000", "noninterest_deposits": "DEPNI * 1000", "interest_deposits": "DEPI * 1000", "wholesale_funding": "(FREPP + OTHBOR + SUBND) * 1000", "other_liabilities": "(LIAB - DEP - FREPP - OTHBOR - SUBND) * 1000", "equity": "EQTOT * 1000"},
        "derived_field_notes": [
            "EQTOT includes $60 million of noncontrolling interests in consolidated subsidiaries. EQ alone does not balance the consolidated bank statement; both fields are retained.",
            "Other assets is a residual bucket including every reported asset outside cash, securities and net loans. It is not the narrower FDIC OA field.",
            "Wholesale funding groups federal funds/repo liabilities, other borrowed money and subordinated notes. It does not reclassify brokered deposits out of deposits.",
            "OTHBFHLB is included in OTHBOR and is not added again. FREPP is the borrowed-funds liability; FREPO is the sold-funds asset.",
            "Other liabilities is the residual of reported total liabilities after deposits and defined wholesale funding. It is not a directly reported FDIC field.",
            "Loan balance is net of allowance; detailed contractual maturity, repricing, duration, deposit behavior and encumbrance are not supplied by these aggregate fields.",
            "INTINC, EINTEXP and NIM are year-to-date values. December 31 values represent the full year; NIMQ is the fourth quarter only.",
            "Snapshot is a later retrieved, potentially revised FDIC vintage, not proof of information available on 2025-12-31. It must not be used as a point-in-time backtest without publication/vintage controls.",
        ],
        "source_field_metadata": selected,
        "reconciliations": {"passed": True, "tolerance_usd": 0, "residuals_usd": residuals},
    }


def validate_snapshot(snapshot: dict[str, object], root: Path = ROOT) -> None:
    """Reject modified raw files or a normalized snapshot that differs from source."""
    rebuilt = build_snapshot(snapshot["source_records"], root=Path(root))
    if snapshot != rebuilt:
        raise ValueError("Normalized bank snapshot does not reproduce exactly from pinned FDIC sources")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="Fetch and pin current FDIC response bytes")
    mode.add_argument("--offline", action="store_true", help="Rebuild using pinned bytes only (the default)")
    mode.add_argument("--verify", action="store_true", help="Verify the saved snapshot against pinned bytes without writing")
    args = parser.parse_args()
    if args.verify:
        validate_snapshot(json.loads(OUTPUT.read_text(encoding="utf-8")))
        print("Bank snapshot exactly reproduces from SHA-256 verified FDIC sources")
        return
    sources = refresh_bundle() if args.refresh else json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))["source_records"]
    snapshot = build_snapshot(sources)
    if args.refresh:
        write_json(BUNDLE_PATH, {"source_records": sources})
    write_json(OUTPUT, snapshot)
    print(f"{snapshot['bank_name']} | {AS_OF} | assets ${snapshot['totals_usd']['assets']:,} | all reconciliations passed")


if __name__ == "__main__":
    main()
