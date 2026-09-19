using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;

namespace ML.App.ViewModels;

/// <summary>One tie in a bracket. It keeps the fixture and both club ids, so the card is a
/// handle on the two clubs in it rather than two rendered names.</summary>
public sealed record CupTie(string Home, string Away, string Score, bool Mine, bool Played, IBrush Bg,
    Avalonia.Media.Imaging.Bitmap? HomeCrest = null, Avalonia.Media.Imaging.Bitmap? AwayCrest = null,
    int FixtureId = 0, int HomeTeamId = 0, int AwayTeamId = 0);

public sealed record CupRound(string Name, ObservableCollection<CupTie> Ties);

public sealed record CupSection(string Header, string Status, ObservableCollection<CupRound> Rounds);

/// <summary>Both knockout brackets — every round's ties, your path highlighted.</summary>
public sealed partial class CupViewModel : PageViewModel
{
    private readonly Session _s;

    public CupViewModel(Session s)
    {
        _s = s;
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
                            ? $"{r.HomeGoals}-{r.AwayGoals} (pens)"
                            : $"{r.HomeGoals}-{r.AwayGoals}";
                    var mine = f.HomeTeamId == s.CurrentTeamId || f.AwayTeamId == s.CurrentTeamId;
                    list.Add(new CupTie(
                        s.TeamName(f.HomeTeamId), s.TeamName(f.AwayTeamId), score, mine, f.Played,
                        mine ? Visuals.Brush("#2E1F9D4D") : Brushes.Transparent,
                        Visuals.LoadBitmap(s.TeamLogoPath(f.HomeTeamId)),
                        Visuals.LoadBitmap(s.TeamLogoPath(f.AwayTeamId)),
                        f.Id, f.HomeTeamId, f.AwayTeamId));
                }
                rounds.Add(new CupRound(round, list));
            }

            // THE ROAD TO THE FINAL, drawn or not. Only rounds with fixtures came back from
            // CupDrawFor, so in July a knockout cup was ONE column of sixteen ties with seventeen
            // hundred pixels of empty pitch beside it — a bracket that shows no bracket. Every
            // round of every cup is declared up front in Session.Cups; the ones not yet drawn now
            // stand as empty ties, so you can see the shape of the run from the first day.
            if (rounds.Count > 0)
            {
                var drawn = rounds.Select(r => r.Name).ToHashSet();
                foreach (var (size, _, name) in cup.Rounds)
                {
                    if (drawn.Contains(name)) continue;
                    var blanks = new ObservableCollection<CupTie>();
                    for (var i = 0; i < size / 2; i++)
                    {
                        // "—  —" alone read as broken data (audit C7) — the round header says
                        // "to come" but each tie is a separate glance, and a bare dash on its
                        // own says nothing about why.
                        blanks.Add(new CupTie("Not drawn yet", "Not drawn yet", "", false, false, Brushes.Transparent));
                    }
                    rounds.Add(new CupRound($"{name} · to come", blanks));
                }
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

    /// <summary>Verb results (a scout dispatched from a bracket) land here, verbatim.</summary>
    [ObservableProperty] private string _statusLine = "";

    /// <summary>
    /// Right-click a tie: both clubs in it, each offered a squad view and a scouting mission.
    /// Hand-built rather than the shared club menu because a tie has TWO subjects — the guard
    /// wording follows EntityActions so a disabled item always says why.
    /// </summary>
    public ContextMenu? MenuFor(CupTie tie)
    {
        if (tie.HomeTeamId <= 0 && tie.AwayTeamId <= 0) return null;

        var noScout = _s.StaffFor("Scout") is null;
        var scoutBusy = _s.ActiveScoutJob() is not null;
        var menu = new ContextMenu();

        void Club(int tid, string label)
        {
            if (tid <= 0) return;
            var name = label.Length > 0 ? label : _s.TeamName(tid);
            var mine = tid == _s.CurrentTeamId;

            var view = new MenuItem { Header = mine ? "🏟 View my squad" : $"🏟 View {name}" };
            view.Click += (_, _) => Nav.Go("Squad", EntityRef.Club(tid, name));
            menu.Items.Add(view);

            var header = mine ? $"🔍 Scout {name} — that's your club"
                : noScout ? $"🔍 Scout {name} — needs a scout"
                : scoutBusy ? $"🔍 Scout {name} — scout on a mission"
                : $"🔍 Scout {name}";
            var scout = new MenuItem { Header = header, IsEnabled = !mine && !noScout && !scoutBusy };
            scout.Click += (_, _) =>
            {
                try
                {
                    var line = _s.StartScoutJob("club", tid, name);
                    if (line.Length > 0) StatusLine = line;
                }
                catch (Exception ex) { StatusLine = ex.Message; }
            };
            menu.Items.Add(scout);
        }

        Club(tie.HomeTeamId, tie.Home);
        if (tie.HomeTeamId > 0 && tie.AwayTeamId > 0) menu.Items.Add(new Separator());
        Club(tie.AwayTeamId, tie.Away);
        return menu.Items.Count == 0 ? null : menu;
    }
}
