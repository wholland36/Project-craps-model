"""Append immutable date-specific pregame research snapshots from JSON quote inputs.

This command never touches the private official wager ledger.
Example: python -m models.run_pregame --input fixtures.json --output results/forecasts.jsonl
"""
import argparse
import json
import os
from pathlib import Path
from .market_engine import Quote, Distribution, new_record

def run(source: Path, target: Path) -> dict:
    obj = json.loads(source.read_text(encoding="utf-8"))
    quotes = obj.get("quotes", [])
    if not isinstance(quotes, list) or not quotes:
        raise ValueError("Provide date-specific, documented pregame quotes")
    target.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if target.exists():
        with target.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    seen.add(json.loads(line)["snapshot_id"])
    rows = []
    for item in quotes:
        q = Quote(**{key: item[key] for key in Quote.__dataclass_fields__})
        d = Distribution(**item["distribution"]) if item.get("distribution") else None
        record = new_record(q, d, obj.get("release"), float(obj.get("bankroll", 0)))
        if record["snapshot_id"] not in seen:
            rows.append(record)
            seen.add(record["snapshot_id"])
    with target.open("a", encoding="utf-8") as f:
        for record in rows:
            f.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return {"new_snapshots": len(rows),
            "validated": sum(x["state"] == "VALIDATED QUALIFYING BET" for x in rows),
            "blocked": sum(bool(x["blockers"]) for x in rows),
            "official_wagers_added": 0, "path": str(target)}

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default=Path("results/forecasts.jsonl"), type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output), indent=2))

if __name__ == "__main__":
    main()
