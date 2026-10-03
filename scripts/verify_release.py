"""Verify source provenance, current code/input hashes, and saved ledgers."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bank_alm.verification import verify_release

if __name__ == "__main__":
    try:
        print(json.dumps(verify_release(), indent=2))
    except Exception as error:
        print(f"VERIFICATION FAILED: {error}", file=sys.stderr)
        sys.exit(1)
