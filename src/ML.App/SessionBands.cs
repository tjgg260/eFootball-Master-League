namespace ML.App;

/// <summary>
/// The id range a career's OWN player rows live in, per world.
///
/// The curated world put a career's copies of players in 20M-700M and minted academy prospects at
/// 30M-40M inside it. A world built from the game cannot: real eFootball PIDs reach into that range
/// (1,584 of them in the Aug 13 dt200), so the Market would hide real players as "career copies"
/// and a new career's clean slate would delete them. tools/game_world.py therefore records the
/// world's own range in meta <c>career_player_band</c>; a database without the key is the curated
/// world and keeps 20M-700M, so nothing changes there.
/// </summary>
public sealed partial class Session
{
    private (long Lo, long Hi)? _careerPlayerBand;

    /// <summary>[Lo, Hi): where this world's careers keep their own player rows.</summary>
    public (long Lo, long Hi) CareerPlayerBand => _careerPlayerBand ??= ReadCareerPlayerBand();

    private (long, long) ReadCareerPlayerBand()
    {
        var v = GetMeta("career_player_band");
        if (v is not null)
        {
            var parts = v.Split(',');
            if (parts.Length == 2 && long.TryParse(parts[0], out var lo) && long.TryParse(parts[1], out var hi)
                && lo > 0 && lo < hi)
                return (lo, hi);
        }
        return (20_000_000, 700_000_000);
    }

    /// <summary>
    /// SQL for "this player row belongs to the reference world": not one of the career's own copies
    /// (the band above), and not the curated 45-46bn overlay. Every pool anyone signs from — the
    /// Market, CPU clubs' shopping — filters by this one expression, so they cannot drift apart.
    /// </summary>
    public string WorldPlayerClause(string alias = "p")
    {
        var (lo, hi) = CareerPlayerBand;
        return $"(NOT ({alias}.id >= {lo} AND {alias}.id < {hi}) " +
               $"AND NOT ({alias}.id >= 45000000000 AND {alias}.id < 46000000000))";
    }

    /// <summary>The academy's ten-million-id band, inside the career band (30M-40M in the curated
    /// world, exactly as before; 10M above the band's floor everywhere).</summary>
    private long AcademyIdBase => CareerPlayerBand.Lo + 10_000_000;
    private long AcademyIdCeiling => CareerPlayerBand.Lo + 20_000_000;
}
