using ML.Data;

namespace ML.App;

// Player ids run past Int32 (the imported world is unbounded) — the id is a long everywhere else
// in the app, and must be one here too or YouthSquad throws on read.
public sealed record YouthPlayerRow(
    long PlayerId, string Name, int Age, int Overall, string Position, int Potential, string Level);

/// <summary>
/// U21 / U18 youth sides (the youth-teams vision): every senior club owns two youth teams, players
/// move freely between first team ⇄ U21 ⇄ U18, and academy intakes land in the youth setup. Youth
/// teams live in a dedicated id range (never rendered in-game — they're a management layer) and
/// carry team_kind + parent_team_id. Young deep-squad players seed the sides when a career is
/// first built — and ONLY then; see EnsureYouthSide.
/// </summary>
public sealed partial class Session
{
    private const int YouthTeamBase = 9_000_000;
    private const int CareerTeamBase = 800_000;

    /// <summary>Meta key holding what the last youth-setup repair did (date|sides).</summary>
    private const string YouthRepairKey = "youth_repair_v1";

    private static int YouthTeamId(int parentId, string kind) =>
        YouthTeamBase + (parentId - CareerTeamBase) * 2 + (kind == "u18" ? 1 : 0);

    /// <summary>
    /// The career-load entry point for the youth layer. Checks that the managed club's two
    /// sides ACTUALLY EXIST before believing the migration flag, and re-creates them when they
    /// don't — so a career that lost them repairs itself on the next load.
    /// </summary>
    public void EnsureYouthTeamsOnLoad()
    {
        // THE BUG THIS REPLACES (1 of 2): the caller used to be `if (GetMeta("youth_teams_v1")
        // is null) { EnsureYouthTeams(); SetMeta(...); }` — one shot, flag written on
        // completion, never asked again. But tools/career_seed.py drops the whole youth layer on
        // a reseed ("DELETE FROM teams WHERE team_kind IN ('u21','u18')") while its meta cleanup
        // only wipes the chairman/manager/team-talk keys, so youth_teams_v1 survived at '1' over
        // a career whose sides were gone. Verified on the real career DB: flag '1', zero rows in
        // the youth id range, and the U21/U18 tabs reading teams that do not exist. (Demoting
        // a player still worked — MovePlayer calls EnsureYouthSide itself — so only the browse
        // path looked broken, which is why it survived so long.)
        //
        // A flag that records COMPLETION can never be the evidence that the work happened; the
        // teams table is. Hot path stays cheap: one primary-key lookup, and the rebuild only
        // runs when there is something to repair.
        if (YouthSidesExist(CurrentTeamId) && GetMeta("youth_teams_v1") is not null) return;

        // THE BUG THIS REPLACES (2 of 2), and the dangerous one. The repair above ran the FULL
        // bulk pass, and EnsureYouthSide did two different jobs in one breath: it created the
        // side, then SEEDED it by moving every deep-squad player of the right age out of the
        // senior squad. On the real career DB that is 1,234 players out of 44 first teams —
        // Manchester United 92 down to 30, Tottenham 85 down to 29 — reorganised during the
        // Session constructor, on startup, under a bare catch, with nothing on screen to say it
        // happened and no way to undo it. The manager never asked.
        //
        // Seeding the sides from the deep squad is right ONCE: when the career is built and
        // nobody has arranged anything yet. After that, creating the teams is a repair and
        // moving players is vandalism. So the two jobs are split, and only a career that has
        // never been played gets the seed.
        var firstBuild = CareerHasNotBegun();
        var created = EnsureYouthTeams(firstBuild);
        // …and the managed club explicitly. EnsureYouthTeams only walks the two career
        // divisions; if yours somehow isn't in one (a hand-edited DB, a half-finished seed)
        // the check above would stay false forever and re-run the whole pass on EVERY load.
        // A self-healing migration has to terminate, so heal the club we just tested.
        if (EnsureYouthSide(CurrentTeamId, CurrentTeamName, "u21", firstBuild)) created++;
        if (EnsureYouthSide(CurrentTeamId, CurrentTeamName, "u18", firstBuild)) created++;
        SetMeta("youth_teams_v1", "1");

        // A repair that changed the shape of the club's setup gets said out loud. A brand-new
        // career doesn't need telling — the sides arriving full IS the career being built.
        if (!firstBuild && created > 0) RecordYouthRepair(created);
    }

