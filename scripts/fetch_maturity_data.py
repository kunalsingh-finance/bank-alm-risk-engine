"""Fetch official maturity evidence; offline rebuild is the default operation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/maturity"
BAND_SUFFIXES = ("3LES", "3T12", "1T3", "3T5", "5T15", "OV15")
FIELDS = ["CERT", "RSSDID", "NAMEFULL", "REPDTE", "SC", "LNLS", "LNLSNET", "LNLSGR", "LNLSGRS", "SC1LES", "LNATRES", "LNLSRES", "UNINC", "NALNLS", "NASCDEBT", "SCEQFV", "SCEQNFT", "SCPLEDGE", "LNPLEDGE", "NONIX", "ELNATR", "ELNLOS", "NTLNLS"] + [prefix + suffix for prefix in ("SCNM", "SCPT", "LNOT", "LNRS") for suffix in BAND_SUFFIXES] + ["SCO3YLES", "SCOOV3Y"]
DATA_URL = "https://api.fdic.gov/banks/financials?" + urllib.parse.urlencode({"filters": "CERT:12368 AND REPDTE:20251231", "fields": ",".join(FIELDS), "limit": 2, "format": "json"})
SOURCES = {
    "fdic_maturity_20251231": (DATA_URL, ".json"),
    "fdic_field_definitions": ("https://api.fdic.gov/banks/docs/risview_properties.yaml", ".yaml"),
    "ffiec_202512_instructions": ("https://www.ffiec.gov/sites/default/files/data/reporting-forms/FFIEC031_FFIEC041_202512_i.pdf", ".pdf"),
}


def fetch_sources() -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "maturity-source-manifest-v1", "records": [], "download_limitations": []}
    for source_id, (url, suffix) in SOURCES.items():
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            if source_id != "ffiec_202512_instructions":
                raise
            manifest["download_limitations"].append({"source_id": source_id, "source_url": url, "status": error.code, "note": "Instructions verified through the web research tool; direct PDF byte retrieval unavailable. No PDF hash is claimed. Numerical rebuild depends only on the saved FDIC bytes."})
            continue
        with response:
            payload = response.read()
            digest = hashlib.sha256(payload).hexdigest()
            path = RAW / f"{source_id}__{digest[:12]}{suffix}"
            path.write_bytes(payload)
            manifest["records"].append({"source_id": source_id, "source_url": url, "final_url": response.url, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "http_status": response.status, "content_type": response.headers.get("Content-Type"), "sha256": digest, "bytes": len(payload), "local_path": path.relative_to(ROOT).as_posix()})
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_sources(root: Path = ROOT) -> tuple[dict, dict, dict]:
    root = Path(root)
    manifest = json.loads((root / "data/raw/maturity/manifest.json").read_text(encoding="utf-8"))
    payloads = {}
    for record in manifest["records"]:
        path = (root / record["local_path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Maturity source path escapes project root")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"] or len(payload) != record["bytes"]:
            raise ValueError("Maturity source hash mismatch: " + record["source_id"])
        payloads[record["source_id"]] = payload
    response = json.loads(payloads["fdic_maturity_20251231"])
    if len(response["data"]) != 1:
        raise ValueError("Expected exactly one bank statement")
    row = response["data"][0]["data"]
    if row["CERT"] != 12368 or str(row["REPDTE"]) != "20251231":
        raise ValueError("Maturity source bank/date mismatch")
    definitions = {}
    text = payloads["fdic_field_definitions"].decode("utf-8")
    for name in FIELDS:
        match = re.search(r"(?ms)^      " + re.escape(name) + r":\n.*?(?=^      [A-Z0-9_]+:|\Z)", text)
        if match:
            title = re.search(r"(?m)^        title: (.*)$", match.group())
            definitions[name] = {"title": title.group(1) if title else name, "definition_yaml": match.group()}
    return row, definitions, manifest


def load_verified_profile(root: Path = ROOT) -> dict:
    """Replay saved source bytes, reject processed-data drift, and perform no writes."""
    root = Path(root)
    row, definitions, manifest = read_sources(root)
    rebuilt = build_profile(row, definitions, manifest)
    saved = json.loads((root / "data/processed/maturity_profile.json").read_text(encoding="utf-8"))
    if rebuilt != saved:
        raise ValueError("Processed maturity profile differs from hash-verified source replay")
    return rebuilt


def build_profile(row: dict, definitions: dict, manifest: dict) -> dict:
    """Keep reported band amounts separate from every modeling assumption."""
    def usd(field: str) -> float:
        value = row.get(field)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("Missing/invalid required maturity field: " + field)
        return value * 1000
    bands = []
    boundaries = [(0, .25), (.25, 1), (1, 3), (3, 5), (5, 15), (15, None)]
    groups = {"SCNM": ("securities", "other_debt", "Debt except specified first-lien mortgage pass-throughs and other mortgage-backed securities"), "SCPT": ("securities", "mortgage_pass_through", "Pass-through securities backed by closed-end first-lien 1-4 family mortgages"), "LNRS": ("loans", "residential_first_lien", "Closed-end first-lien 1-4 family residential loans"), "LNOT": ("loans", "other_loans", "Other loans and leases")}
    for prefix, (asset_class, group, scope) in groups.items():
        for suffix, (lower, upper) in zip(BAND_SUFFIXES, boundaries):
            field = prefix + suffix
            bands.append({"id": field, "source_field": field, "asset_class": asset_class, "group": group, "scope": scope, "basis": "fixed_remaining_maturity_or_floating_next_repricing", "lower_years_exclusive": lower, "upper_years_inclusive": upper, "reported_balance_usd": usd(field), "field_title": definitions[field]["title"]})
    for field, lower, upper in (("SCO3YLES", 0, 3), ("SCOOV3Y", 3, None)):
        bands.append({"id": field, "source_field": field, "asset_class": "securities", "group": "other_mbs", "scope": "Other mortgage-backed securities, expected weighted average life", "basis": "expected_weighted_average_life", "lower_years_exclusive": lower, "upper_years_inclusive": upper, "reported_balance_usd": usd(field), "field_title": definitions[field]["title"]})
    securities_bands = sum(b["reported_balance_usd"] for b in bands if b["asset_class"] == "securities")
    loan_bands = sum(b["reported_balance_usd"] for b in bands if b["asset_class"] == "loans")
    residuals = {"securities_bands_plus_nonaccrual_and_equity_minus_total_usd": securities_bands + usd("NASCDEBT") + usd("SCEQNFT") - usd("SC"), "loan_bands_plus_nonaccrual_minus_gross_usd": loan_bands + usd("NALNLS") - usd("LNLSGR"), "gross_minus_allowance_minus_net_usd": usd("LNLSGR") - usd("LNATRES") - usd("LNLSNET")}
    if any(abs(value) > 1 for value in residuals.values()):
        raise ValueError("Unexpected reporting scope: explicit residual reconciliation needs review: " + str(residuals))
    return {"schema_version": "bank-alm-maturity-profile-v1", "bank_name": row["NAMEFULL"], "certificate": row["CERT"], "rssd_id": row["RSSDID"], "as_of": "2025-12-31", "legal_entity": "FDIC-insured Regions Bank and consolidated subsidiaries, not Regions Financial Corporation", "units": "USD; official source amounts in USD thousands multiplied by1000", "source_records": manifest["records"], "download_limitations": manifest.get("download_limitations", []), "instructions_reference": {"url": SOURCES["ffiec_202512_instructions"][0], "edition": "December2025", "securities": "RC-B Memorandum2, PDF pages146-156", "loans": "RC-C PartI Memorandum2, PDF pages194-201", "verification": "Read through web research tool; direct PDF download may be unavailable, as recorded in download_limitations."}, "bands": bands, "totals_usd": {"securities_book": usd("SC"), "securities_bands": securities_bands, "equity_securities_residual": usd("SCEQNFT"), "nonaccrual_debt_securities": usd("NASCDEBT"), "securities_contractual_maturity_le_one_year": usd("SC1LES"), "pledged_securities": usd("SCPLEDGE"), "unpledged_securities_aggregate": max(0, usd("SC") - usd("SCPLEDGE")), "gross_loans": usd("LNLSGR"), "loan_bands_accruing": loan_bands, "nonaccrual_loans": usd("NALNLS"), "allowance_for_loans": usd("LNATRES"), "unearned_income": usd("UNINC"), "net_loans": usd("LNLSNET"), "pledged_loans": usd("LNPLEDGE")}, "reconciliations": {"passed": True, "tolerance_usd": 1, "residuals_usd": residuals}, "reported_annual_context_usd": {"noninterest_expense": usd("NONIX"), "provision_for_credit_losses": usd("ELNATR"), "provision_for_loan_lease_losses": usd("ELNLOS"), "net_chargeoffs": usd("NTLNLS")}, "field_definitions": definitions, "limitations": ["A maturity-or-next-repricing band does not reveal the fixed/floating split or the contractual maturity of floating exposures. Those remain explicit model assumptions.", "Other MBS bands report expected weighted average life, not final contractual maturity. A representative cash-flow reconstruction is an assumption.", "Equity securities and nonaccrual exposures are outside the performing debt band schedule and remain separately identified.", "Public loan bands are gross exposures. Proportional allocation of the total allowance across segments to reproduce net loan book is a modeling bridge, not a reported allowance assignment.", "Pledged securities are reported in aggregate. Proportional allocation of encumbrance across debt bands and exclusion of equity securities from forced sales are additional assumptions. Availability of new borrowing remains separately assumed.", "Retrieved FDIC data can be revised; observation-date alignment is not evidence the data were published on that date."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Explicitly retrieve official source bytes before rebuilding")
    args = parser.parse_args()
    if args.fetch:
        fetch_sources()
    row, definitions, manifest = read_sources()
    profile = build_profile(row, definitions, manifest)
    destination = ROOT / "data/processed/maturity_profile.json"
    destination.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_count": len(manifest["records"]), "profile": destination.relative_to(ROOT).as_posix(), "reconciliations": profile["reconciliations"]}, indent=2))


if __name__ == "__main__":
    main()
