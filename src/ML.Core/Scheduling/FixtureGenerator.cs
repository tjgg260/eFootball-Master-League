using ML.Core.Domain;

namespace ML.Core.Scheduling;

/// <summary>
/// Round-robin scheduling by the circle method (Berger tables).
///
/// One club is pinned and the rest rotate around it. With an odd number of clubs a bye is
/// added, which gives each club exactly one blank matchday. The pinned club would otherwise
/// take the same venue every round, so its pairing flips on odd rounds — that keeps every
/// club's home count within one of the rest across a single leg, and exactly level across two.
/// </summary>
public static class FixtureGenerator
{
    private static readonly TeamId Bye = new(int.MinValue);

    /// <summary>Each club plays every other once. Matchdays run 1..(n-1), or 1..n if n is odd.</summary>
    public static IReadOnlyList<Fixture> GenerateSingleRoundRobin(
        IReadOnlyList<TeamId> teams,
        IRandomSource random)
        => Generate(teams, random, secondLeg: false);

    /// <summary>
    /// Each club plays every other home and away. The second leg mirrors the first with venues
    /// swapped, which is what makes the season-long home/away split exactly even.
    /// </summary>
    public static IReadOnlyList<Fixture> GenerateDoubleRoundRobin(
        IReadOnlyList<TeamId> teams,
        IRandomSource random)
        => Generate(teams, random, secondLeg: true);

    private static IReadOnlyList<Fixture> Generate(
        IReadOnlyList<TeamId> teams,
        IRandomSource random,
        bool secondLeg)
    {
        ArgumentNullException.ThrowIfNull(teams);
        ArgumentNullException.ThrowIfNull(random);

        if (teams.Count < 2)
        {
            throw new ArgumentException("A league needs at least two clubs.", nameof(teams));
        }

        if (teams.Distinct().Count() != teams.Count)
        {
            throw new ArgumentException("The same club appears twice in the league.", nameof(teams));
        }

        var slots = teams.ToList();
        random.Shuffle(slots);

        if (slots.Count % 2 != 0)
        {
            slots.Add(Bye);
        }

        var size = slots.Count;
        var roundsPerLeg = size - 1;
        var pairingsPerRound = size / 2;

        var fixtures = new List<Fixture>();
        var nextId = 1;

        for (var round = 0; round < roundsPerLeg; round++)
        {
            for (var pairing = 0; pairing < pairingsPerRound; pairing++)
            {
                var first = slots[pairing];
                var second = slots[size - 1 - pairing];

                if (first == Bye || second == Bye)
                {
                    continue;
                }

                // The pinned club sits in slot 0 every round; alternate its venue.
                var (home, away) = pairing == 0 && round % 2 == 1
                    ? (second, first)
                    : (first, second);

                fixtures.Add(new Fixture(nextId++, round + 1, home, away));

                if (secondLeg)
                {
                    fixtures.Add(new Fixture(nextId++, round + 1 + roundsPerLeg, away, home));
                }
            }

            Rotate(slots);
        }

        return fixtures.OrderBy(f => f.Matchday).ThenBy(f => f.Id).ToList();
    }

    /// <summary>Pins slot 0 and rotates the remainder one place clockwise.</summary>
    private static void Rotate(List<TeamId> slots)
    {
        if (slots.Count < 3)
        {
            return;
        }

        var last = slots[^1];
        slots.RemoveAt(slots.Count - 1);
        slots.Insert(1, last);
    }
}