    /// <summary>Do BOTH youth sides of this club exist? One primary-key lookup.</summary>
    public bool YouthSidesExist(int parentTeamId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT COUNT(*) FROM teams WHERE id IN ($u21,$u18)";
        q.Parameters.AddWithValue("$u21", YouthTeamId(parentTeamId, "u21"));
        q.Parameters.AddWithValue("$u18", YouthTeamId(parentTeamId, "u18"));
        // A row COUNT, not an id — Int32 is correct here. (Ids in this world run past Int32;
        // they are longs everywhere. Don't "tidy" this into a pattern for id reads.)
        return Convert.ToInt32(q.ExecuteScalar()) == 2;
    }

    /// <summary>
    /// Has a single thing happened in this career yet? tools/career_seed.py clears every career
    /// result and the whole inbox when it builds a save, and the Session constructor writes the
    /// board's objectives and the welcome letter at the END of the very first load — so "no
    /// result on file and not one letter in the inbox" is an honest test for a career whose
    /// first launch is happening right now, and it stops being true forever afterwards.
    ///
    /// Anything we cannot prove is brand new is treated as in progress: the cost of guessing
    /// wrong that way is two empty youth sides, and the cost of guessing wrong the other way is
    /// a thousand players relocated behind the manager's back.
    /// </summary>
    private bool CareerHasNotBegun()
    {
        try
        {
            using var q = Db.Connection.CreateCommand();
            q.CommandText = "SELECT (SELECT EXISTS(SELECT 1 FROM results)) + " +
                            "(SELECT EXISTS(SELECT 1 FROM inbox))";
            return Convert.ToInt32(q.ExecuteScalar()) == 0;
        }
        catch
        {
            return false;   // an older DB missing a table proves nothing — never seed on a guess
        }
    }

    /// <summary>Create any missing U21/U18 sides for the career's clubs. Creation only — not one
    /// player is moved. Idempotent.</summary>
    public void EnsureYouthTeams() => EnsureYouthTeams(seedFromDeepSquad: false);

    /// <summary>
    /// Create any missing U21/U18 sides for the career's clubs, returning how many were created.
    /// When <paramref name="seedFromDeepSquad"/> is set — a career that has never been played —
    /// each new side is also filled from its club's young deep-squad players. Idempotent.
    /// </summary>
    public int EnsureYouthTeams(bool seedFromDeepSquad)
    {
        var clubs = Repo.Teams()
            .Where(t => t.LeagueId is TopFlight or Division2)
            .Where(t => TeamKindOf(t.Id) == "first")
            .ToList();
        var created = 0;
        foreach (var club in clubs)
        {
            if (EnsureYouthSide(club.Id, club.Name, "u21", seedFromDeepSquad)) created++;
            if (EnsureYouthSide(club.Id, club.Name, "u18", seedFromDeepSquad)) created++;
        }
        return created;
    }

    public string TeamKindOf(int teamId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT COALESCE(team_kind,'first') FROM teams WHERE id=$id";
        q.Parameters.AddWithValue("$id", teamId);
        return q.ExecuteScalar() as string ?? "first";
    }

