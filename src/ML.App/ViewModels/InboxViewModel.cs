using System.Collections.ObjectModel;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- News (the Sky-style feed the inbox always wanted to be) ----------------------

public sealed record NewsEntry(
    long Id, string Icon, string Category, string Subject, string Body, string When, bool Unread,
    Bitmap? Portrait, bool IsBreaking, Bitmap? Crest = null,
    long? PlayerId = null, int? TeamId = null, bool RequiresAction = false)
{
    // A story that is waiting on a decision shows the decision, in place (P10). An offer for
    // one of your players is answerable here; a job offer is the Board's to take.
    public bool ShowOfferActions => RequiresAction && PlayerId is not null;
    public bool ShowBoardAction => RequiresAction && PlayerId is null && TeamId is not null;
    public bool ShowActions => ShowOfferActions || ShowBoardAction;
    public IBrush SubjectBrush => Visuals.Brush(Unread ? "#FFFFFF" : "#8A93A2");
    public IBrush BodyBrush => Visuals.Brush(Unread ? "#C7CEDA" : "#5E6774");
    public FontWeight SubjectWeight => Unread ? FontWeight.Bold : FontWeight.Normal;
    public bool ShowNew => Unread;
    public bool HasPortrait => Portrait is not null;
    /// <summary>Club crest in the avatar slot — only when there is no player face.</summary>
    public bool HasCrest => Crest is not null && Portrait is null;
    // Breaking news takes the danger bar regardless of category.
    public IBrush AccentBrush => Visuals.Brush(IsBreaking ? "#D64545" : Category switch
    {
        "Transfer" => "#F5C044",
        "Board" => "#5AA7F0",
        "Player" => "#2EC4A6",
        "Media" => "#8A93A2",
        _ => "#3A4759",
    });
}

public sealed record TickerEntry(string Player, string Line, Bitmap? Portrait, long PlayerId = 0)
{
    public bool HasPortrait => Portrait is not null;
    public string Mark => Visuals.PlayerMark(Player);
}

public sealed partial class InboxViewModel : PageViewModel
{
    private readonly Session _s;

    public InboxViewModel(Session s)
    {
        _s = s;
        Reload();
    }

    private void Reload()
    {
        Rows.Clear();
        foreach (var m in _s.InboxMessages())
        {
            Bitmap? face = null;
            if (m.PlayerId is { } pid)
            {
                try
                {
                    var (path, _) = _s.NewsFaceOf(pid);
                    face = Visuals.LoadBitmap(path);
                }
                catch { /* faceless news is fine */ }
            }
            // No face? A club crest fills the avatar slot when the message carries a team.
            Bitmap? crest = null;
            if (face is null && m.TeamId is { } tid)
            {
                try { crest = Visuals.LoadBitmap(_s.TeamLogoPath(tid)); }
                catch { /* crestless news is fine too */ }
            }
            Rows.Add(new NewsEntry(m.Id, IconFor(m.Category), m.Category, m.Subject, m.Body,
                m.Matchday is { } md and > 0 ? $"MD{md}" : "", !m.IsRead, face,
                m.Subject.Contains("DEADLINE DAY"), crest,
                m.PlayerId, m.TeamId, m.RequiresAction));
        }
        Header = $"News — {Rows.Count(r => r.Unread)} unread";
        Empty = Rows.Count == 0;

        // DONE DEAL hero: the latest paid move in the world.
        try
        {
            var feed = _s.TransfersFeed(10);
            var hero = feed.FirstOrDefault(t => t.Fee > 0);
            if (hero.Player is { Length: > 0 })
            {
                HeroVisible = true;
                HeroName = hero.Player;
                HeroLine = $"→ {hero.ToTeam}";
                HeroFee = $"£{hero.Fee:N0}";
                _heroPlayerId = hero.PlayerId;
                var (path, _) = _s.NewsFaceOf(hero.PlayerId);
                HeroPortrait = Visuals.LoadBitmap(path);
            }
            Ticker.Clear();
            foreach (var t in feed)
            {
                var (path, _) = _s.NewsFaceOf(t.PlayerId);
                Ticker.Add(new TickerEntry(t.Player,
                    t.Fee > 0 ? $"→ {t.ToTeam} · £{t.Fee:N0}" : $"→ {t.ToTeam}",
                    Visuals.LoadBitmap(path), t.PlayerId));
            }
        }
        catch { HeroVisible = false; }
        HasTicker = Ticker.Count > 0;
        HasHeroPortrait = HeroPortrait is not null;
    }

