"""Offline report build and source/output integrity controls."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(value, encoding="utf-8")
    pending.replace(path)


def fingerprint(root: Path = ROOT) -> dict[str, str]:
    paths = []
    for directory in ("bank_alm", "scripts", "configs", "data/processed", "data/raw"):
        paths.extend(path for path in (root / directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    paths.extend(root / name for name in ("requirements.txt", "pyproject.toml"))
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}


def validate_sources(root: Path = ROOT) -> tuple[dict, dict]:
    from scripts.fetch_bank_data import build_snapshot
    from scripts.prepare_curve import prepare

    snapshot = read_json(root / "data/processed/bank_snapshot.json")
    bundle = read_json(root / "data/raw/fdic_source_bundle.json")
    rebuilt = build_snapshot(bundle["source_records"], root=root)
    if snapshot != rebuilt:
        raise ValueError("Normalized bank snapshot differs from its verified FDIC source replay")
    curve = read_json(root / "data/processed/curve.json")
    reconstructed = prepare(snapshot["as_of"], write=False, root=root)
    if curve != reconstructed:
        raise ValueError("Normalized curve differs from its verified Federal Reserve source replay")
    if digest(root / "data/raw/fed_curve/selected_observation.json") != curve["selected_observation_sha256"]:
        raise ValueError("Saved Federal Reserve observation does not match the curve")
    from scripts.fetch_history import load_verified_calibration
    from scripts.fetch_maturity_data import load_verified_profile
    load_verified_calibration(root)
    load_verified_profile(root)
    return snapshot, curve


def to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    fields = list(dict.fromkeys(key for row in rows for key in row if not isinstance(row[key], (list, dict))))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def blocked_report(message: str) -> str:
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>ALM build blocked</title><style>body{font:18px system-ui;background:#0b1728;color:#f2efe8;max-width:760px;margin:12vh auto;padding:24px}p{line-height:1.6}code{color:#ffd7a2}</style><h1>Report build blocked</h1><p>' + html.escape(message) + '</p><p>Earlier JSON and CSV outputs may remain in this folder. They do not validate this build attempt. Read <code>run_status.json</code>, correct the source or model issue, and rebuild.</p></html>'


def build(output: Path | None = None) -> dict:
    destination = output or ROOT / "output"
    destination.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    write_json(destination / "run_status.json", {"status": "building", "started_at_utc": started})
    write_text(destination / "report.html", blocked_report("A new offline build is in progress."))
    write_text(destination / "reference_report.html", blocked_report("A new offline build is in progress."))
    try:
        from bank_alm.engine import run_analysis
        from bank_alm.report import render_report
        from bank_alm.research import prepare_research_inputs, evidence_summary
        from bank_alm.robustness import evaluate_robustness, audit_robustness
        from bank_alm.storage import compact_analysis, compact_challenges, write_gzip_json

        input_hashes = fingerprint()
        snapshot, curve = validate_sources()
        reference_assumptions = read_json(ROOT / "configs/assumptions.json")
        research = prepare_research_inputs(snapshot, reference_assumptions)
        assumptions = research["extended_assumptions"]
        reference = run_analysis(snapshot, reference_assumptions, curve)
        analysis = run_analysis(snapshot, assumptions, curve)
        analysis["schema_version"] = "bank-alm-analysis-v3"
        checks = analysis.get("checks", [])
        if not checks or any(check.get("passed") is not True for check in checks + reference.get("checks", [])):
            failed = [check.get("name", "unnamed") for check in checks if check.get("passed") is not True]
            raise ValueError("Numerical controls failed or absent: " + ", ".join(failed))
        from bank_alm.verification import audit_saved_analysis
        independent_audit = audit_saved_analysis(analysis, snapshot, assumptions)
        reference_audit = audit_saved_analysis(reference, snapshot, reference_assumptions)
        primary_challenges = evaluate_robustness(snapshot, assumptions, curve, analysis)
        reference_challenges = evaluate_robustness(snapshot, reference_assumptions, curve, reference)
        challenges = {"primary": primary_challenges, "reference": reference_challenges}
        challenge_audits = {"primary": audit_robustness(primary_challenges, snapshot, analysis), "reference": audit_robustness(reference_challenges, snapshot, reference)}
        analysis["research_evidence"] = evidence_summary(research, analysis, primary_challenges, reference_challenges)
        analysis["detail_storage"] = {"full_analysis": "analysis_full.json.gz", "aggregate_analysis": "analysis.json", "per_band_detail": "Opening and every monthly inventory, principal, credit-loss and sale allocation for every candidate are preserved in the full compressed analysis."}
        reference["detail_storage"] = {"full_analysis": "reference_analysis_full.json.gz", "aggregate_analysis": "reference_analysis.json", "per_band_detail": "Original aggregate research case, with complete policy accounting ledgers."}
        # Detect concurrent model/input edits while computation is in progress.
        if fingerprint() != input_hashes:
            raise ValueError("Source or implementation changed during this build; rerun with stable inputs")
        provenance = {
            "built_at_utc": started,
            "bank_as_of": snapshot["as_of"],
            "curve_as_of": curve["as_of"],
            "legal_entity": snapshot["legal_entity"],
            "source_records": snapshot["source_records"],
            "curve_source": curve["source"],
            "curve_source_captured_at": curve["source_captured_at"],
            "curve_limitations": curve["limitations"],
            "source_reconciliations": snapshot["reconciliations"],
            "input_hashes": input_hashes,
            "validation": "Exact offline source replay; numerical and ledger controls. Assumptions are illustrative, not independently calibrated to the bank.",
            "independent_ledger_audit": independent_audit,
            "reference_ledger_audit": reference_audit,
            "challenge_audits": challenge_audits,
            "historical_sources": research["history"]["source_records"],
            "maturity_sources": research["profile"]["source_records"],
        }
        write_gzip_json(destination / "analysis_full.json.gz", analysis)
        write_gzip_json(destination / "reference_analysis_full.json.gz", reference)
        write_gzip_json(destination / "robustness_full.json.gz", challenges)
        write_json(destination / "analysis.json", compact_analysis(analysis))
        write_json(destination / "reference_analysis.json", compact_analysis(reference))
        write_json(destination / "robustness.json", compact_challenges(challenges))
        write_json(destination / "research_evidence.json", analysis["research_evidence"])
        write_json(destination / "calibration.json", research["calibration"])
        write_json(destination / "maturity_profile.json", research["profile"])
        historical_rows = [{key: value for key, value in row.items() if not isinstance(value, (dict, list))} | {"quarter_" + key: value for key, value in row["quarter_flows_usd"].items()} for row in research["history"]["quarters"]]
        write_text(destination / "historical_data.csv", to_csv(historical_rows))
        challenge_rows = [{"model_case": model_case, **{key: value for key, value in case.items() if not isinstance(value, (dict, list))}} for model_case, result in challenges.items() for case in result["cases"]]
        write_text(destination / "robustness_summary.csv", to_csv(challenge_rows))
        write_json(destination / "provenance.json", provenance)
        write_text(destination / "scenario_summary.csv", to_csv(analysis["scenarios"]))
        monthly = [{"scenario_id": scenario["id"], **row} for scenario in analysis["scenarios"] for row in [scenario["initial_event"], *scenario["monthly"]]]
        write_text(destination / "monthly_ledgers.csv", to_csv(monthly))
        policies = analysis.get("policies", [])
        if isinstance(policies, dict):
            policies = policies.get("candidates", [])
        write_text(destination / "policy_comparison.csv", to_csv(policies))
        policy_scenarios = [{"policy_id": policy["id"], **scenario} for policy in policies for scenario in policy["scenarios"]]
        policy_events = [{"policy_id": policy["id"], "scenario_id": scenario["id"], **row} for policy in policies for scenario in policy["scenarios"] for row in [scenario["initial_event"], *scenario["monthly"]]]
        write_text(destination / "policy_scenarios.csv", to_csv(policy_scenarios))
        write_text(destination / "policy_ledgers.csv", to_csv(policy_events))
        write_text(destination / "hedge_comparison.csv", to_csv(analysis["hedge_comparison"]))
        write_json(destination / "independent_audit.json", independent_audit)
        write_json(destination / "reference_audit.json", reference_audit)
        write_json(destination / "robustness_audit.json", challenge_audits)
        write_text(destination / "report.html", render_report(analysis, provenance))
        write_text(destination / "reference_report.html", render_report(reference, provenance))
        artifacts = ["analysis.json", "analysis_full.json.gz", "reference_analysis.json", "reference_analysis_full.json.gz", "robustness.json", "robustness_full.json.gz", "research_evidence.json", "calibration.json", "maturity_profile.json", "historical_data.csv", "robustness_summary.csv", "provenance.json", "scenario_summary.csv", "monthly_ledgers.csv", "policy_comparison.csv", "policy_scenarios.csv", "policy_ledgers.csv", "hedge_comparison.csv", "independent_audit.json", "reference_audit.json", "robustness_audit.json", "report.html", "reference_report.html"]
        if fingerprint() != input_hashes:
            raise ValueError("Source or implementation changed while saving artifacts; rebuild with stable inputs")
        manifest = {
            "schema_version": 3,
            "status": "verified_build",
            "built_at_utc": started,
            "input_hashes": input_hashes,
            "artifact_hashes": {name: digest(destination / name) for name in artifacts},
            "technical_check_count": len(checks),
        }
        write_json(destination / "manifest.json", manifest)
        write_json(destination / "run_status.json", {"status": "verified_build", "started_at_utc": started, "manifest_sha256": digest(destination / "manifest.json"), "risk_decision": {"selected_policy_id": analysis["policies"]["selected_policy_id"], "feasible_count": analysis["policies"]["feasible_count"], "candidate_count": len(policies), "scope": "Model decision within the saved research scenarios and assumptions."}})
        return analysis
    except Exception as error:
        write_json(destination / "run_status.json", {"status": "blocked", "started_at_utc": started, "error": str(error)})
        write_text(destination / "report.html", blocked_report(str(error)))
        write_text(destination / "reference_report.html", blocked_report(str(error)))
        raise