    /// <summary>
    /// Create one club's U21 or U18 side if it is missing; true when it created one.
    /// CREATION AND SEEDING ARE SEPARATE JOBS — the new side stays empty unless the caller can
    /// say the career has not begun. Every caller that runs on a live career passes false.
    /// </summary>
    private bool EnsureYouthSide(int parentId, string parentName, string kind, bool seedFromDeepSquad)
    {
        var yid = YouthTeamId(parentId, kind);
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT 1 FROM teams WHERE id=$id";
            q.Parameters.AddWithValue("$id", yid);
            if (q.ExecuteScalar() is not null) return false;   // already created
        }
        var label = kind.ToUpperInvariant();
        using (var ins = Db.Connection.CreateCommand())
        {
            ins.CommandText =
                "INSERT INTO teams(id,game_team_id,is_custom,name,short_name,league_id,budget," +
                "parent_team_id,team_kind) VALUES($id,$g,1,$n,$s,NULL,0,$p,$k)";
            ins.Parameters.AddWithValue("$id", yid);
            ins.Parameters.AddWithValue("$g", yid);
            ins.Parameters.AddWithValue("$n", $"{parentName} {label}");
            ins.Parameters.AddWithValue("$s", label);
            ins.Parameters.AddWithValue("$p", parentId);
            ins.Parameters.AddWithValue("$k", kind);
            ins.ExecuteNonQuery();
        }
        // The team cache is built once, before this runs (Session's constructor touches it on
        // line 1). Without this drop, TeamName/TeamLogoPath answer "?" and null for a side
        // created during this session — a youth lad's profile would show no club name.
        _teamCache = null;
        if (seedFromDeepSquad) SeedYouthSideFromDeepSquad(parentId, yid, kind);
        return true;
    }

    /// <summary>
    /// Fill a just-created youth side from its club's deep squad: players below slot 23 are the
    /// senior XI and rotation and are never touched, so only the tail of the squad moves, and
    /// only lads inside this level's age band.
    /// ONLY EVER CALLED FOR A CAREER THAT HAS NOT BEGUN — see EnsureYouthTeamsOnLoad.
    /// </summary>
    private void SeedYouthSideFromDeepSquad(int parentId, int youthTeamId, string kind)
    {
        var (lo, hi) = kind == "u18" ? (0, 18) : (19, 21);
        var moving = new List<long>();
        using (var q = Db.Connection.CreateCommand())
        {
            // One read for the whole side. It used to be a full squad load followed by an age
            // query PER PLAYER, and a big club's deep squad is ninety names — times two levels,
            // times every club in both divisions.
            q.CommandText =
                "SELECT s.player_id FROM squad_members s JOIN players p ON p.id = s.player_id " +
                "WHERE s.team_id = $t AND s.slot > 22 AND p.age BETWEEN $lo AND $hi " +
                "ORDER BY s.slot";
            q.Parameters.AddWithValue("$t", parentId);
            q.Parameters.AddWithValue("$lo", lo);
            q.Parameters.AddWithValue("$hi", hi);
            using var r = q.ExecuteReader();
            // A player id is a long — most of this world's squad rows sit above Int32.
            while (r.Read()) moving.Add(r.GetInt64(0));
        }
        var n = 0;
        foreach (var pid in moving)
        {
            n++;
            using var move = Db.Connection.CreateCommand();
            // ONE statement per player, not a DELETE followed by an INSERT. The pair left the
            // lad belonging to no club at all in between, and this pass runs inside the Session
            // constructor under a bare catch — an exception between the two halves lost him.
            // role resets to 0: the armband and the set-piece duties belong to the squad he
            // came from, not to the youth side.
            move.CommandText =
                "UPDATE squad_members SET team_id=$y, squad_number=$n, slot=$s, role=0 " +
                "WHERE team_id=$p AND player_id=$pid";
            move.Parameters.AddWithValue("$y", youthTeamId);
            move.Parameters.AddWithValue("$n", n);
            move.Parameters.AddWithValue("$s", n - 1);
            move.Parameters.AddWithValue("$p", parentId);
            move.Parameters.AddWithValue("$pid", pid);
            move.ExecuteNonQuery();
        }
    }

    /// <summary>
    /// Leave a trace of a repair the manager did not ask for: a meta record any screen can read,
    /// then a letter in his inbox. The record goes down FIRST — if the inbox write fails, the
    /// empty sides can still explain themselves.
    /// </summary>
    private void RecordYouthRepair(int sidesCreated)
    {
        SetMeta(YouthRepairKey, $"{DateTime.Now:yyyy-MM-dd}|{sidesCreated}");
        PostInbox("Club", "Your youth setup has been rebuilt",
            "Our records had lost the U21 and U18 sides themselves — the age-group teams, not " +
            $"the players in them. They have been set up again: {sidesCreated} sides across the " +
            "two divisions, yours among them.\n\n" +
            "Nobody has been moved. Your first team is exactly the squad you left, and the youth " +
            "sides start empty on purpose — we are not reshuffling your squad while your back " +
            "is turned.\n\n" +
            "To put a lad on one of them: right-click him on the Squad screen and send him down, " +
            "or use \"Send an under-21 down\" on the Academy screen. He comes back up whenever " +
            "you want him.",
            teamId: CurrentTeamId);
    }

    /// <summary>
    /// What the last youth-setup repair did, in a sentence, or null if there has never been one.
    /// A screen showing empty U21/U18 sides can use this so the emptiness explains itself.
    /// </summary>
    public string? YouthRepairNote()
    {
        var raw = GetMeta(YouthRepairKey);
        if (string.IsNullOrEmpty(raw)) return null;
        var parts = raw.Split('|');
        if (parts.Length < 2 || !int.TryParse(parts[1], out var sides) || sides <= 0) return null;
        // Stored exact (yyyy-MM-dd), read back exact, shown in the reader's own language.
        var when = DateOnly.TryParseExact(parts[0], "yyyy-MM-dd", out var d)
            ? d.ToString("d MMM yyyy")
            : parts[0];
        return $"Your youth setup was rebuilt on {when}: {sides} age-group " +
               $"{(sides == 1 ? "side was" : "sides were")} re-created empty, and no player was " +
               "moved out of a first-team squad.";
    }

    private int? AgeOf(long playerId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT age FROM players WHERE id=$p";
        q.Parameters.AddWithValue("$p", playerId);
        var v = q.ExecuteScalar();
        return v is null or DBNull ? null : Convert.ToInt32(v);
    }

    /// <summary>The U21 or U18 squad of a senior club.</summary>
    public IReadOnlyList<YouthPlayerRow> YouthSquad(int parentTeamId, string kind)
    {
        var yid = YouthTeamId(parentTeamId, kind);
        var rows = new List<YouthPlayerRow>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT p.id, p.name, COALESCE(p.age,0), COALESCE(p.overall_rating,0), " +
            "COALESCE(p.position,'') FROM squad_members s JOIN players p ON p.id=s.player_id " +
            "WHERE s.team_id=$t ORDER BY p.overall_rating DESC";
        cmd.Parameters.AddWithValue("$t", yid);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            var pid = r.GetInt64(0);
            rows.Add(new YouthPlayerRow(pid, r.GetString(1), r.GetInt32(2),
                r.GetInt32(3), r.GetString(4), PotentialOf(pid), kind.ToUpperInvariant()));
        }
        return rows;
    }

    /// <summary>Promote a youth player to the senior squad.</summary>
    public string PromoteToSenior(long playerId, int parentTeamId)
    {
        return MovePlayer(playerId, parentTeamId, "first");
    }

    /// <summary>Send a player down to a youth side (U21/U18).</summary>
    public string DemoteToYouth(long playerId, int parentTeamId, string kind)
    {
        var age = AgeOf(playerId) ?? 25;
        if (kind == "u18" && age > 18) return "Too old for the U18s.";
        if (kind == "u21" && age > 21) return "Too old for the U21s.";
        return MovePlayer(playerId, parentTeamId, kind);
    }

    private string MovePlayer(long playerId, int parentTeamId, string toKind)
    {
        // The youth side must exist before anyone is moved into it. A club that missed the
        // career-load pass (created later, promoted in) would otherwise swallow the player into
        // a team id with no row — he'd vanish from every squad view. EnsureYouthSide is
        // idempotent, so this costs one lookup in the normal case.
        //
        // THE BUG: this call used to seed as well as create. Sending ONE lad to the U21s at a
        // club whose side didn't exist yet quietly relocated every other young deep-squad player
        // with him — the manager asked to move one name and lost twenty off his squad list.
        // Creating a side is never permission to reorganise a squad.
        if (toKind != "first")
            EnsureYouthSide(parentTeamId, TeamName(parentTeamId), toKind, seedFromDeepSquad: false);

        var dest = toKind == "first" ? parentTeamId : YouthTeamId(parentTeamId, toKind);
        // remove from whichever of the three sides currently holds him
        foreach (var tid in new[] { parentTeamId, YouthTeamId(parentTeamId, "u21"),
                                    YouthTeamId(parentTeamId, "u18") })
            Repo.RemoveSquadMember(tid, playerId);
        var squad = Repo.Squad(dest);
        var used = squad.Select(s => s.SquadNumber).ToHashSet();
        var shirt = Enumerable.Range(1, 99).FirstOrDefault(x => !used.Contains(x), 99);
        Repo.SetSquadMember(new SquadMemberRow
        { TeamId = dest, PlayerId = playerId, SquadNumber = shirt, Slot = squad.Count });
        var name = PlayerBasics(playerId).Name;
        return toKind == "first"
            ? $"{name} promoted to the first team (shirt {shirt})."
            : $"{name} moved to the {toKind.ToUpperInvariant()}s.";
    }
}
