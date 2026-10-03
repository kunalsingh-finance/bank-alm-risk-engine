"""Read-only validation of the exported XLSX, including cached formula values.

No spreadsheet authoring library is used. The independent swap reconstruction
does not import the ALM engine or its numerical helpers.
"""
from __future__ import annotations
import calendar
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "outputs/01a0fce5-927e-7883-9b51-671e6a527eaa/Bank_ALM_Case.xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def validate(path: Path) -> dict:
    with ZipFile(path) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {x.attrib["Id"]: x.attrib["Target"] for x in rels}
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(x.itertext()) for x in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        sheets = {}
        formula_count = 0
        for info in book.find("s:sheets", NS):
            target = targets[info.attrib[R]].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            xml = ET.fromstring(archive.read(target))
            cells = {}
            for cell in xml.findall(".//s:sheetData/s:row/s:c", NS):
                address = cell.attrib["r"]
                assert cell.attrib.get("t") != "e", f"Formula error {info.attrib['name']}!{address}"
                value = cell.find("s:v", NS)
                text = None if value is None else value.text
                if cell.attrib.get("t") == "s" and text is not None:
                    text = shared[int(text)]
                elif cell.attrib.get("t") == "inlineStr":
                    text = "".join(cell.find("s:is", NS).itertext())
                elif cell.attrib.get("t") not in ("str", "b") and text is not None:
                    text = float(text)
                formula = cell.find("s:f", NS)
                if formula is not None:
                    formula_count += 1
                    assert value is not None and text is not None, f"No cached formula result {info.attrib['name']}!{address}"
                cells[address] = (text, None if formula is None else formula.text)
            sheets[info.attrib["name"]] = cells
        assert list(sheets) == ["Summary", "Assumptions", "Earnings", "Swap", "Sources", "Engine reference", "Engine ledgers"]
        get = lambda sheet, cell: sheets[sheet][cell][0]
        curve = json.loads((ROOT / "data/processed/curve.json").read_text())
        snapshot_bytes = (ROOT / "data/processed/bank_snapshot.json").read_bytes()
        bank = json.loads(snapshot_bytes)
        analysis_bytes = (ROOT / "output/analysis.json").read_bytes()
        analysis = json.loads(analysis_bytes)
        assert get("Sources", "E27") == hashlib.sha256(analysis_bytes).hexdigest(), "Workbook analysis hash is stale"
        assert get("Sources", "E28") == hashlib.sha256(snapshot_bytes).hexdigest()
        assert get("Sources", "E10") == bank["balance_sheet_usd"]["cash"]
        assert get("Sources", "E19") == bank["totals_usd"]["assets"]
        assert get("Assumptions", "E6") == 3
        for cell in ["E9", "E14", "E15", "E16", "E17"]:
            assert isinstance(get("Summary", cell), float)
            assert "Earnings!" in sheets["Summary"][cell][1]
        # Independent dated swap pricing; exact local zero interpolation.
        start = date.fromisoformat(bank["as_of"])
        notional = get("Swap", "E6")
        shock = get("Swap", "E9")
        tenors, rates = curve["tenors_years"], curve["zero_rates"]
        def zero(t):
            if t <= tenors[0]:
                return rates[0]
            for i in range(1, len(tenors)):
                if t <= tenors[i]:
                    fraction = (t-tenors[i-1])/(tenors[i]-tenors[i-1])
                    return rates[i-1]+fraction*(rates[i]-rates[i-1])
            return rates[-1]
        dates = []
        previous = start
        for month in range(1, 61):
            total = start.year*12+start.month-1+month
            year, index = divmod(total, 12)
            payment = date(year, index+1, calendar.monthrange(year, index+1)[1])
            dates.append(((payment-previous).days/365, (payment-start).days/365))
            previous = payment
        base = [math.exp(-zero(t)*t) for _, t in dates]
        shocked = [math.exp(-(zero(t)+shock)*t) for _, t in dates]
        fixed = (1-base[-1])/sum(alpha*df for (alpha, _), df in zip(dates, base))
        fixing = (1/base[0]-1)/dates[0][0]
        coupons = []
        prior_df = 1
        comparisons = 0
        def close(actual, expected, label, tolerance=1e-6):
            nonlocal comparisons
            assert math.isfinite(actual) and abs(actual-expected) <= tolerance, f"{label}: {actual} vs {expected}"
            comparisons += 1
        close(get("Swap", "E7"), fixed, "Par fixed rate", 1e-12)
        close(get("Swap", "E8"), fixing, "Locked first fixing", 1e-12)
        for i, ((alpha, t), df) in enumerate(zip(dates, shocked)):
            floating = fixing if i == 0 else (prior_df/df-1)/alpha
            coupon = notional*(floating-fixed)*alpha
            coupons.append(coupon)
            close(get("Swap", f"T{i+22}"), coupon, f"Coupon {i+1}")
            prior_df = df
        opening = sum(c*d for c, d in zip(coupons, shocked))
        terminal = sum(c*d for c, d in zip(coupons[12:], shocked[12:]))/shocked[11]
        close(get("Swap", "E10"), opening, "Opening swap value")
        close(get("Swap", "E11"), terminal, "Terminal swap value")
        close(get("Swap", "E12"), sum(coupons[:12]), "12-month coupons")
        close(get("Swap", "E13"), 0, "Inception par value")
        for i, letter in enumerate("GHIJKLMNOPQR"):
            opening_cash = get("Earnings", f"{letter}27")
            income = get("Earnings", f"{letter}46")
            noncash = get("Earnings", f"{letter}42")
            collateral = get("Earnings", f"{letter}53")
            fee = get("Earnings", f"{letter}54")
            withdrawals = get("Earnings", f"{letter}55")
            close(get("Earnings", f"{letter}56"), opening_cash+income+noncash-collateral-fee-withdrawals, f"Free cash month {i+1}")
            close(get("Earnings", f"{letter}69"), get("Earnings", f"{letter}67")-noncash, f"Loan book month {i+1}")
            prior = "FGHIJKLMNOPQ"[i]
            opening_deposits = get("Earnings", "F15") if i == 0 else get("Earnings", f"{prior}24")
            deposit_rate = max(get("Assumptions", "E67"), get("Assumptions", "E66") + (get("Assumptions", "E18") * get("Assumptions", "E12") / 10000 if i+1 > get("Assumptions", "E48") else 0))
            close(get("Earnings", f"{letter}36"), opening_deposits*deposit_rate*dates[i][0], f"Opening-balance deposit interest month {i+1}")
        # Full fixed imports retain all reference and candidate events.
        expected_paths = len(analysis["scenarios"])+sum(len(p["scenarios"]) for p in analysis["policies"]["candidates"])
        expected_events = sum(1+len(s["monthly"]) for s in analysis["scenarios"])+sum(1+len(s["monthly"]) for p in analysis["policies"]["candidates"] for s in p["scenarios"])
        ledger_rows = [cell for cell in sheets["Engine ledgers"] if cell.startswith("C") and cell[1:].isdigit() and int(cell[1:]) >= 10]
        assert len(ledger_rows) == expected_events
        scenario_rows = [cell for cell in sheets["Engine reference"] if cell.startswith("C") and cell[1:].isdigit() and int(cell[1:]) >= 51]
        assert len(scenario_rows) == expected_paths
        charts = [name for name in archive.namelist() if "/charts/chart" in name and name.endswith(".xml")]
        assert len(charts) == 1
        chart_text = archive.read(charts[0]).decode()
        assert "142D43" in chart_text and "B48035" in chart_text, "Exported line colors missing"
        assert "lineChart" in chart_text and "$E$44:$E$56" in chart_text and "$D$44:$D$56" in chart_text
        # The optional calcPr element is absent in this exporter. Excel's
        # default calculation mode is automatic; formulas and caches exist.
        return {"passed": True, "cached_formulas": formula_count, "independent_numeric_comparisons": comparisons,
                "fixed_scenario_paths": expected_paths, "fixed_events": expected_events, "sheet_count": len(sheets), "native_charts": len(charts)}


if __name__ == "__main__":
    print(json.dumps(validate(Path(sys.argv[1]) if len(sys.argv)>1 else DEFAULT), indent=2))
