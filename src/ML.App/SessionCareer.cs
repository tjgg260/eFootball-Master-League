using ML.Core;
using ML.Core.Management;
using ML.Data;

namespace ML.App;

public sealed record JobOffer(int TeamId, string Club, string League, int SquadRating);

/// <summary>
/// The manager's own career (D2): persistent reputation, a board whose patience runs out in a
/// real sacking, and rival clubs who come calling when your name is big enough. The pure rules
/// live in ML.Core.Management.ManagerCareer; this partial owns the persistence and the club data.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ reputation

    public int Reputation
    {
        get => GetMeta("manager_rep") is { } v && int.TryParse(v, out var n) ? n : ManagerCareer.StartingRep;
        private set => SetMeta("manager_rep", Math.Clamp(value, ManagerCareer.RepMin, ManagerCareer.RepMax).ToString());
    }

    public string ReputationLabel => ManagerCareer.RepLabel(Reputation);

    // ------------------------------------------------------------------ the board, persisted

    /// <summary>Stored confidence, surviving app restarts (the ctor seeds Board from this).</summary>
    private int StoredBoardConfidence
    {
        get => GetMeta("board_conf") is { } v && int.TryParse(v, out var n) ? n : 58;
        set => SetMeta("board_conf", Math.Clamp(value, BoardConfidence.Min, BoardConfidence.Max).ToString());
    }

    private int ThreatStreak
    {
        get => GetMeta("board_threat_streak") is { } v && int.TryParse(v, out var n) ? n : 0;
        set => SetMeta("board_threat_streak", value.ToString());
    }

    /// <summary>Where this squad ranks by strength among its league rivals (1 = strongest).</summary>
    private int StrengthRank(int teamId, int leagueId)
    {
        var mine = SquadStrengthOf(teamId);
        return 1 + Repo.TeamsIn(leagueId).Count(t => t.Id != teamId && SquadStrengthOf(t.Id) > mine);
    }

    /// <summary>The board's demand for this club this season, derived from squad strength.</summary>
    private Expectation DeriveExpectation()
    {
        var teams = Repo.TeamsIn(LeagueId).Count;
        if (teams == 0) return Expectation.MidTable;
        return ManagerCareer.ExpectationFor(StrengthRank(CurrentTeamId, LeagueId), teams, LeagueId == TopFlight);
    }

    // ------------------------------------------------------------------ after your result

    /// <summary>
    /// Apply YOUR recorded result to the board and your reputation, then let the board act.
    /// League games move confidence against the table; every competitive game moves reputation.
    /// </summary>
    public void ApplyCareerAfterResult(int homeId, int awayId, int homeGoals, int awayGoals, string kind)
    {
        if (kind == "friendly" || IsSacked) return;
        var youAreHome = homeId == CurrentTeamId;
        var us = youAreHome ? homeGoals : awayGoals;
        var them = youAreHome ? awayGoals : homeGoals;
        var oppId = youAreHome ? awayId : homeId;
        var oppStronger = SquadStrengthOf(oppId) > SquadStrengthOf(CurrentTeamId);

        Reputation = ManagerCareer.RepAfterResult(Reputation, us, them, oppStronger);

        if (kind != "league") return;
        var teams = Repo.TeamsIn(LeagueId).Count;
        var target = ManagerCareer.TargetPosition(Board.Expectation, teams);
        Board.ApplyResult(us, them, CurrentPosition(), target);
        StoredBoardConfidence = Board.Value;

        // The SACK reads the composite, not the result-driven half. Board.Value knows only
        // what the last league game did to you; the swing meta carries the season verdict, the
        // mid-season review and every budget ask. A manager whose board had been talked down to
        // 12 was being judged on the 40-odd the results alone said, and kept his job.
        ThreatStreak = BoardNow.ManagerUnderThreat ? ThreatStreak + 1 : 0;
        // Settings: sacking leniency shifts how long the board waits.
        var patienceShift = (GetMeta("sack_leniency") ?? "Normal") switch
        {
            "Patient" => 3, "Ruthless" => -2, _ => 0,
        };
        if (ManagerCareer.ShouldSack(BoardConfidenceNow, ThreatStreak - patienceShift))
        {
            SackManager();
        }
        else if (BoardNow.ManagerUnderThreat && ThreatStreak == ManagerCareer.BoardPatience - 1)
        {
            PostInbox("Board", "Final warning",
                $"Chairman {Chairman()} has seen enough. Without an immediate upturn in results, " +
                "the board will make a change.", NextFixture()?.Matchday);
        }
    }

    // ------------------------------------------------------------------ the sack

    public bool IsSacked => GetMeta("sacked") == "1";

    private void SackManager()
    {
        if (IsSacked) return;
        SetMeta("sacked", "1");
        SetMeta("sacked_line",
            $"Dismissed by {CurrentTeamName} in {SeasonYear}, sitting {CurrentPosition()} in the {LeagueName}.");
        PostInbox("Board", "You have been dismissed",
            $"Chairman {Chairman()} thanks you for your service, but results have fallen short of the " +
            $"board's expectations and {CurrentTeamName} will seek a new direction. " +
            "Offers from other clubs — if any come — will arrive here. See the Board screen.",
            NextFixture()?.Matchday);
        GenerateJobOffers(desperation: true);
    }

    public string SackedLine => GetMeta("sacked_line") ?? "";

    /// <summary>Career summary for the game-over screen and the Board page.</summary>
    public string CareerSummary()
    {
        var seasons = SeasonId - 9000 + 1;
        int w = 0, d = 0, l = 0;
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT r.home_goals, r.away_goals, f.home_team_id FROM results r " +
                "JOIN fixtures f ON f.id = r.fixture_id " +
                "WHERE (f.home_team_id=$t OR f.away_team_id=$t) AND f.kind != 'friendly'";
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                var us = r.GetInt32(2) == CurrentTeamId ? r.GetInt32(0) : r.GetInt32(1);
                var them = r.GetInt32(2) == CurrentTeamId ? r.GetInt32(1) : r.GetInt32(0);
                if (us > them) w++;
                else if (us == them) d++;
                else l++;
            }
        }
        var trophies = Honours().Count(h => h.Team == CurrentTeamName);
        return $"{seasons} season{(seasons == 1 ? "" : "s")} · record {w}W {d}D {l}L · " +
               $"{trophies} troph{(trophies == 1 ? "y" : "ies")} · {ReputationLabel}";
    }

    // ------------------------------------------------------------------ job offers

    /// <summary>
    /// Clubs that would take you: seeded per season, filtered by the pure rep rule. Desperation
    /// offers (after a sacking) come from the lower reaches so there is always a way back.
    /// </summary>
    public void GenerateJobOffers(bool desperation)
    {
        var clubs = Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2 && t.Id != CurrentTeamId).ToList();
        if (clubs.Count == 0) return;
        var ranked = clubs.OrderByDescending(t => SquadStrengthOf(t.Id)).ToList();
        var eligible = ranked
            .Select((t, i) => (Team: t, Rank: i + 1))
            .Where(x => ManagerCareer.ClubWouldOffer(
                desperation ? Math.Max(Reputation, 25) : Reputation, x.Rank, ranked.Count))
            .ToList();
        if (eligible.Count == 0) return;

        var rng = new SeededRandom((SeasonId * 8929 + Reputation * 31 + (desperation ? 7 : 0)) ^ WorldSeed);
        var picked = eligible.OrderBy(_ => rng.Next(1_000_000)).Take(2).Select(x => x.Team.Id).ToList();
        SetMeta("job_offers", string.Join(",", picked));
        var stampMd = NextFixture()?.Matchday;
        foreach (var tid in picked)
        {
            PostInbox("Board", $"Job offer: {TeamName(tid)}",
                $"{TeamName(tid)} have approached you about their vacant manager's position. " +
                "Accept from the Board screen — your current post ends the moment you do.", stampMd,
                teamId: tid, requiresAction: true);
        }
    }

    public IReadOnlyList<JobOffer> JobOffers()
    {
        if (GetMeta("job_offers") is not { } csv || csv.Length == 0) return Array.Empty<JobOffer>();
        var offers = new List<JobOffer>();
        foreach (var part in csv.Split(','))
        {
            if (!int.TryParse(part, out var tid)) continue;
            var team = Repo.Teams().FirstOrDefault(t => t.Id == tid);
            if (team is null) continue;
            offers.Add(new JobOffer(tid, team.Name,
                Repo.Leagues().FirstOrDefault(l => l.Id == team.LeagueId)?.Name ?? "League",
                (int)Math.Round(SquadStrengthOf(tid))));
        }
        return offers;
    }

    /// <summary>
    /// Take the job: the DB's current club changes and the caller reloads the Session. Per-club
    /// state (XI, captain, takers, tactics metas) is keyed by team id, so nothing needs wiping.
    /// </summary>
    public void AcceptJobOffer(int teamId)
    {
        SetMeta("current_team_id", teamId.ToString());
        SetMeta("sacked", "0");
        SetMeta("job_offers", "");
        SetMeta("board_conf", "58");
        SetMeta("board_threat_streak", "0");
        PostInbox("Board", $"Welcome to {TeamName(teamId)}",
            $"The {TeamName(teamId)} board welcomes you as their new manager. " +
            "The squad, the academy and the training ground are yours.", NextFixture()?.Matchday,
            teamId: teamId);
    }

    /// <summary>Turn down a standing job offer: the club comes off the list and life goes on.</summary>
    public string DeclineJobOffer(int teamId)
    {
        var ids = (GetMeta("job_offers") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries).ToList();
        if (!ids.Remove(teamId.ToString())) return "That offer is no longer on the table.";
        SetMeta("job_offers", string.Join(",", ids));
        var club = Repo.Teams().FirstOrDefault(t => t.Id == teamId)?.Name ?? "the club";
        return $"You turn down {club}. The story continues here.";
    }

    /// <summary>Season rollover: the big rep swing, a fresh board slate, and new suitors.</summary>
    public void RollCareerAtSeasonEnd(int finalPosition, int teamCount, bool promoted)
    {
        var trophies = 0;
        foreach (var lid in new[] { CupLeague, LeagueCupId })
        {
            if (GetMeta($"cup_winner_{lid}_{SeasonId}") is { } w && w == CurrentTeamId.ToString()) trophies++;
        }
        if (finalPosition == 1) trophies++;   // the league title counts as silverware too
        Reputation = ManagerCareer.RepAfterSeason(
            Reputation, finalPosition, teamCount, LeagueId == TopFlight, promoted, trophies);
        // A new season resets tempers — on the number the manager can actually SEE. Lifting
        // only the result-driven half left a badly-swung board still reading 20 in August while
        // the copy promised a clean slate.
        if (BoardConfidenceNow < 45) MoveBoardConfidence(45 - BoardConfidenceNow);
        ThreatStreak = 0;
        if (!IsSacked && new SeededRandom((SeasonId * 4241 + Reputation) ^ WorldSeed).Next(100) < 35)
        {
            GenerateJobOffers(desperation: false);
        }
    }
}
