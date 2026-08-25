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
/// carry team_kind + parent_team_id. Young deep-squad players seed the sides on first creation.
/// </summary>
public sealed partial class Session
{
    private const int YouthTeamBase = 9_000_000;
    private const int CareerTeamBase = 800_000;

    private static int YouthTeamId(int parentId, string kind) =>
        YouthTeamBase + (parentId - CareerTeamBase) * 2 + (kind == "u18" ? 1 : 0);

    /// <summary>
    /// The career-load entry point for the youth layer. Checks that the managed club's two
    /// sides ACTUALLY EXIST before believing the migration flag, and re-runs the bulk seed
    /// when they don't — so a career that lost them repairs itself on the next load.
    /// </summary>
    public void EnsureYouthTeamsOnLoad()
    {
        // THE BUG THIS REPLACES: the caller used to be `if (GetMeta("youth_teams_v1") is null)
        // { EnsureYouthTeams(); SetMeta(...); }` — one shot, flag written on completion, never
        // asked again. But tools/career_seed.py drops the whole youth layer on a reseed
        // ("DELETE FROM teams WHERE team_kind IN ('u21','u18')") while its meta cleanup only
        // wipes the chairman/manager/team-talk keys, so youth_teams_v1 survived at '1' over a
        // career whose sides were gone. Verified on the real career DB: flag '1', zero rows in
        // the youth id range, and the U21/U18 tabs reading teams that do not exist. (Demoting
        // a player still worked — MovePlayer calls EnsureYouthSide itself — so only the browse
        // path looked broken, which is why it survived so long.)
        //
        // A flag that records COMPLETION can never be the evidence that the work happened; the
        // teams table is. Hot path stays cheap: one primary-key lookup, and the bulk pass only
        // runs when there is something to repair.
        if (YouthSidesExist(CurrentTeamId) && GetMeta("youth_teams_v1") is not null) return;
        EnsureYouthTeams();
        // …and the managed club explicitly. EnsureYouthTeams only walks the two career
        // divisions; if yours somehow isn't in one (a hand-edited DB, a half-finished seed)
        // the check above would stay false forever and re-run the whole bulk pass on EVERY
        // load. A self-healing migration has to terminate, so heal the club we just tested.
        EnsureYouthSide(CurrentTeamId, CurrentTeamName, "u21");
        EnsureYouthSide(CurrentTeamId, CurrentTeamName, "u18");
        SetMeta("youth_teams_v1", "1");
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

    /// <summary>Create any missing U21/U18 sides for the career's clubs and seed them from the
    /// club's youngest deep-squad players. Idempotent — call on career load.</summary>
    public void EnsureYouthTeams()
    {
        var clubs = Repo.Teams()
            .Where(t => t.LeagueId is TopFlight or Division2)
            .Where(t => TeamKindOf(t.Id) == "first")
            .ToList();
        foreach (var club in clubs)
        {
            EnsureYouthSide(club.Id, club.Name, "u21");
            EnsureYouthSide(club.Id, club.Name, "u18");
        }
    }

    public string TeamKindOf(int teamId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT COALESCE(team_kind,'first') FROM teams WHERE id=$id";
        q.Parameters.AddWithValue("$id", teamId);
        return q.ExecuteScalar() as string ?? "first";
    }

    private void EnsureYouthSide(int parentId, string parentName, string kind)
    {
        var yid = YouthTeamId(parentId, kind);
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT 1 FROM teams WHERE id=$id";
            q.Parameters.AddWithValue("$id", yid);
            if (q.ExecuteScalar() is not null) return;   // already created
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
        // Seed: deep-squad players (slot > 22) young enough for this band move into the youth side,
        // so the senior XI/rotation (slots 0-22) is never disturbed.
        var (lo, hi) = kind == "u18" ? (0, 18) : (19, 21);
        var young = Repo.Squad(parentId)
            .Where(s => s.Slot > 22)
            .Select(s => s.PlayerId)
            .Where(pid => AgeOf(pid) is { } a && a >= lo && a <= hi)
            .ToList();
        var n = 0;
        foreach (var pid in young)
        {
            Repo.RemoveSquadMember(parentId, pid);
            Repo.SetSquadMember(new SquadMemberRow
            { TeamId = yid, PlayerId = pid, SquadNumber = ++n, Slot = n - 1 });
        }
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
        // The youth side must exist before anyone is moved into it. EnsureYouthTeams runs once
        // behind a meta flag, so a club that missed it (created later, promoted in) would swallow
        // the player into a team id with no row — he'd vanish from every squad view.
        // EnsureYouthSide is idempotent, so this costs one lookup in the normal case.
        if (toKind != "first") EnsureYouthSide(parentTeamId, TeamName(parentTeamId), toKind);

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
