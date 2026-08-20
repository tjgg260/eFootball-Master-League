using ML.Core.Development;
using ML.Data;

namespace ML.App;

public sealed record SkillTrainingRow(int PlayerId, string Player, string Skill, int Progress, int Target);

/// <summary>
/// The character-and-development layer (P1): FM-style traits (Determination 1-20 + hidden
/// professionalism/ambition/temperament), a derived personality, eFootball Player Skills
/// learned on the training ground, and a growth model where determined professionals develop
/// and slackers stall. Pure rules live in ML.Core.Development; this partial owns persistence.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ traits & personality

    /// <summary>A player's traits — seeded deterministically on first read, then stored.</summary>
    public (int Determination, int Professionalism, int Ambition, int Temperament) TraitsOf(int playerId)
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT determination, professionalism, ambition, temperament " +
                            "FROM player_traits WHERE player_id=$p";
            q.Parameters.AddWithValue("$p", playerId);
            using var r = q.ExecuteReader();
            if (r.Read()) return (r.GetInt32(0), r.GetInt32(1), r.GetInt32(2), r.GetInt32(3));
        }
        var seeded = PersonalityModel.SeedTraits(playerId);
        using (var ins = Db.Connection.CreateCommand())
        {
            ins.CommandText = "INSERT OR IGNORE INTO player_traits" +
                              "(player_id,determination,professionalism,ambition,temperament) " +
                              "VALUES($p,$d,$pr,$a,$t)";
            ins.Parameters.AddWithValue("$p", playerId);
            ins.Parameters.AddWithValue("$d", seeded.Determination);
            ins.Parameters.AddWithValue("$pr", seeded.Professionalism);
            ins.Parameters.AddWithValue("$a", seeded.Ambition);
            ins.Parameters.AddWithValue("$t", seeded.Temperament);
            ins.ExecuteNonQuery();
        }
        return seeded;
    }

    public string PersonalityOf(int playerId)
    {
        var (d, p, a, t) = TraitsOf(playerId);
        return PersonalityModel.Personality(d, p, a, t);
    }

    // ------------------------------------------------------------------ skills

    public IReadOnlyList<string> SkillsOf(int playerId)
    {
        var rows = new List<string>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT skill FROM player_skills WHERE player_id=$p ORDER BY skill";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add(r.GetString(0));
        return rows;
    }

    /// <summary>
    /// What this player could take onto the training ground: the game's own gates (GK-only,
    /// Track Back for mid/fwd), the innate set excluded, known skills excluded, and old dogs
    /// excluded entirely.
    /// </summary>
    public IReadOnlyList<string> LearnableSkillsFor(int playerId)
    {
        var p = Repo.SquadPlayers(CurrentTeamId).FirstOrDefault(x => x.Id == playerId);
        if (p is null) return Array.Empty<string>();
        var (det, _, _, _) = TraitsOf(playerId);
        if (!PersonalityModel.CanStillLearn(p.Age ?? 24, det)) return Array.Empty<string>();
        return PlayerSkillCatalog
            .LearnableFor(p.Position, Visuals.PositionCategory(p.Position), SkillsOf(playerId).ToList())
            .Select(s => s.Name)
            .ToList();
    }

    /// <summary>Start (or switch) skill training. One skill per player at a time.</summary>
    public string StartSkillTraining(int playerId, string skill)
    {
        var p = Repo.SquadPlayers(CurrentTeamId).FirstOrDefault(x => x.Id == playerId);
        if (p is null) return "Not in your squad.";
        if (!LearnableSkillsFor(playerId).Contains(skill))
        {
            return PlayerSkillCatalog.IsInnate(skill)
                ? $"{skill} can't be coached — players are born with it."
                : $"{p.Name} can't learn {skill}.";
        }
        var (det, prof, _, _) = TraitsOf(playerId);
        var target = PersonalityModel.SkillSessions(det, prof, CoachTrainingBonus());
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO skill_training(player_id,team_id,skill,progress,target) " +
                          "VALUES($p,$t,$s,0,$g) ON CONFLICT(player_id) DO UPDATE SET " +
                          "skill=excluded.skill, progress=0, target=excluded.target";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$s", skill);
        cmd.Parameters.AddWithValue("$g", target);
        cmd.ExecuteNonQuery();
        return $"{p.Name} starts working on {skill} — about {target} matchweeks at his determination.";
    }

    public IReadOnlyList<SkillTrainingRow> ActiveSkillTrainings()
    {
        var rows = new List<SkillTrainingRow>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT t.player_id, p.name, t.skill, t.progress, t.target " +
                          "FROM skill_training t JOIN players p ON p.id=t.player_id " +
                          "WHERE t.team_id=$t ORDER BY p.name";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            rows.Add(new SkillTrainingRow(r.GetInt32(0), r.GetString(1), r.GetString(2),
                r.GetInt32(3), r.GetInt32(4)));
        }
        return rows;
    }

    /// <summary>
    /// One matchweek of skill work (called from the weekly pass): progress ticks, completed
    /// skills land on the player with a letter home.
    /// </summary>
    private List<string> AdvanceSkillTraining()
    {
        var notes = new List<string>();
        foreach (var t in ActiveSkillTrainings())
        {
            var progress = t.Progress + 1;
            if (progress >= t.Target)
            {
                using (var learn = Db.Connection.CreateCommand())
                {
                    learn.CommandText = "INSERT OR IGNORE INTO player_skills(player_id,skill,source) " +
                                        "VALUES($p,$s,'trained')";
                    learn.Parameters.AddWithValue("$p", t.PlayerId);
                    learn.Parameters.AddWithValue("$s", t.Skill);
                    learn.ExecuteNonQuery();
                }
                using (var del = Db.Connection.CreateCommand())
                {
                    del.CommandText = "DELETE FROM skill_training WHERE player_id=$p";
                    del.Parameters.AddWithValue("$p", t.PlayerId);
                    del.ExecuteNonQuery();
                }
                // "mastered", not "learned" — PostMatchInbox mails notes containing "learned"
                // and the letter below already covers it (no double mail).
                notes.Add($"{t.Player} has mastered {t.Skill}!");
                PostInbox("Player", $"{t.Player} learned {t.Skill}",
                    $"The coaches confirm it: {t.Skill} is now part of {t.Player}'s game.",
                    playerId: t.PlayerId);
            }
            else
            {
                using var upd = Db.Connection.CreateCommand();
                upd.CommandText = "UPDATE skill_training SET progress=$g WHERE player_id=$p";
                upd.Parameters.AddWithValue("$g", progress);
                upd.Parameters.AddWithValue("$p", t.PlayerId);
                upd.ExecuteNonQuery();
            }
        }
        return notes;
    }

    /// <summary>Season growth multiplier for a player — determined professionals develop.</summary>
    internal double GrowthMultiplierOf(int playerId)
    {
        var (det, prof, _, _) = TraitsOf(playerId);
        var facility = 1.0;
        try
        {
            // Only YOUR squad trains on your facilities.
            if (Repo.Squad(CurrentTeamId).Any(m => m.PlayerId == playerId))
                facility = TrainingFacilityMultiplier;
        }
        catch { /* facilities are additive */ }
        return PersonalityModel.GrowthMultiplier(det, prof) * facility;
    }

    // ------------------------------------------------------------------ potential (P2)

    /// <summary>
    /// The ceiling a player can develop toward — stored; seeded on first read from age,
    /// current rating and determination (young + driven = higher ceiling). Academy prospects
    /// get theirs written explicitly at intake.
    /// </summary>
    public int PotentialOf(int playerId, int? age = null, int? rating = null)
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT potential FROM player_potential WHERE player_id=$p";
            q.Parameters.AddWithValue("$p", playerId);
            var v = q.ExecuteScalar();
            if (v is not null and not DBNull) return Convert.ToInt32(v);
        }
        if (age is null || rating is null)
        {
            using var pq = Db.Connection.CreateCommand();
            pq.CommandText = "SELECT COALESCE(age,25), COALESCE(overall_rating,65) FROM players WHERE id=$p";
            pq.Parameters.AddWithValue("$p", playerId);
            using var r = pq.ExecuteReader();
            if (r.Read()) { age ??= r.GetInt32(0); rating ??= r.GetInt32(1); }
        }
        var (det, _, _, _) = TraitsOf(playerId);
        // Headroom shrinks with age, grows with determination; a seeded spark makes some kids special.
        var spark = (int)(unchecked((uint)(playerId * 2654435761) ^ (uint)WorldSeed) % 7);   // 0-6
        var headroom = Math.Max(0, 27 - (age ?? 25)) * (2 + det / 7) / 2 + spark;
        var potential = Math.Clamp((rating ?? 65) + headroom, rating ?? 65, 95);
        SetPotential(playerId, potential);
        return potential;
    }

    internal void SetPotential(int playerId, int potential)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO player_potential(player_id,potential) VALUES($p,$v) " +
                          "ON CONFLICT(player_id) DO UPDATE SET potential=excluded.potential";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$v", potential);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Potential as scouting stars for the UI (rounded half-up onto 1-5).</summary>
    public int PotentialStars(int playerId) => PotentialOf(playerId) switch
    {
        >= 86 => 5, >= 79 => 4, >= 71 => 3, >= 62 => 2, _ => 1,
    };
}