    public override string Title => "News";
    public override string Icon => "📰";
    public ObservableCollection<NewsEntry> Rows { get; } = new();
    public ObservableCollection<TickerEntry> Ticker { get; } = new();

    [ObservableProperty] private string _header = "News";
    [ObservableProperty] private bool _empty;
    [ObservableProperty] private bool _hasTicker;
    [ObservableProperty] private bool _heroVisible;
    [ObservableProperty] private string _heroName = "";
    [ObservableProperty] private string _heroLine = "";
    [ObservableProperty] private string _heroFee = "";
    [ObservableProperty] private Bitmap? _heroPortrait;
    [ObservableProperty] private bool _hasHeroPortrait;

    [RelayCommand]
    private void MarkAllRead()
    {
        _s.MarkInboxRead();
        Reload();
    }

    /// <summary>Clicking a message marks that one message read (P6).</summary>
    [RelayCommand]
    private void MarkRead(NewsEntry? entry)
    {
        if (entry is null || !entry.Unread) return;
        try
        {
            using var cmd = _s.Db.Connection.CreateCommand();
            cmd.CommandText = "UPDATE inbox SET is_read=1 WHERE id=$id";
            cmd.Parameters.AddWithValue("$id", entry.Id);
            cmd.ExecuteNonQuery();
        }
        catch (Exception ex)
        {
            // A click on a letter must never take the app down; it simply stays unread.
            Program.Log("Inbox.MarkRead", ex);
            return;
        }
        var i = Rows.IndexOf(entry);
        if (i >= 0) Rows[i] = entry with { Unread = false };
        Header = $"News — {Rows.Count(r => r.Unread)} unread";
    }

    // --- acting on the news (P10) -------------------------------------------------
    // A story names a player or a club; the same right-click vocabulary the rest of the
    // app uses works here too, and the three letters that wait on a decision carry it.

    private long _heroPlayerId;

    [ObservableProperty] private string _status = "";

    /// <summary>Right-click a story: the player it is about, else the club it is about.</summary>
    public Avalonia.Controls.ContextMenu? MenuFor(NewsEntry? e)
    {
        if (e is null) return null;
        if (e.PlayerId is { } pid && pid > 0)
            return EntityActions.BuildMenu(_s, EntityRef.Player(pid, _s.PlayerNameOf(pid)),
                status: t => Status = t, refresh: Reload);
        if (e.TeamId is { } tid && tid > 0)
            return EntityActions.BuildMenu(_s, EntityRef.Club(tid, _s.TeamName(tid)),
                status: t => Status = t, refresh: Reload);
        return null;
    }

    public Avalonia.Controls.ContextMenu? MenuForTicker(TickerEntry? t)
        => t is null || t.PlayerId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Player(t.PlayerId, t.Player),
                status: x => Status = x, refresh: Reload);

    public Avalonia.Controls.ContextMenu? MenuForHero()
        => _heroPlayerId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Player(_heroPlayerId, HeroName),
                status: x => Status = x, refresh: Reload);

    // Two-step, on the Status line rather than the button label: NewsEntry is a plain record
    // rendered by an ItemsControl template, so there is no per-row mutable state to flip a
    // label on without rebuilding the list. The story card's own Command="{Binding}" (the row
    // itself) is the key: a second click ON THE SAME STORY confirms; clicking a different one
    // re-arms instead of accepting the wrong player.
    private long _armedOfferEntryId;

    /// <summary>Answer an offer from the story itself — no trip to the Market.</summary>
    [RelayCommand]
    private void AcceptOffer(NewsEntry? e)
    {
        if (e?.PlayerId is not { } pid) return;
        if (_armedOfferEntryId != pid)
        {
            _armedOfferEntryId = pid;
            string name;
            try { name = _s.PlayerNameOf(pid); } catch { name = "him"; }
            Status = $"Sell {name}? Click Accept offer again to confirm.";
            return;
        }
        _armedOfferEntryId = 0;
        Status = _s.AcceptOffer(pid);
        MarkRead(e);
        Reload();
    }

    [RelayCommand]
    private void RejectOffer(NewsEntry? e)
    {
        if (e?.PlayerId is not { } pid) return;
        _armedOfferEntryId = 0;
        _s.RejectOffer(pid);
        Status = "Offer turned down.";
        MarkRead(e);
        Reload();
    }

    /// <summary>Job offers are the Board's to take — go there, don't retype it.</summary>
    [RelayCommand]
    private void OpenBoard() => Nav.Go("Board");

    private static string IconFor(string c) => c switch
    {
        "Board" => "🏛️",
        "Player" => "👤",
        "Media" => "📰",
        "Transfer" => "🔁",
        _ => "•",
    };
}
