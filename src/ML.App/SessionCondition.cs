using System.Linq;
using ML.Core;

namespace ML.App;

/// <summary>
/// Intrinsic condition traits (the fatigue/sharpness/form system's static inputs): how STEADY a
/// player's form is and how INJURY-PRONE he is. eFootball carries both natively — its "Condition"
/// stat (stored as the <c>form</c> attribute, 1..8: higher = steadier) and its Injury Resistance
/// (<c>injury_resistance</c>, 1..3: higher = tougher) — but ONLY for players that exist in the
/// eFootball DB. So natives use those real values; everyone else falls back to character
/// (professionalism for steadiness) or a neutral default. Cached per session.
///
/// These feed the matchday loop: steadiness scales how far form swings after a result
/// (<see cref="ML.Core.Selection.ConditionModel.FormAfterResult(double,int,double)"/>), and
/// proneness scales injury odds (<see cref="ML.Core.Selection.ConditionModel.InjuryRoll(int,int,int,double)"/>).
/// </summary>
public sealed partial class Session
{
    private readonly Dictionary<int, (double Steadiness, double Proneness)> _intrinsics = new();

    private (double Steadiness, double Proneness) IntrinsicsOf(int playerId)
    {
        if (_intrinsics.TryGetValue(playerId, out var cached)) return cached;

        int? nativeForm = null, nativeInj = null;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT attribute, value FROM player_attributes WHERE player_id=$p " +
                            "AND attribute IN ('form','injury_resistance')";
            q.Parameters.AddWithValue("$p", playerId);
            using var r = q.ExecuteReader();
            while (r.Read())
            {
                if (r.GetString(0) == "form") nativeForm = r.GetInt32(1);
                else nativeInj = r.GetInt32(1);
            }
        }

        // Steadiness 0..1. eFootball Condition (1..8) is the truth for natives; otherwise a driven
        // professional is steadier than a flake, so professionalism (1..20) stands in.
        double steadiness;
        if (nativeForm is { } nf)
        {
            steadiness = Math.Clamp((nf - 1) / 7.0, 0.0, 1.0);
        }
        else
        {
            var (_, prof, _, _) = TraitsOf(playerId);
            steadiness = Math.Clamp((prof - 1) / 19.0, 0.0, 1.0);
        }

        // Proneness = a multiplier on injury odds. Injury Resistance 1/2/3 -> fragile/normal/iron.
        // No native value -> neutral (FM/Genie don't expose Injury Proneness, so we don't invent it).
        var proneness = nativeInj switch { 1 => 1.6, 2 => 1.0, 3 => 0.5, _ => 1.0 };

        var v = (steadiness, proneness);
        _intrinsics[playerId] = v;
        return v;
    }

    /// <summary>How consistent a player's form is (0 flaky .. 1 metronome). Native eFootball
    /// Condition where we have it, professionalism otherwise.</summary>
    internal double SteadinessOf(int playerId) => IntrinsicsOf(playerId).Steadiness;

    /// <summary>Injury-odds multiplier (≈0.5 iron .. 1.6 glass), from eFootball Injury Resistance;
    /// neutral 1.0 when unknown.</summary>
    internal double PronenessOf(int playerId) => IntrinsicsOf(playerId).Proneness;

    /// <summary>
    /// A team's strength ON THE DAY: its XI strength plus a random off-day / inspired-day swing.
    /// The rating says who SHOULD win; this says who actually turns up. The swing is small for a
    /// squad of consistent professionals (~±3.5 pts) and large for a flaky one (~±8), so upsets
    /// come disproportionately from inconsistent teams — elite ratings stay elite, but a great side
    /// full of temperamental players is beatable on a bad day. Attack swings a touch more than
    /// defence; both move together because a team plays well or badly as a unit.
    /// </summary>
    internal (double Attack, double Defence) MatchdayStrengthOf(int teamId, IRandomSource rng)
    {
        var (atk, def) = XiStrengthOf(teamId);
        var steadiness = SquadSteadinessOf(teamId);          // 0..1
        var sigma = 3.5 + (1.0 - steadiness) * 4.5;          // ~3.5 steady .. 8.0 flaky rating points
        var swing = NextGaussian(rng) * sigma;
        return (atk + swing, def + swing * 0.6);
    }

    /// <summary>Average steadiness of a team's likely XI (slots 0-10), 0..1.</summary>
    internal double SquadSteadinessOf(int teamId)
    {
        var ids = new List<int>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT player_id FROM squad_members WHERE team_id=$t " +
                              "AND slot BETWEEN 0 AND 10";
            cmd.Parameters.AddWithValue("$t", teamId);
            using var r = cmd.ExecuteReader();
            while (r.Read()) ids.Add(r.GetInt32(0));
        }
        return ids.Count == 0 ? 0.5 : ids.Average(id => SteadinessOf(id));
    }

    /// <summary>Box-Muller normal, tail-clamped so one match can't swing an absurd amount.</summary>
    private static double NextGaussian(IRandomSource rng)
    {
        var u1 = Math.Max(1e-9, rng.NextDouble());
        var u2 = rng.NextDouble();
        var z = Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2);
        return Math.Clamp(z, -2.5, 2.5);
    }
}
