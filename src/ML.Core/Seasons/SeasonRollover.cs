using ML.Core.Domain;
using ML.Core.Tables;
using ML.Core.Validation;

namespace ML.Core.Seasons;

public sealed record LeagueOutcome(
    LeagueId LeagueId,
    TeamId Champion,
    IReadOnlyList<LeagueTableRow> FinalTable,
    IReadOnlyList<TeamId> Promoted,
    IReadOnlyList<TeamId> Relegated);

public sealed record RolloverReport(
    int CompletedSeasonId,
    IReadOnlyList<LeagueOutcome> Leagues,
    IReadOnlyList<PlayerId> Released,
    IReadOnlyList<PlayerId> Signed,
    IReadOnlyDictionary<TeamId, long> WageShortfalls);

/// <summary>
/// Turns a finished season into the next one's starting position: crown the champions, move
/// clubs up and down, pay out, age everyone, and settle expiring contracts.
///
/// Player development here is age-driven only. Phase 5 replaces it with progression driven by
/// minutes played and performance, along with real contract negotiation, youth intake and CPU
/// transfer activity — all of which need data this phase does not yet collect.
/// </summary>
public sealed class SeasonRollover
{
    private readonly World _world;
    private readonly IRandomSource _random;
    private readonly RolloverSettings _settings;
    private readonly SquadRules _rules;

    public SeasonRollover(
        World world,
        IRandomSource random,
        RolloverSettings? settings = null,
        SquadRules? rules = null)
    {
        _world = world ?? throw new ArgumentNullException(nameof(world));
        _random = random ?? throw new ArgumentNullException(nameof(random));
        _settings = settings ?? RolloverSettings.Default;
        _rules = rules ?? SquadRules.Default;
    }

    public RolloverReport Apply(int completedSeasonId, IReadOnlyList<Season> completedSeasons)
    {
        ArgumentNullException.ThrowIfNull(completedSeasons);

        var unfinished = completedSeasons.FirstOrDefault(s => s.State != SeasonState.Complete);
        if (unfinished is not null)
        {
            throw new InvalidOperationException(
                $"Season {unfinished.Id} (league {unfinished.LeagueId}) is {unfinished.State}; " +
                "every division must finish before the rollover.");
        }

        LeaguePyramid.Validate(_world);

        var tables = completedSeasons.ToDictionary(
            s => s.LeagueId,
            s => LeagueTable.Build(s.Teams, s.Fixtures));

        var shortfalls = PayOut(tables);
        var movements = ApplyPromotionAndRelegation(tables);
        AgeSquads();
        var (released, signed) = SettleContracts(completedSeasonId);

        var outcomes = tables
            .Select(kvp =>
            {
                var moved = movements[kvp.Key];
                return new LeagueOutcome(
                    kvp.Key, kvp.Value[0].TeamId, kvp.Value, moved.Promoted, moved.Relegated);
            })
            .OrderBy(o => _world.GetLeague(o.LeagueId).Tier)
            .ToList();

        return new RolloverReport(completedSeasonId, outcomes, released, signed, shortfalls);
    }

    // --- Finances -------------------------------------------------------------------

    private Dictionary<TeamId, long> PayOut(
        IReadOnlyDictionary<LeagueId, IReadOnlyList<LeagueTableRow>> tables)
    {
        var shortfalls = new Dictionary<TeamId, long>();

        foreach (var (leagueId, table) in tables)
        {
            var tier = _world.GetLeague(leagueId).Tier;
            var winnersPrize = _settings.TopFlightWinnersPrize >> (tier - 1);

            foreach (var row in table)
            {
                var team = _world.GetTeam(row.TeamId);
                var prize = Math.Max(
                    _settings.MinimumPrize,
                    winnersPrize - ((row.Position - 1) * _settings.PrizeStepPerPlace));

                team.Credit(prize);

                // DebitUpTo floors at zero, so the "no negative budgets" invariant holds even
                // for a club whose wage bill has run away from it. The shortfall is reported
                // rather than swallowed — Phase 5 can turn it into a forced sale.
                var shortfall = team.DebitUpTo(_world.WageBillOf(team.Id));
                if (shortfall > 0)
                {
                    shortfalls[team.Id] = shortfall;
                }
            }
        }

        return shortfalls;
    }

    // --- Promotion and relegation ---------------------------------------------------

