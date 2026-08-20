namespace ML.Core.Scheduling;

/// <summary>
/// Real dates for the season (FM phase C1), derived deterministically from matchday numbers —
/// no schema needed. League rounds are Saturdays, one per week from the first Saturday of
/// August; cup rounds are the Wednesday after their shared week number; preseason friendlies
/// (matchday 0) sit on the last Saturday of July.
/// </summary>
public static class SeasonCalendar
{
    public static DateOnly FirstLeagueSaturday(int seasonYear)
    {
        var d = new DateOnly(seasonYear, 8, 1);
        while (d.DayOfWeek != DayOfWeek.Saturday) d = d.AddDays(1);
        return d;
    }

    /// <summary>The date a fixture is played. kind: "league" | "cup" | "friendly".</summary>
    public static DateOnly DateOf(int seasonYear, int matchday, string kind)
    {
        var first = FirstLeagueSaturday(seasonYear);
        if (matchday <= 0 || kind == "friendly")
        {
            return first.AddDays(-7);                       // preseason: late July Saturday
        }
        var saturday = first.AddDays((matchday - 1) * 7);
        return kind == "cup" ? saturday.AddDays(4) : saturday;   // cup = midweek Wednesday
    }

    /// <summary>"Sat 8 Aug 2026" — the label the calendar and inbox stamp on things.</summary>
    public static string Label(DateOnly d) => d.ToString("ddd d MMM yyyy");

    /// <summary>Short in-row label: "8 Aug".</summary>
    public static string ShortLabel(DateOnly d) => d.ToString("d MMM");
}
