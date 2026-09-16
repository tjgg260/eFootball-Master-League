using System.Text.Json;
using System.Text.Json.Nodes;
using ML.Ingest;

namespace ML.Core.Tests;

/// <summary>
/// The stats-host export path, against two real exports in samples/ml-stats (efootball-re,
/// 2026-09-13; raw roster bytes stripped). The away side of both was compiled from this project's
/// world, so its PIDs are real players.game_pid values; the home side is an editor-modded squad.
/// </summary>
public class MatchExportTests
{
    private const string Match3Nil = "match_20260913_215134";
    private const string Match0v1 = "match_20260913_192859";

    internal static string SampleDir()
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "samples", "ml-stats");
            if (Directory.Exists(candidate)) return candidate;
        }
        throw new DirectoryNotFoundException("samples/ml-stats not found above the test binary");
    }

    private static MatchExport Load(string stem) => MatchExport.Load(Path.Combine(SampleDir(), stem + ".json"));

    [Fact]
    public void ParsesTheRealExport()
    {
        var e = Load(Match3Nil);
        Assert.True(e.Final);
        Assert.Equal("left_match", e.FinalReason);
        Assert.Equal(Match3Nil, e.Stem);
        Assert.Equal(new[] { "home", "away" }, e.Teams.Select(t => t.Side));
        Assert.Equal(3, e.Teams[0].Total("goals"));
        Assert.Equal(0, e.Teams[1].Total("goals"));
        Assert.Equal(11, e.Teams[0].Players.Count);
        Assert.Equal(14, e.Teams[1].Players.Count);
        var keeper = e.Teams[0].Players[0];
        Assert.Equal(106778524224656UL, keeper.PlayerId);
        Assert.Equal(0, keeper.LineupIndex);
        Assert.Equal(61, keeper.AttributesBase!.Length);
        Assert.Equal(9, keeper.RawSegments!.First().Value.Length);
    }

    /// <summary>The Match Report shows what the bound fields leave out (segments, raw counters,
    /// labels, caveats), so the export is kept exactly as the host wrote it.</summary>
    [Fact]
    public void KeepsTheExportVerbatim()
    {
        var e = Load(Match3Nil);
        Assert.Equal(File.ReadAllText(Path.Combine(SampleDir(), Match3Nil + ".json")), e.RawJson);
        Assert.Contains("\"raw_totals\"", e.RawJson);
    }

    [Fact]
    public void RejectsAnotherSchema()
    {
        Assert.Throws<FormatException>(() => MatchExport.Parse("""{"schema":"something/else","teams":[{},{}]}"""));
    }

    [Theory]
    [InlineData("match_20260913_215134.json", true)]
    [InlineData("live.json", false)]
    [InlineData("match_20260913_215134.json.tmp", false)]
    [InlineData("match_20260913_215134.rated.json", false)]
    [InlineData("match_20260913_215134.report.html", false)]
    public void OnlyFinishedMatchFilesCount(string name, bool expected) =>
        Assert.Equal(expected, MatchExportFolder.IsMatchFile(Path.Combine("ml_stats", name)));

    [Theory]
    [InlineData(Match3Nil)]
    [InlineData(Match0v1)]
    public void RatingsMatchRatingPyForEveryPlayer(string stem)
    {
        var export = Load(stem);
        using var expected = JsonDocument.Parse(File.ReadAllText(Path.Combine(SampleDir(), stem + ".expected-ratings.json")));
        Assert.Equal(MatchRating.Model, expected.RootElement.GetProperty("model").GetString());

        var rated = MatchRating.RateMatch(export);
        var teams = expected.RootElement.GetProperty("teams").EnumerateArray().ToList();
        Assert.Equal(2, teams.Count);
        var checkedPlayers = 0;
        for (var t = 0; t < 2; t++)
        {
            var want = teams[t].GetProperty("players").EnumerateArray().ToList();
            Assert.Equal(want.Count, rated[t].Count);
            for (var i = 0; i < want.Count; i++)
            {
                var w = want[i];
                var got = rated[t][i];
                var who = $"{stem} team {t} slot {got.Slot}";
                Assert.True(w.GetProperty("slot").GetInt32() == got.Slot, who);
                Assert.True(w.GetProperty("role").GetString() == got.Role, $"{who} role {got.Role}");
                Assert.True(w.GetProperty("role_source").GetString() == got.RoleSource, $"{who} source {got.RoleSource}");
                Assert.True(w.GetProperty("match_rating").GetDouble() == got.Rating, $"{who} rating {got.Rating}");
                Assert.True(w.GetProperty("match_rating_unclamped").GetDouble() == got.Unclamped, $"{who} raw {got.Unclamped}");
                var share = w.GetProperty("minutes_share");
                Assert.True((share.ValueKind == JsonValueKind.Null ? null : share.GetDouble()) == got.MinutesShare,
                    $"{who} share {got.MinutesShare}");
                checkedPlayers++;
            }
        }
        Assert.Equal(25, checkedPlayers);
    }

    // --- rating.py's own unit cases (efootball-re/mlstats/test_rating.py), ported ---------------

    private static readonly Dictionary<string, int> Defender = new()
    {
        ["def_awareness"] = 85, ["def_engagement"] = 82, ["tackling"] = 84, ["aggression"] = 80,
        ["att_awareness"] = 55, ["finishing"] = 45, ["gk_awareness"] = 40,
    };
    private static readonly Dictionary<string, int> Forward = new()
    {
        ["att_awareness"] = 88, ["finishing"] = 86, ["def_awareness"] = 45, ["def_engagement"] = 45,
        ["tackling"] = 45, ["aggression"] = 50, ["gk_awareness"] = 40,
    };
    private static readonly Dictionary<string, int> Keeper = new()
    {
        ["gk_awareness"] = 82, ["gk_catching"] = 80, ["gk_parrying"] = 81, ["gk_reflexes"] = 83, ["gk_reach"] = 80,
        ["def_awareness"] = 40, ["att_awareness"] = 40, ["finishing"] = 40,
    };

    private static ExportPlayer Player(Dictionary<string, int>? attrs, int age = 24, int? lineupIndex = null,
                                       params (string Key, int Value)[] actions)
    {
        int[]? attributes = null;
        if (attrs is not null)
        {
            attributes = Enumerable.Repeat(50, 61).ToArray();
            foreach (var (name, v) in attrs) attributes[MatchRating.AttrIndex(name)] = v;
            attributes[MatchRating.AttrIndex("age")] = age;
        }
        return new ExportPlayer
        {
            Slot = 5, LineupIndex = lineupIndex, AttributesBase = attributes, AttributesForm = attributes,
            RawSegments = new Dictionary<string, long[]>(),
            Actions = actions.ToDictionary(a => a.Key, a => a.Value),
        };
    }

    private static double Score(ExportPlayer p, long teamGoals = 0, long oppGoals = 0) =>
        MatchRating.RatePlayer(p, teamGoals, oppGoals, new RatingConfig()).Unclamped;

    [Fact]
    public void TacklesHelpFoulsHurt()
    {
        var baseline = Player(Defender, actions: new[] { ("passes", 30), ("passes_completed", 26), ("tackles", 2) });
        var more = Player(Defender, actions: new[] { ("passes", 30), ("passes_completed", 26), ("tackles", 5) });
        var fouls = Player(Defender, actions: new[] { ("passes", 30), ("passes_completed", 26), ("tackles", 2), ("fouls", 3) });
        Assert.True(Score(more) > Score(baseline));
        Assert.True(Score(fouls) < Score(baseline));
    }

    [Fact]
    public void AccuracyMattersAtTheSameVolume() =>
        Assert.True(Score(Player(Defender, actions: new[] { ("passes", 40), ("passes_completed", 38) }))
                    > Score(Player(Defender, actions: new[] { ("passes", 40), ("passes_completed", 26) })));

    [Fact]
    public void PassVolumeHasDiminishingReturns()
    {
        var s0 = Score(Player(Forward, actions: new[] { ("passes", 0), ("passes_completed", 0) }));
        var s50 = Score(Player(Forward, actions: new[] { ("passes", 60), ("passes_completed", 50) }));
        var s100 = Score(Player(Forward, actions: new[] { ("passes", 120), ("passes_completed", 100) }));
        Assert.True(s100 - s50 < s50 - s0);
    }

    [Fact]
    public void AGoalIsWorthMoreThanASavedShot()
    {
        var saved = Player(Forward, actions: new[] { ("shots", 1), ("shots_on_target", 1) });
        var scored = Player(Forward, actions: new[] { ("shots", 1), ("shots_on_target", 1), ("goals", 1) });
        Assert.True(Score(scored) - Score(saved) > 0.5);
    }

    [Fact]
    public void KeeperSavesAndConceded()
    {
        var cfg = new RatingConfig();
        var calm = MatchRating.RatePlayer(Player(Keeper, actions: new[] { ("saves", 0) }), 1, 0, cfg);
        var busy = MatchRating.RatePlayer(Player(Keeper, actions: new[] { ("saves", 5) }), 1, 0, cfg);
        var leaky = MatchRating.RatePlayer(Player(Keeper, actions: new[] { ("saves", 5) }), 1, 3, cfg);
        Assert.Equal("GK", busy.Role);
        Assert.True(busy.Unclamped > calm.Unclamped);
        Assert.True(leaky.Unclamped < busy.Unclamped);
        Assert.Contains("uses inferred label: saves", busy.Caveats);
    }

    [Fact]
    public void Clamped() =>
        Assert.Equal(10.0, MatchRating.RatePlayer(
            Player(Forward, actions: new[] { ("goals", 9), ("shots", 9), ("shots_on_target", 9) }),
            9, 0, new RatingConfig()).Rating);

    [Fact]
    public void RolesFromAttributes()
    {
        Assert.Equal("DEF", MatchRating.InferRole(Player(Defender)).Role);
        Assert.Equal("FWD", MatchRating.InferRole(Player(Forward)).Role);
        Assert.Equal("GK", MatchRating.InferRole(Player(Keeper)).Role);
    }

    [Fact]
    public void AModdedAll99SquadFindsItsKeeperByLineup()
    {
        var maxed = new[] { "att_awareness", "def_awareness", "gk_awareness", "def_engagement", "dribbling",
            "ball_control", "tight_possession", "finishing", "low_pass", "lofted_pass", "header", "tackling",
            "aggression", "set_piece", "curl", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach",
            "weak_foot", "speed", "physical", "balance", "kicking_power", "acceleration", "jump", "stamina" }
            .ToDictionary(n => n, _ => 99);
        var keeper = Player(maxed, lineupIndex: 0, actions: new[] { ("passes", 6), ("passes_completed", 4) });
        Assert.Equal(("GK", "lineup"), MatchRating.InferRole(keeper));
        var outfield = Player(maxed, lineupIndex: 5,
            actions: new[] { ("passes", 6), ("passes_completed", 4), ("tackles", 3), ("interceptions", 2) });
        Assert.NotEqual("attributes", MatchRating.InferRole(outfield).Source);
    }

    [Fact]
    public void MinutesShareFromSegments()
    {
        var starter = new ExportPlayer { RawSegments = new() { ["0x18"] = new long[] { 1, 1, 1, 1, 1, 1, 1, 1, 0 } } };
        var sub = new ExportPlayer { RawSegments = new() { ["0x18"] = new long[] { 0, 0, 0, 0, 0, 2, 1, 1, 0 } } };
        Assert.Equal(1.0, MatchRating.MinutesShare(starter, 8));
        Assert.Equal(3 / 8.0, MatchRating.MinutesShare(sub, 8));
    }

    [Theory]
    [InlineData(6.35, 1, 6.3)]     // stored as 6.34999…: Python says 6.3, Math.Round(x, 1) says 6.4
    [InlineData(6.25, 1, 6.2)]     // an exact tie goes to even
    [InlineData(7.45, 1, 7.5)]     // stored as 7.4500000000000002
    [InlineData(5.0, 3, 5.0)]
    public void RoundsLikePython(double x, int digits, double expected) =>
        Assert.Equal(expected, MatchRating.PyRound(x, digits));

    // --- linking an export to the fixture that is waiting -------------------------------------

    private static List<SquadPlayer> SquadsFor(MatchExport e, int homeTeamId, int awayTeamId, bool swapSides = false)
    {
        // The world's squads, as the fixture would have them: PIDs from the export's away side
        // belong to one club; the modded home side is made the other club here.
        var squads = new List<SquadPlayer>();
        for (var t = 0; t < 2; t++)
        {
            var teamId = (t == 0) ^ swapSides ? homeTeamId : awayTeamId;
            foreach (var p in e.Teams[t].Players.Where(p => p.PlayerId is not null))
                squads.Add(new SquadPlayer(squads.Count + 1, unchecked((long)p.PlayerId!.Value), p.ShirtName ?? "?", teamId));
        }
        return squads;
    }

    [Fact]
    public void LinksTheFixtureAndCarriesTheScore()
    {
        var e = Load(Match3Nil);
        var linked = ExportLinker.Link(e, 10, 20, SquadsFor(e, 10, 20), out var reason);
        Assert.NotNull(linked);
        Assert.Equal("", reason);
        Assert.Equal((3L, 0L), (linked!.Home.Goals, linked.Away.Goals));
        Assert.Equal(25, linked.Resolved);
        Assert.All(linked.AllPlayers, p => Assert.NotNull(p.Player));
    }

    [Fact]
    public void TheGamesHomeSideNeedNotBeTheFixturesHomeSide()
    {
        var e = Load(Match3Nil);
        // The league's home club played as the game's AWAY team.
        var linked = ExportLinker.Link(e, 10, 20, SquadsFor(e, 10, 20, swapSides: true), out _);
        Assert.NotNull(linked);
        Assert.Equal("away", linked!.Home.Team.Side);
        Assert.Equal((0L, 3L), (linked.Home.Goals, linked.Away.Goals));
    }

    [Fact]
    public void RefusesAMatchThatIsNotTheFixture()
    {
        var e = Load(Match3Nil);
        var otherClubs = SquadsFor(Load(Match0v1), 10, 20)
            .Where(s => e.Teams.SelectMany(t => t.Players).All(p => unchecked((long)(p.PlayerId ?? 0)) != s.GamePid))
            .ToList();
        Assert.Null(ExportLinker.Link(e, 10, 20, otherClubs, out var reason));
        Assert.Contains("not this fixture", reason);
    }

    [Fact]
    public void RefusesAnExportWithoutPlayerIds()
    {
        var e = MatchExport.Parse("""
            {"schema":"efootball-re/match-stats/1","final":true,"teams":[
              {"side":"home","totals":{"goals":1},"players":[{"slot":0,"actions":{}}]},
              {"side":"away","totals":{"goals":0},"players":[{"slot":0,"actions":{}}]}]}
            """);
        Assert.Null(ExportLinker.Link(e, 1, 2, Array.Empty<SquadPlayer>(), out var reason));
        Assert.Contains("no player ids", reason);
    }

    [Fact]
    public void TeamStatsUseTheScreensNamesAndPossessionTimeShare()
    {
        var e = Load(Match3Nil);
        var linked = ExportLinker.Link(e, 10, 20, SquadsFor(e, 10, 20), out _)!;
        var home = ExportLinker.TeamStats(linked.Home, linked.Away);
        var away = ExportLinker.TeamStats(linked.Away, linked.Home);
        Assert.Equal(e.Teams[0].Total("passes_completed"), home["successful_passes"]);
        Assert.Equal(e.Teams[1].Total("fouls"), home["free_kicks"]);
        // 10220 : 5483 possession time
        Assert.Equal(65, home["possession"]);
        Assert.Equal(35, away["possession"]);
        Assert.Equal(e.Teams[0].RawTotals["0x4B"], home["possession_time"]);
    }

    // --- counters identified after the vendored host was built, read by engine id --------------

    [Fact]
    public void ReadsACounterByEngineIdFromTheFirstEightSegments()
    {
        var e = MatchExport.Parse("""
            {"schema":"efootball-re/match-stats/1","final":true,"teams":[
              {"side":"home","raw_totals":{"0x3E":2},"players":[
                {"slot":0,"actions":{},"raw_segments":{"0x3E":[0,1,0,0,1,0,0,0,9]}}]},
              {"side":"away","raw_totals":{},"players":[{"slot":0,"actions":{}}]}]}
            """);
        var booked = e.Teams[0].Players[0];
        Assert.Equal(2L, booked.Raw(ExportCounters.YellowCards));   // the 9th segment is not the match
        Assert.Equal(2L, booked.Raw("0x3e"));                        // any case of the id
        Assert.Equal(0L, booked.Raw(ExportCounters.RedCards));       // a counter that did not move
        Assert.Equal(0L, e.Teams[1].Players[0].Raw(ExportCounters.YellowCards));  // no raw_segments at all
        Assert.Equal(2L, e.Teams[0].Raw(ExportCounters.YellowCards));
        Assert.Equal(0L, e.Teams[1].Raw(ExportCounters.YellowCards));
    }

    [Fact]
    public void AnIdentifiedCounterReadsWhatTheHostRecordedInARealExport()
    {
        // The 3-0 was recorded before 0x13 had a name: it is in raw_segments all the same, and it
        // moved for the three scorers only, never for the four who hit the target without scoring.
        var e = Load(Match3Nil);
        var arsenal = e.Teams[0];
        Assert.Equal(3L, arsenal.Raw(ExportCounters.FinesseShotGoals));
        foreach (var p in arsenal.Players)
            Assert.Equal((long)p.Action("goals"), p.Raw(ExportCounters.FinesseShotGoals));
        Assert.Equal(0L, e.Teams[1].Raw(ExportCounters.FinesseShotGoals));
    }

    [Fact]
    public void BookingsComeFromTheCardCountersByEngineId()
    {
        // A real export, with cards added the way the host writes them: per player in raw_segments,
        // per team in raw_totals. Neither sample match had a booking.
        var node = JsonNode.Parse(File.ReadAllText(Path.Combine(SampleDir(), Match3Nil + ".json")))!;
        JsonObject Segments(int team, int player)
        {
            var p = node["teams"]![team]!["players"]![player]!.AsObject();
            if (p["raw_segments"] is not JsonObject segs) { segs = new JsonObject(); p["raw_segments"] = segs; }
            return segs;
        }
        Segments(0, 0)["0x3E"] = new JsonArray(0, 1, 0, 0, 0, 0, 0, 0, 5);   // one yellow (the 9th is not the match)
        Segments(1, 2)["0x3E"] = new JsonArray(0, 1, 0, 0, 1, 0, 0, 0, 0);   // two yellows...
        Segments(1, 2)["0x3F"] = new JsonArray(0, 0, 0, 0, 1, 0, 0, 0, 0);   // ...and sent off
        node["teams"]![0]!["raw_totals"]!["0x3E"] = 1;
        node["teams"]![1]!["raw_totals"]!["0x3E"] = 2;
        node["teams"]![1]!["raw_totals"]!["0x3F"] = 1;
        var e = MatchExport.Parse(node.ToJsonString());

        var linked = ExportLinker.Link(e, 10, 20, SquadsFor(e, 10, 20), out var reason);
        Assert.True(linked is not null, reason);

        var bookings = ExportLinker.Bookings(linked!);
        Assert.Equal(2, bookings.Count);
        var yellow = bookings.Single(b => ReferenceEquals(b.Player.Export, e.Teams[0].Players[0]));
        Assert.Equal((1, 0), (yellow.Yellows, yellow.Reds));
        var sentOff = bookings.Single(b => ReferenceEquals(b.Player.Export, e.Teams[1].Players[2]));
        Assert.Equal((2, 1), (sentOff.Yellows, sentOff.Reds));
        Assert.All(bookings, b => Assert.NotNull(b.Player.Player));

        var home = ExportLinker.TeamStats(linked!.Home, linked.Away);
        var away = ExportLinker.TeamStats(linked.Away, linked.Home);
        Assert.Equal((1, 0), (home["yellow_cards"], home["red_cards"]));
        Assert.Equal((2, 1), (away["yellow_cards"], away["red_cards"]));
    }

    [Fact]
    public void AMatchWithoutCardsHasNoBookings()
    {
        var e = Load(Match3Nil);
        var linked = ExportLinker.Link(e, 10, 20, SquadsFor(e, 10, 20), out _)!;
        Assert.Empty(ExportLinker.Bookings(linked));
        Assert.Equal(0, ExportLinker.TeamStats(linked.Home, linked.Away)["yellow_cards"]);
    }
}