    private Dictionary<LeagueId, (List<TeamId> Promoted, List<TeamId> Relegated)>
        ApplyPromotionAndRelegation(
            IReadOnlyDictionary<LeagueId, IReadOnlyList<LeagueTableRow>> tables)
    {
        var movements = tables.Keys.ToDictionary(
            id => id,
            _ => (Promoted: new List<TeamId>(), Relegated: new List<TeamId>()));

        foreach (var (upper, lower) in LeaguePyramid.AdjacentTiers(_world))
        {
            if (!tables.TryGetValue(upper.Id, out var upperTable) ||
                !tables.TryGetValue(lower.Id, out var lowerTable))
            {
                // A division that did not play this season simply does not exchange clubs.
                continue;
            }

            var goingDown = upperTable
                .TakeLast(upper.RelegationPlaces)
                .Select(r => r.TeamId)
                .ToList();

            var goingUp = lowerTable
                .Take(lower.PromotionPlaces)
                .Select(r => r.TeamId)
                .ToList();

            foreach (var teamId in goingDown)
            {
                _world.GetTeam(teamId).MoveToLeague(lower.Id);
            }

            foreach (var teamId in goingUp)
            {
                _world.GetTeam(teamId).MoveToLeague(upper.Id);
            }

            movements[upper.Id].Relegated.AddRange(goingDown);
            movements[lower.Id].Promoted.AddRange(goingUp);
        }

        return movements;
    }

    // --- Ageing ---------------------------------------------------------------------

    private void AgeSquads()
    {
        foreach (var player in _world.Players)
        {
            player.AdvanceAge();
            player.AdjustRating(RatingDelta(player));
        }
    }

    private int RatingDelta(Player player)
    {
        if (player.Age < _settings.PeakAgeStart)
        {
            // -1 to MaxYouthGain: most young players improve, a few stall.
            return _random.Next(_settings.MaxYouthGain + 2) - 1;
        }

        if (player.Age <= _settings.PeakAgeEnd)
        {
            return _random.Next(3) - 1;
        }

        var yearsPastPeak = player.Age - _settings.PeakAgeEnd;
        var worstCase = Math.Min(_settings.MaxVeteranLoss, 1 + yearsPastPeak);
        return -(1 + _random.Next(worstCase));
    }

    // --- Contracts ------------------------------------------------------------------

    private (List<PlayerId> Released, List<PlayerId> Signed) SettleContracts(int completedSeasonId)
    {
        var released = new List<PlayerId>();

        foreach (var team in _world.Teams.OrderBy(t => t.Id.Value).ToList())
        {
            released.AddRange(SettleContractsAt(team, completedSeasonId));
        }

        var signed = FillShortSquads(completedSeasonId);
        return (released, signed);
    }

    private List<PlayerId> SettleContractsAt(Team team, int completedSeasonId)
    {
        var released = new List<PlayerId>();

        var expiring = _world.SquadOf(team.Id)
            .Where(p => p.ContractHasExpired(completedSeasonId))
            .OrderBy(p => p.OverallRating)
            .ThenBy(p => p.Id.Value)
            .ToList();

        var squadSize = _world.SquadOf(team.Id).Count;

        foreach (var player in expiring)
        {
            var canAfford = team.CanAfford(player.AnnualWage);
            var wouldGoBelowMinimum = squadSize - 1 < _rules.MinSquadSize;

            // Letting a club drop below a legal squad is worse than an unaffordable renewal;
            // it would leave the world invalid with no market to fix it from.
            if (!_settings.AutoRenewAffordableContracts && !wouldGoBelowMinimum)
            {
                _world.ReleasePlayer(player.Id);
                released.Add(player.Id);
                squadSize--;
                continue;
            }

            if (canAfford || wouldGoBelowMinimum)
            {
                player.SignContract(completedSeasonId + _settings.ContractLengthYears, player.WeeklyWage);
                continue;
            }

            _world.ReleasePlayer(player.Id);
            released.Add(player.Id);
            squadSize--;
        }

        return released;
    }

    /// <summary>
    /// Minimal free-agent market: clubs short of a legal squad take the best available. Real
    /// bidding, fees and CPU transfer strategy are Phase 5.
    /// </summary>
    private List<PlayerId> FillShortSquads(int completedSeasonId)
    {
        var signed = new List<PlayerId>();

        foreach (var team in _world.Teams.OrderBy(t => t.Id.Value))
        {
            while (_world.SquadOf(team.Id).Count < _rules.MinSquadSize)
            {
                var target = PickSigning(team);
                if (target is null)
                {
                    break;
                }

                var shirt = _world.NextFreeSquadNumber(team.Id);
                if (shirt is null)
                {
                    break;
                }

                _world.AssignPlayer(target.Id, team.Id, shirt.Value);
                target.SignContract(completedSeasonId + _settings.ContractLengthYears, target.WeeklyWage);
                signed.Add(target.Id);
            }
        }

        return signed;
    }

    private Player? PickSigning(Team team)
    {
        var freeAgents = _world.FreeAgents;
        if (freeAgents.Count == 0)
        {
            return null;
        }

        var keepers = _world.SquadOf(team.Id).Count(p => p.Position.IsGoalkeeper());
        if (keepers < _rules.MinGoalkeepers)
        {
            var keeper = freeAgents
                .Where(p => p.Position.IsGoalkeeper())
                .OrderByDescending(p => p.OverallRating)
                .ThenBy(p => p.Id.Value)
                .FirstOrDefault();

            if (keeper is not null)
            {
                return keeper;
            }
        }

        return freeAgents
            .OrderByDescending(p => p.OverallRating)
            .ThenBy(p => p.Id.Value)
            .First();
    }
}
