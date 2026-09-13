#!/usr/bin/env python3
"""
rating_reference.py — regenerate samples/ml-stats/*.expected-ratings.json from rating.py.

ML.Ingest.MatchRating is a C# port of tools/vendor/efootball-re/mlstats/rating.py, and
MatchExportTests compares every player of the sample exports against these files. After
changing rating.py, run this, port the change, and the tests say whether the two still agree.

    python tools/rating_reference.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "efootball-re" / "mlstats"))
import rating  # noqa: E402

SAMPLES = REPO / "samples" / "ml-stats"


def main() -> int:
    exports = sorted(p for p in SAMPLES.glob("match_*.json") if not p.name.endswith(".expected-ratings.json"))
    for path in exports:
        rated = rating.rate_match(json.loads(path.read_text(encoding="utf-8")))
        out = {
            "source": path.name,
            "model": rating.MODEL,
            "generated_by": f"tools/vendor/efootball-re/mlstats/rating.py (model {rating.MODEL})",
            "teams": [{
                "side": team["side"],
                "players": [{
                    "slot": p["slot"],
                    "role": p["rating"]["role"],
                    "role_source": p["rating"]["role_source"],
                    "match_rating": p["rating"]["match_rating"],
                    "match_rating_unclamped": p["rating"]["match_rating_unclamped"],
                    "minutes_share": p["rating"]["derived"]["minutes_share"],
                } for p in team["players"]],
            } for team in rated["teams"]],
        }
        target = path.with_name(path.stem + ".expected-ratings.json")
        target.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"wrote {target.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
