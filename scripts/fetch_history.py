"""Pin public FDIC/FRED history and rebuild deposit calibration offline."""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from bank_alm.calibration import calibrate
from scripts.fetch_bank_data import definition_blocks

RAW = ROOT / "data" / "raw" / "history"
BUNDLE = RAW / "source_bundle.json"
FIELDS = "CERT,RSSDID,NAMEFULL,REPDTE,ASSET,AVASSET,ASSET2,ERNAST,ERNAST2,DEP,DEPIDOM,DEPIFOR,DEPI,DEPNI,EDEP,EDEPDOM,EDEPDOMQ,EDEPFOR,EDEPFORQ,INTINC,EINTEXP,NIM,NIMQ,NONII,NONIIQ,NONIX,NONIXQ,ELNATR,NTLNLS,NTLNLSQ,LNLSGR,LNLSGR2,ID,DATEUPDT"
URLS = {
    "fdic_history": ("https://api.fdic.gov/banks/financials?" + urllib.parse.urlencode({"filters": "CERT:12368 AND REPDTE:[20141231 TO 20251231]", "fields": FIELDS, "sort_by": "REPDTE", "sort_order": "ASC", "limit": 100, "format": "json"}), "json"),
    "fred_dff": ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF&cosd=2014-01-01&coed=2025-12-31", "csv"),
    "fdic_definitions": ("https://api.fdic.gov/banks/docs/risview_properties.yaml", "yaml"),
    "ffiec_faq": ("https://cdr.ffiec.gov/public/HelpFiles/FAQ.htm", "html"),
    "ffiec_bulk_page": ("https://cdr.ffiec.gov/public/PWS/DownloadBulkData.aspx", "html"),
    "ffiec_pws_info": ("https://cdr.ffiec.gov/public/HelpFiles/PWSInfo.htm", "html"),
    "fred_dff_metadata": ("https://fred.stlouisfed.org/series/DFF", "html"),
    "ffiec_rc_k_instructions": ("https://www.fdic.gov/system/files/2024-08/2017-03-rc-k.pdf", "pdf"),
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def capture(source_id: str, url: str, suffix: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "bank-alm-research/0.3 (public-data research)"})
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
        digest = hashlib.sha256(raw).hexdigest()
        path = RAW / f"{source_id}__{digest[:12]}.{suffix}"
        metadata = {"source_id": source_id, "source_url": url, "final_url": response.url,
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "http_status": response.status, "content_type": response.headers.get("Content-Type"),
                    "bytes": len(raw), "sha256": digest, "local_path": path.relative_to(ROOT).as_posix()}
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Content-addressed source collision")
    path.write_bytes(raw)
    write_json(path.with_suffix(path.suffix + ".manifest.json"), metadata)
    return metadata


def verified_bytes(source: dict, root: Path = ROOT) -> bytes:
    root = Path(root)
    path = (root / source["local_path"]).resolve()
    if not path.is_relative_to((root / "data" / "raw" / "history").resolve()):
        raise ValueError("Historical source path is outside its raw directory")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError(f"Historical source SHA-256 mismatch: {source['source_id']}")
    return raw


