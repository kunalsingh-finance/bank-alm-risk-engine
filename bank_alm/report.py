"""Render the saved ALM analysis as a portable, script-safe research report."""

from __future__ import annotations

import html
import json
from .evidence_report import render_evidence
from .storage import compact_analysis
from pathlib import Path
from typing import Any


def render_report(analysis: dict[str, Any], provenance: dict[str, Any]) -> str:
    """Return standalone HTML; no network requests or model calculations occur here."""
    if not isinstance(analysis, dict) or not isinstance(provenance, dict):
        raise TypeError("analysis and provenance must be dictionaries")
    def scenario_ids(rows: Any) -> set[str]:
        if not isinstance(rows, list) or not rows:
            raise ValueError("The report requires at least one saved scenario per view")
        ids = [row.get("id") for row in rows if isinstance(row, dict)]
        if len(ids) != len(rows) or any(not isinstance(item, str) or not item for item in ids):
            raise ValueError("Each saved scenario requires a nonempty string id")
        if len(set(ids)) != len(ids):
            raise ValueError("Saved scenario ids must be unique within each view")
        return set(ids)

    reference_ids = scenario_ids(analysis.get("scenarios"))
    policy_view = analysis.get("policy_analysis")
    if policy_view is not None:
        if not isinstance(policy_view, dict):
            raise ValueError("Saved policy analysis must be a dictionary")
        if scenario_ids(policy_view.get("scenarios")) != reference_ids:
            raise ValueError("Policy and reference views require the same saved scenario ids")
        selection = policy_view.get("selection_status")
        policies = analysis.get("policies", {})
        if selection not in {"selected", "diagnostic_unselected"}:
            raise ValueError("Saved policy view requires an explicit selection status")
        if selection == "selected":
            candidate = next((row for row in policies.get("candidates", [])
                              if row.get("id") == policy_view.get("policy_id")), None)
            if (policies.get("selected_policy_id") != policy_view.get("policy_id")
                    or candidate is None or candidate.get("feasible") is not True):
                raise ValueError("A selected report view requires a matching feasible policy")
        elif policies.get("selected_policy_id") is not None:
            raise ValueError("An unselected diagnostic cannot accompany a selected policy")
    report_data = compact_analysis(analysis, for_report=True) if analysis.get("detail_storage") else analysis
    payload = json.dumps(
        {"analysis": report_data, "provenance": provenance},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    # JSON is data inside a raw-text HTML script element. Escaping '<' also prevents
    # an injected closing script tag; the Unicode separators cover older parsers.
    for literal, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                             ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        payload = payload.replace(literal, escaped)
    bank = analysis.get("bank", {})
    title = html.escape(str(bank.get("name", "Bank ALM")), quote=True)
    template = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
    verified_evidence = analysis.get("research_evidence") if analysis.get("checks") and all(check.get("passed") is True for check in analysis["checks"]) else None
    return template.replace("__REPORT_TITLE__", title).replace("__REPORT_DATA__", payload).replace("__RESEARCH_EVIDENCE__", render_evidence(verified_evidence)).replace("__EVIDENCE_NAV__", '<a href="#research-evidence">Historical evidence</a>' if verified_evidence else "")


def write_report(path: str | Path, analysis: dict[str, Any], provenance: dict[str, Any]) -> Path:
    """Write a report after rendering succeeds, returning its destination."""
    destination = Path(path)
    rendered = render_report(analysis, provenance)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    return destination
