using System.Text.Json;
using System.Text.Json.Serialization;
using ML.Data;

namespace ML.Sync;

// The spec the proven Python authoring pipeline (tools/ml_author.py) consumes: for each club,
// the host team slot it takes over and its real squad. ML.Sync's job is to produce this from the
// master DB deterministically, so the DB is the single source of truth and the game is compiled
// from it — full recompile, no applied_state diff.

public sealed record CompileSpec(
    [property: JsonPropertyName("clubs")] IReadOnlyList<CompileClub> Clubs);

public sealed record CompileClub(
    [property: JsonPropertyName("club")] string Club,
    [property: JsonPropertyName("host_team_id")] int HostTeamId,
    [property: JsonPropertyName("players")] IReadOnlyList<CompilePlayer> Players);

public sealed record CompilePlayer(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("position")] string Position,
    [property: JsonPropertyName("shirt")] int Shirt);

/// <summary>
/// Reads the master DB into the authoring spec. Custom clubs render into their assigned host team
/// slot (game_team_id); their real squads come straight from the DB. This is the deterministic
/// half of the compile — the byte-level authoring is the Python tool, invoked by <see cref="Compiler"/>.
/// </summary>
public static class CompileSpecBuilder
{
    public static CompileSpec Build(Repository repo)
    {
        var players = repo.Players().ToDictionary(p => p.Id);
        var clubs = new List<CompileClub>();

        foreach (var team in repo.Teams().Where(t => t.IsCustom).OrderBy(t => t.GameTeamId))
        {
            var squad = repo.Squad(team.Id)
                .Where(s => players.ContainsKey(s.PlayerId))
                .OrderBy(s => s.Slot)
                .Select(s =>
                {
                    var p = players[s.PlayerId];
                    return new CompilePlayer(p.Name, p.Position, s.SquadNumber);
                })
                .ToList();

            if (squad.Count > 0)
            {
                clubs.Add(new CompileClub(team.Name, team.GameTeamId, squad));
            }
        }

        return new CompileSpec(clubs);
    }

    public static string ToJson(CompileSpec spec) =>
        JsonSerializer.Serialize(spec, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
}