def quarter_end(value: date) -> date:
    month = ((value.month - 1) // 3 + 1) * 3
    return date(value.year, month, calendar.monthrange(value.year, month)[1])


def quarterly_policy_rates(raw: bytes) -> dict:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != ["observation_date", "DFF"]:
        raise ValueError("Unexpected FRED DFF CSV columns")
    observations = {}
    for row in reader:
        day = date.fromisoformat(row["observation_date"])
        if day in observations:
            raise ValueError("Duplicate daily policy-rate observation")
        if row["DFF"] in ("", "."):
            raise ValueError("Missing policy-rate day; interpolation/future fill is prohibited")
        value = float(row["DFF"]) / 100
        if not math.isfinite(value):
            raise ValueError("Nonfinite policy rate")
        observations[day] = value
    start, end = date(2014, 1, 1), date(2025, 12, 31)
    expected = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    if set(observations) != expected:
        raise ValueError("Daily DFF coverage must exactly cover 2014–2025 with no missing days")
    groups = {}
    for day, value in observations.items():
        groups.setdefault(quarter_end(day).isoformat(), []).append((day, value))
    return {key: {"mean_rate_decimal": math.fsum(value for _, value in values) / len(values),
                  "observations": len(values), "first_observation": min(day for day, _ in values).isoformat(),
                  "last_observation": max(day for day, _ in values).isoformat(),
                  "aggregation": "Arithmetic mean of all supplied daily calendar observations; no filling",
                  "series": "DFF", "original_units": "Percent", "units": "decimal annual rate"}
            for key, values in sorted(groups.items())}


def derive_quarters(rows: list[dict], policy: dict) -> tuple[list[dict], dict]:
    """De-cumulate within year and match expense to interest-bearing deposits."""
    if len({r["REPDTE"] for r in rows}) != len(rows):
        raise ValueError("Duplicate bank-quarter records")
    if rows != sorted(rows, key=lambda r: r["REPDTE"]):
        raise ValueError("Historical rows must be chronological")
    flow_fields = {"deposit_interest_expense": "EDEPDOM", "foreign_deposit_interest_expense": "EDEPFOR",
                   "total_interest_income": "INTINC", "total_interest_expense": "EINTEXP", "net_interest_income": "NIM",
                   "noninterest_income": "NONII", "noninterest_expense": "NONIX", "provision_for_credit_losses": "ELNATR", "net_loan_chargeoffs": "NTLNLS"}
    quarterly_controls = {"EDEPDOM": "EDEPDOMQ", "EDEPFOR": "EDEPFORQ", "NIM": "NIMQ", "NONII": "NONIIQ", "NONIX": "NONIXQ", "NTLNLS": "NTLNLSQ"}
    max_residual = 0
    controls = 0
    output = []

    def usd(row: dict, key: str) -> int | float:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            raise ValueError(f"Missing monetary field {key} in {row.get('REPDTE')}")
        number = Decimal(str(value)) * 1000
        if not number.is_finite():
            raise ValueError(f"Invalid monetary field {key}")
        return int(number) if number == number.to_integral_value() else float(number)

    previous = None
    for row in rows:
        if int(row["CERT"]) != 12368 or int(row["RSSDID"]) != 233031 or row["NAMEFULL"] != "REGIONS BANK":
            raise ValueError("Historical legal entity mismatch")
        end = datetime.strptime(row["REPDTE"], "%Y%m%d").date()
        if quarter_end(end) != end:
            raise ValueError("Unexpected bank reporting date")
        if previous is None:
            previous = row
            continue
        previous_end = datetime.strptime(previous["REPDTE"], "%Y%m%d").date()
        if quarter_end(previous_end + timedelta(days=1)) != end:
            raise ValueError("Quarter gap: no missing bank periods may be filled")
        beginning = previous_end + timedelta(days=1)
        days = (end - beginning).days + 1
        first_quarter = end.month == 3
        flows = {name + "_usd": usd(row, field) - (0 if first_quarter else usd(previous, field)) for name, field in flow_fields.items()}
        for field, qfield in quarterly_controls.items():
            derived = usd(row, field) - (0 if first_quarter else usd(previous, field))
            residual = derived - usd(row, qfield)
            max_residual = max(max_residual, abs(residual))
            controls += 1
            if residual != 0:
                raise ValueError(f"YTD/quarterly reconciliation fails for {row['REPDTE']} {field}: {residual}")
        if usd(row, "EDEP") != usd(row, "EDEPDOM") + usd(row, "EDEPFOR") or usd(row, "DEPI") != usd(row, "DEPIDOM") + usd(row, "DEPIFOR"):
            raise ValueError("Domestic/foreign deposit scope does not reconcile")
        opening_interest = usd(previous, "DEPIDOM")
        closing_interest = usd(row, "DEPIDOM")
        average_interest = (opening_interest + closing_interest) / 2
        if average_interest <= 0 or flows["deposit_interest_expense_usd"] < 0:
            raise ValueError("Deposit denominator must be positive and expense nonnegative")
        if end.isoformat() not in policy:
            raise ValueError("No matching quarterly policy rate")
        annualization = 365 / days
        avg_assets = (usd(previous, "ASSET") + usd(row, "ASSET")) / 2
        avg_loans = (usd(previous, "LNLSGR") + usd(row, "LNLSGR")) / 2
        output.append({"quarter_start": beginning.isoformat(), "quarter_end": end.isoformat(), "days_in_quarter": days,
                       "source_record_id": row["ID"], "annualization_factor": annualization,
                       "source_ytd_usd": {name + "_usd": usd(row, field) for name, field in flow_fields.items()},
                       "quarter_flows_usd": flows,
                       "opening_domestic_interest_bearing_deposits_usd": opening_interest,
                       "closing_domestic_interest_bearing_deposits_usd": closing_interest,
                       "average_domestic_interest_bearing_deposits_proxy_usd": average_interest,
                       "deposit_average_basis": "Arithmetic mean of prior/current quarter-end DEPIDOM, not reported RC-K daily/weekly average",
                       "deposit_cost_annualized_proxy": flows["deposit_interest_expense_usd"] * annualization / average_interest,
                       "policy_rate_mean_decimal": policy[end.isoformat()]["mean_rate_decimal"],
                       "reported_balance_sheet_usd": {"assets": usd(row, "ASSET"), "interest_bearing_deposits": usd(row, "DEPI"), "foreign_interest_bearing_deposits": usd(row, "DEPIFOR"), "total_deposits": usd(row, "DEP"), "gross_loans": usd(row, "LNLSGR"), "earning_assets": usd(row, "ERNAST"), "reported_average_assets_AVASSET": usd(row, "AVASSET")},
                       "ratios_annualized_proxy": {"noninterest_income_to_average_assets": flows["noninterest_income_usd"] * annualization / avg_assets,
                                                   "noninterest_expense_to_average_assets": flows["noninterest_expense_usd"] * annualization / avg_assets,
                                                   "credit_provision_to_average_gross_loans": flows["provision_for_credit_losses_usd"] * annualization / avg_loans,
                                                   "net_chargeoffs_to_average_gross_loans": flows["net_loan_chargeoffs_usd"] * annualization / avg_loans},
                       "publication_date": None, "submission_datetime": None,
                       "availability_status": "Exact bank-quarter submission/publication dates not observed; FDIC later-vintage record"})
        previous = row
    return output, {"ytd_quarter_comparisons": controls, "maximum_quarter_flow_residual_usd": max_residual,
                    "all_exact_quarter_flow_checks_passed": True, "identity_and_deposit_scope_checks_passed": True}


def build_history(sources: list[dict] | None = None, root: Path = ROOT) -> dict:
    root = Path(root)
    if sources is None:
        sources = json.loads((root / "data/raw/history/source_bundle.json").read_text())["source_records"]
    if len(sources) != len(URLS) or {s["source_id"] for s in sources} != set(URLS):
        raise ValueError("Historical source bundle is incomplete or has duplicate source ids")
    raw = {s["source_id"]: verified_bytes(s, root) for s in sources}
    payload = json.loads(raw["fdic_history"])
    records = [entry["data"] for entry in payload["data"]]
    if payload["meta"]["total"] != 45 or len(records) != 45:
        raise ValueError("Expected all 45 bank quarters including the 2014Q4 opening denominator")
    policy = quarterly_policy_rates(raw["fred_dff"])
    quarters, checks = derive_quarters(records, policy)
    definitions = definition_blocks(raw["fdic_definitions"])
    selected = {}
    for field in FIELDS.split(","):
        if field in {"ID", "DATEUPDT"}:
            continue
        if field not in definitions:
            raise ValueError(f"Missing official definition for {field}")
        selected[field] = definitions[field]
    if quarters[0]["quarter_end"] != "2015-03-31" or quarters[-1]["quarter_end"] != "2025-12-31":
        raise ValueError("Unexpected calibration coverage")
    last_year = [q for q in quarters if q["quarter_end"].startswith("2025")]
    year_flows = {key: sum(q["quarter_flows_usd"][key] for q in last_year) for key in last_year[0]["quarter_flows_usd"]}
    average_assets = sum(q["reported_balance_sheet_usd"]["reported_average_assets_AVASSET"] * q["days_in_quarter"] for q in last_year) / 365
    assets_proxy = sum(((records[-5 + i]["ASSET"] + records[-4 + i]["ASSET"]) / 2) * 1000 * q["days_in_quarter"] for i, q in enumerate(last_year)) / 365
    gross_loans_proxy = sum(((records[-5 + i]["LNLSGR"] + records[-4 + i]["LNLSGR"]) / 2) * 1000 * q["days_in_quarter"] for i, q in enumerate(last_year)) / 365
    return {"schema_version": "bank-alm-history-v1", "bank_name": "Regions Bank", "certificate": 12368, "rssd_id": 233031,
            "legal_entity": "FDIC-insured Regions Bank consolidated bank entity; not Regions Financial Corporation",
            "observation_start": "2015-03-31", "observation_end": "2025-12-31", "quarter_count": len(quarters),
            "source_records": sources, "source_index": payload["meta"]["index"], "source_money_units": "USD thousands", "normalized_money_units": "USD",
            "quarters": quarters, "policy_quarter_means": policy, "source_field_definitions": selected,
            "reconciliations": checks,
            "annual_2025_cost_and_credit_evidence": {"flows_usd": year_flows,
                "day_weighted_reported_average_assets_usd": average_assets,
                "reported_average_assets_period_basis": "Unverified: FDIC AVASSET dictionary title is AVG TOTAL ASSETS without a quarter/YTD definition. Its day-weighted combination is retained for inspection only and is not used as a denominator.",
                "time_weighted_quarter_endpoint_average_assets_proxy_usd": assets_proxy,
                "time_weighted_quarter_endpoint_average_gross_loans_proxy_usd": gross_loans_proxy,
                "noninterest_income_to_average_assets_proxy": year_flows["noninterest_income_usd"] / assets_proxy,
                "noninterest_expense_to_average_assets_proxy": year_flows["noninterest_expense_usd"] / assets_proxy,
                "credit_provision_to_average_gross_loans_proxy": year_flows["provision_for_credit_losses_usd"] / gross_loans_proxy,
                "net_chargeoffs_to_average_gross_loans_proxy": year_flows["net_loan_chargeoffs_usd"] / gross_loans_proxy,
                "notes": "Noninterest income is broader than fees; provisions differ from chargeoffs and must not both be charged as the same credit cost. ELNATR scope reflects provision-for-credit-loss definitions, including later accounting regimes."},
            "availability_evidence": {"record_publication_dates": "Unknown and represented as null, never quarter-end plus an invented lag",
                "fdic_metadata": "Response gives dataset index creation time but no bank-quarter DATEUPDT values; index timestamp is not a filing/publication timestamp",
                "ffiec_submission_service": "Official PWSInfo documents RetrieveFilersSubmissionDateTime, but access requires a registered account and security token. No credentials were available or requested.",
                "public_bulk_inspection": "Public DownloadBulkData page lists Call Reports Single Period for all banks; its public HTML does not expose an individual-bank quarterly-average download or submission timestamps. RC-K average data were not obtained through the unauthenticated sources used here.",
                "rc_k_denominator_definition": "Pinned official March 2017 RC-K instructions distinguish quarterly average interest-bearing transaction accounts (item 10), savings/time deposits (11), and foreign-office interest-bearing deposits (12). These definitions establish the desired scope but do not supply Regions observations or map AVASSET to a period.",
                "publication_procedure": "FFIEC FAQ says individual UBPR data is generally public the day after a validated Call Report is received; this is a general procedure, not observed Regions release dates.",
                "public_data_not_unavailable_in_principle": True,
                "historical_vintage": "All observations are the later source vintage captured in these manifests; original as-filed versions and revision history are not established."},
            "limitations": ["Deposit denominator is a matching domestic interest-bearing endpoint-average proxy, not total deposits and not reported daily/weekly averages.", "Contemporaneous realized policy-rate means support conditional historical analysis, not forecasts available at quarter start.", "FDIC quarterly averages were not obtained for interest-bearing deposits through the unauthenticated sources inspected; use RC-K filings in a later authenticated enhancement.", "Deposit mix, merger effects and customer-level behavior are not separately identified. Provision regimes change around CECL implementation; compare provision histories cautiously."]}


def validate_history(history: dict, root: Path = ROOT) -> None:
    if history != build_history(history["source_records"], root):
        raise ValueError("Historical data does not reproduce from hash-verified sources")


def load_verified_history(root: Path = ROOT) -> dict:
    """Read and reconstruct historical data using only the requested checkout."""
    root = Path(root)
    history = json.loads((root / "data/processed/history.json").read_text(encoding="utf-8"))
    validate_history(history, root)
    return history


def load_verified_calibration(root: Path = ROOT) -> dict:
    """Read deterministic calibration and fail closed on source/output changes."""
    root = Path(root)
    history = load_verified_history(root)
    result = json.loads((root / "data/processed/calibration.json").read_text(encoding="utf-8"))
    if result != calibrate(history):
        raise ValueError("Calibration differs from deterministic historical replay")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--refresh", action="store_true")
    group.add_argument("--offline", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    history_path = ROOT / "data/processed/history.json"
    calibration_path = ROOT / "data/processed/calibration.json"
    if args.verify:
        load_verified_calibration()
        print("Historical sources, 44-quarter normalization, and calibration reproduce exactly")
        return
    sources = [capture(key, *value) for key, value in URLS.items()] if args.refresh else json.loads(BUNDLE.read_text())["source_records"]
    history = build_history(sources)
    result = calibrate(history)
    if args.refresh:
        write_json(BUNDLE, {"source_records": sources})
    write_json(history_path, history)
    write_json(calibration_path, result)
    print(f"Regions Bank: {history['quarter_count']} quarters; beta={result['coefficients']['total_beta']:.4f}; holdout RMSE={result['metrics']['lagged_model']['holdout']['rmse_bps']:.2f} bps")


if __name__ == "__main__":
    main()
