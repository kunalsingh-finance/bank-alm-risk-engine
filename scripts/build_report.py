"""Build the dated bank ALM research report without network access."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bank_alm.pipeline import build

if __name__ == "__main__":
    try:
        result = build()
    except Exception as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"Built {len(result['scenarios'])} reference scenarios and {len(result['policies']['candidates'])} joint policies; {len(result['checks'])} technical controls and the independent ledger audit passed.")
    print(ROOT / "output" / "report.html")
