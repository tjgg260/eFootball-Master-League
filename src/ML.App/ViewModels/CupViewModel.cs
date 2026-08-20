using System.Collections.ObjectModel;
using Avalonia.Media;

namespace ML.App.ViewModels;

public sealed record CupTie(string Home, string Away, string Score, bool Mine, bool Played, IBrush Bg);

public sealed record CupRound(string Name, ObservableCollection<CupTie> Ties);

public sealed record CupSection(string Header, string Status, ObservableCollection<CupRound> Rounds);

/// <summary>Both knockout brackets — every round's ties, your path highlighted.</summary>
public sealed class CupViewModel : PageViewModel
{
    public CupViewModel(Session s)
    {
        foreach (var cup in Session.Cups)
        {
            var rounds = new ObservableCollection<CupRound>();
            foreach (var (round, ties) in s.CupDrawFor(cup.LeagueId))
            {
                var list = new ObservableCollection<CupTie>();
                foreach (var f in ties)
                {
                    var r = s.ResultFor(f.Id);
                    var score = r is null ? "v"
                        : r.HomeGoals == r.AwayGoals
                            ? $"{r.HomeGoals}-{r.AwayGoals} ({s.TeamName(s.CupWinnerOf(f))} on pens)"
                            : $"{r.HomeGoals}-{r.AwayGoals}";
                    var mine = f.HomeTeamId == s.CurrentTeamId || f.AwayTeamId == s.CurrentTeamId;
                    list.Add(new CupTie(
                        s.TeamName(f.HomeTeamId), s.TeamName(f.AwayTeamId), score, mine, f.Played,
                        mine ? Visuals.Brush("#2E1F9D4D") : Brushes.Transparent));
                }
                rounds.Add(new CupRound(round, list));
            }
            var status = rounds.Count == 0
                ? "The draw is made at the start of each season."
                : rounds.Any(r => r.Ties.Any(t => t.Mine && !t.Played))
                    ? "You're still in it — your tie is on the calendar."
                    : rounds.SelectMany(r => r.Ties).Any(t => t.Mine)
                        ? "Your run is over for this season."
                        : "Your club missed this draw (32 of the clubs enter).";
            Sections.Add(new CupSection(cup.Name, status, rounds));
        }
    }

    public override string Title => "Cups";
    public override string Icon => "🏆";
    public ObservableCollection<CupSection> Sections { get; } = new();
}
