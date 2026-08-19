using ML.Ingest;

namespace ML.Core.Tests;

public class CalibrationTests
{
    [Fact]
    public void DefaultProfileCapturesEveryStatForBothSides()
    {
        var profile = CalibrationProfile.Default1080p();
        var fields = profile.Regions.Select(r => r.Field).ToHashSet();

        Assert.Contains("home_score", fields);
        Assert.Contains("away_score", fields);
        Assert.Contains("scorers", fields);

        foreach (var (key, _) in CalibrationProfile.StatRows)
        {
            Assert.Contains($"home_{key}", fields);
            Assert.Contains($"away_{key}", fields);
        }

        // score(2) + scorers(1) + 2 columns per stat row
        Assert.Equal(3 + CalibrationProfile.StatRows.Count * 2, profile.Regions.Count);
    }

    [Fact]
    public void NormalisedRegionsMapToPixelsWithinTheImage()
    {
        var profile = CalibrationProfile.Default1080p();
        foreach (var region in profile.Regions)
        {
            var (x, y, w, h) = region.ToPixels(1920, 1080);
            Assert.InRange(x, 0, 1920);
            Assert.InRange(y, 0, 1080);
            Assert.True(x + w <= 1920 + 1);
            Assert.True(y + h <= 1080 + 1);
        }
    }
}
