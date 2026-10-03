"""Static, escaped evidence panels for the portable report."""
from __future__ import annotations

import html
import math


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(value: object) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "Not available"
    return ("−" if value < 0 else "") + "$" + f"{abs(value) / 1e9:,.3f}bn"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    return '<div class="table-wrap"><table class="data-table"><thead><tr>' + "".join("<th>" + _text(h) + "</th>" for h in headers) + '</tr></thead><tbody>' + "".join("<tr>" + "".join("<td>" + _text(value) + "</td>" for value in row) + "</tr>" for row in rows) + "</tbody></table></div>"


def render_evidence(evidence: dict | None) -> str:
    if not evidence:
        return ""
    title = evidence.get("case_label", "Extended public-data case")
    output = ['<section class="wide-block" id="research-evidence"><div class="section-heading"><div><span class="eyebrow">Evidence &amp; independent challenges</span><h2>' + _text(title) + '</h2></div><span class="small-note">The original aggregate case remains available for method comparison.</span></div>']
    output.append('<div class="scope-note"><strong>' + _text(evidence.get("decision_context", "")) + '</strong> <a href="reference_report.html">Open original aggregate case</a> · <a href="research_evidence.json">Download evidence summary</a></div>')
    output.append('<div class="split-section">')
    calibration = evidence.get("calibration", {})
    output.append('<article class="card"><h3>Historical deposit-cost calibration</h3><p class="objective-note">' + _text(calibration.get("description", "Historical results pending")) + '</p>')
    for key in ("fit_description", "holdout_description", "availability_note", "denominator_note"):
        if calibration.get(key):
            output.append('<p class="table-caption">' + _text(calibration[key]) + "</p>")
    if calibration.get("metric_rows"):
        output.append(_table(["Evaluation", "Model", "Benchmark"], calibration["metric_rows"]))
    if calibration.get("prediction_rows"):
        output.append('<details style="margin-top:16px"><summary class="details-title">Chronological holdout predictions</summary><div class="details-body">' + _table(["Quarter", "Observed proxy", "Model prediction", "Benchmark"], calibration["prediction_rows"]) + "</div></details>")
    output.append('<p class="table-caption"><a href="calibration.json">Calibration evidence</a> · <a href="historical_data.csv">Quarterly source series</a></p></article>')
    coverage = evidence.get("coverage", {})
    output.append('<article class="card"><h3>Sourced maturities &amp; asset availability</h3><p class="objective-note">' + _text(coverage.get("description", "")) + '</p>')
    if coverage.get("rows"):
        output.append(_table(["Reconciliation", "USD"], [[row[0], _money(row[1])] for row in coverage["rows"]]))
    for note in coverage.get("notes", []):
        output.append('<p class="table-caption">' + _text(note) + "</p>")
    output.append('<p class="table-caption"><a href="maturity_profile.json">Maturity source and reconciliation</a></p></article></div>')
    costs = evidence.get("business_costs", {})
    output.append('<article class="card" style="margin-top:20px"><h3>Operating costs &amp; credit-loss assumptions</h3><p class="objective-note">' + _text(costs.get("description", "")) + '</p>')
    if costs.get("rows"):
        output.append(_table(["Driver", "Applied assumption", "Evidence / convention"], costs["rows"]))
    output.append('</article>')
    challenge = evidence.get("robustness", {})
    output.append('<article class="card" style="margin-top:20px"><h3>Frozen-policy challenge results</h3><p class="objective-note">' + _text(challenge.get("description", "")) + '</p>')
    if challenge.get("summary_rows"):
        output.append(_table(["Case family", "Policy tested", "Passed", "Failed"], challenge["summary_rows"]))
    if challenge.get("case_rows"):
        output.append('<details style="margin-top:16px"><summary class="details-title">Unseen scenarios, behavioral uncertainty &amp; alternate curves</summary><div class="details-body">' + _table(["Challenge", "Result", "Modeled earnings", "EVE change"], challenge["case_rows"]) + '</div></details>')
    for note in challenge.get("notes", []):
        output.append('<p class="table-caption">' + _text(note) + "</p>")
    output.append('<p class="table-caption"><a href="robustness.json">Complete challenge ledgers</a> · <a href="robustness_summary.csv">Challenge comparison</a></p></article></section>')
    return "".join(output)
