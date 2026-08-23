namespace ML.Core.Selection;

/// <summary>
/// Fatigue, form and injury rules for the matchday condition loop. Pure functions over the
/// player_condition state: Session applies them once per matchday and persists the results.
/// Injuries are hash-seeded from (season, matchday, player) — no shared Random state — so a
/// replayed matchday produces the same knocks.
/// </summary>
public static class ConditionModel
{
    /// <summary>Fatigue a starter picks up from playing a match.</summary>
    public const int StarterFatigue = 15;

    /// <summary>Fatigue shed by every player each matchday before the starters' cost lands.</summary>
    public const int Recovery = 8;

    /// <summary>Fatigue ceiling; at 60 a player's score drops by a full 15 points.</summary>
    public const int MaxFatigue = 60;

    /// <summary>Form's resting point; every result drifts form 10% back toward it.</summary>
    public const double NeutralForm = 6.5;

    /// <summary>A matchday of rest: fatigue - <see cref="Recovery"/>, clamped to 0..<see cref="MaxFatigue"/>.</summary>
    public static int AfterRest(int fatigue) => Math.Clamp(fatigue - Recovery, 0, MaxFatigue);

    /// <summary>A start: fatigue + <see cref="StarterFatigue"/>, clamped to 0..<see cref="MaxFatigue"/>.</summary>
    public static int AfterStart(int fatigue) => Math.Clamp(fatigue + StarterFatigue, 0, MaxFatigue);

    /// <summary>
    /// Form after a result. outcome is 1 win / 0 draw / -1 loss: the result moves form by ±0.5,
    /// then form drifts 10% back toward <see cref="NeutralForm"/>, clamped to 4..9.
    /// </summary>
    public static double FormAfterResult(double form, int outcome) => FormAfterResult(form, outcome, 0.0);

    /// <summary>
    /// Form after a result for a player of a given <paramref name="steadiness"/> (0..1 — eFootball's
    /// Condition/"form" attribute for natives, professionalism otherwise). Steady players swing less:
    /// the ±0.5 base shrinks to as little as ±0.2 for a rock-steady player, so consistent performers
    /// hold their level while flaky ones lurch between hot and cold. Then the usual 10% drift home.
    /// </summary>
    public static double FormAfterResult(double form, int outcome, double steadiness)
    {
        var swing = 0.5 * (1.0 - 0.6 * Math.Clamp(steadiness, 0.0, 1.0));
        var f = form + swing * outcome;
        f += (NeutralForm - f) * 0.1;
        return Math.Clamp(f, 4.0, 9.0);
    }

    public static int? InjuryRoll(int seasonId, int matchday, long playerId) =>
        InjuryRoll(seasonId, matchday, playerId, 1.0);

    /// <summary>
    /// Injury roll scaled by <paramref name="proneness"/> (a multiplier on the ~2% base: eFootball's
    /// Injury Resistance inverted — robust ~0.5, fragile ~1.6). Glass players pick up knocks two to
    /// three times as often as iron men. Still fully deterministic in (season, matchday, player).
    /// </summary>
    public static int? InjuryRoll(int seasonId, int matchday, long playerId, double proneness)
    {
        var h = Mix(seasonId, matchday, playerId);
        var threshold = (uint)Math.Clamp(200.0 * proneness, 0.0, 9999.0);
        if ((uint)(h >> 32) % 10000 >= threshold) return null;
        var duration = 1 + (int)((uint)h % 4);
        return matchday + duration;
    }

    /// <summary>SplitMix64 over the three inputs — full-avalanche, no Random, no shared state.</summary>
    private static ulong Mix(int a, int b, long c)
    {
        unchecked
        {
            // (ulong)c == (uint)c for the old int-range ids, so existing careers keep their rolls.
            var z = 0x9E3779B97F4A7C15UL;
            z = SplitMix(z + (uint)a);
            z = SplitMix(z + (uint)b);
            z = SplitMix(z + (ulong)c);
            return z;
        }
    }

    private static ulong SplitMix(ulong z)
    {
        unchecked
        {
            z += 0x9E3779B97F4A7C15UL;
            z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
            z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
            return z ^ (z >> 31);
        }
    }
}
