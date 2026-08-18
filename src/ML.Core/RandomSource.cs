namespace ML.Core;

/// <summary>
/// Every source of chance in the engine goes through this. Tests inject a fixed seed so a
/// season replays identically, and nothing in ML.Core ever touches a static <see cref="Random"/>.
/// </summary>
public interface IRandomSource
{
    /// <summary>Uniform in [0, 1).</summary>
    double NextDouble();

    /// <summary>Uniform integer in [0, <paramref name="maxExclusive"/>).</summary>
    int Next(int maxExclusive);
}

public sealed class SeededRandom : IRandomSource
{
    private readonly Random _random;

    public SeededRandom(int seed)
    {
        Seed = seed;
        _random = new Random(seed);
    }

    public int Seed { get; }

    public double NextDouble() => _random.NextDouble();

    public int Next(int maxExclusive) => _random.Next(maxExclusive);
}

public static class RandomSourceExtensions
{
    /// <summary>In-place Fisher-Yates.</summary>
    public static void Shuffle<T>(this IRandomSource random, IList<T> items)
    {
        for (var i = items.Count - 1; i > 0; i--)
        {
            var j = random.Next(i + 1);
            (items[i], items[j]) = (items[j], items[i]);
        }
    }
}
