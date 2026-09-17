"""Derive each dt200 club's real name from the reference world, by the players they share.

A dt200 club Konami left unlicensed carries an invented name ("Albacete BN") but the REAL squad:
eFootball's players are real even when the club's name is not. master.db's reference world holds
the same clubs under their real names with their own squads. So the two are matched on the players
themselves — surname + age, which survives both naming styles ("Antonio Puertas" / "Puertas") —
and never on the club name, which is the thing we are trying to recover.

Writes a review CSV; decides nothing on its own.
"""
import csv, re, sqlite3, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

WORLD = "file:build/game_world.db?mode=ro"
MASTER = "file:build/master.db?mode=ro&immutable=1"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("club_names_review.csv")

# A name the game invented: "<place> <2-4 capitals>", where the capitals are not a real suffix.
REAL_SUFFIX = {"FC", "CF", "AC", "SC", "AFC", "CD", "SD", "SV", "BK", "IF", "FK", "SK", "US", "UD",
               "RC", "CA", "CP", "BC", "SCO", "AS", "PSV", "PSG", "TSG", "VfB", "VfL", "FSV", "SpVgg",
               "MSV", "KV", "KAA", "RKC", "NEC", "ADO", "AZ", "SBV", "FCO", "OGC", "RCD", "UC", "SS"}
INVENTED = re.compile(r"^(?P<base>.+?) (?P<tag>[A-Z]{1,4})$")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


def surname(name: str) -> str:
    parts = [p for p in re.split(r"[\s.]+", fold(name)) if len(p) > 1]
    return parts[-1] if parts else ""


def looks_invented(name: str) -> bool:
    m = INVENTED.match(name)
    return bool(m) and m.group("tag") not in REAL_SUFFIX


def main() -> int:
    w = sqlite3.connect(WORLD, uri=True)
    m = sqlite3.connect(MASTER, uri=True)

    clubs = {}          # dt200 id -> (name, league)
    for tid, name, league in w.execute("""
            SELECT t.base_team_id, t.name, COALESCE(l.name, '')
            FROM teams t LEFT JOIN leagues l ON l.id = t.league_id
            WHERE t.base_team_id IS NOT NULL GROUP BY t.base_team_id"""):
        clubs[tid] = (name, league)

    squads = defaultdict(list)
    for tid, pname, age in w.execute("""
            SELECT t.base_team_id, p.name, p.age FROM squad_members s
            JOIN players p ON p.id = s.player_id JOIN teams t ON t.id = s.team_id
            WHERE t.base_team_id IS NOT NULL"""):
        if surname(pname):
            squads[tid].append((surname(pname), age))

    # The reference world: every club that is not one of dt200's own mirror rows.
    ref_name, ref_league = {}, {}
    for tid, name, league in m.execute("""
            SELECT t.id, t.name, COALESCE(l.name, '') FROM teams t LEFT JOIN leagues l ON l.id = t.league_id"""):
        if tid in clubs or looks_invented(name):
            continue                      # a mirror of the dt200 row, or itself unnamed
        ref_name[tid] = name
        ref_league[tid] = league

    index = defaultdict(set)              # (surname, age) -> reference clubs holding that player
    loose = defaultdict(set)              # surname only, for a weaker second vote
    for tid, pname, age in m.execute("""
            SELECT s.team_id, p.name, p.age FROM squad_members s JOIN players p ON p.id = s.player_id
            WHERE p.superseded_by IS NULL"""):
        if tid not in ref_name:
            continue
        sn = surname(pname)
        if not sn:
            continue
        index[(sn, age)].add(tid)
        loose[sn].add(tid)

    rows = []
    for tid, (name, league) in sorted(clubs.items()):
        squad = squads.get(tid, [])
        votes = Counter()
        for sn, age in squad:
            for cand in index.get((sn, age), ()):        # exact: surname + age
                votes[cand] += 2
            for cand in loose.get(sn, ()):               # weaker: surname alone
                votes[cand] += 1
        best = votes.most_common(2)
        top, top_score = (best[0] if best else (None, 0))
        runner, runner_score = (best[1] if len(best) > 1 else (None, 0))
        rows.append({
            "team_id": tid,
            "current": name,
            "league": league,
            "invented": "yes" if looks_invented(name) else "",
            "proposed": ref_name.get(top, ""),
            "match_league": ref_league.get(top, ""),
            "match_id": top or "",
            "score": top_score,
            "runner_up": ref_name.get(runner, ""),
            "runner_score": runner_score,
            "squad": len(squad),
        })

    with OUT.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    inv = [r for r in rows if r["invented"]]
    named = [r for r in inv if r["proposed"] and r["score"] >= 8 and r["score"] >= 2 * r["runner_score"]]
    print(f"world clubs {len(rows)}, invented-looking {len(inv)}")
    print(f"confident matches among them: {len(named)}")
    print(f"wrote {OUT}")
    for r in named[:25]:
        print(f"   {r['team_id']:6d} {r['current']:26s} -> {r['proposed']:30s} "
              f"score {r['score']:3d} (runner {r['runner_score']:3d}) [{r['league']} / {r['match_league']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
