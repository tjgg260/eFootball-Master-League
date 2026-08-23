using System.Collections.ObjectModel;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- News (the Sky-style feed the inbox always wanted to be) ----------------------

public sealed record NewsEntry(
    long Id, string Icon, string Category, string Subject, string Body, string When, bool Unread,
    Bitmap? Portrait, bool IsBreaking)
{
    public IBrush SubjectBrush => Visuals.Brush(Unread ? "#FFFFFF" : "#8A93A2");
    public IBrush BodyBrush => Visuals.Brush(Unread ? "#C7CEDA" : "#5E6774");
    public FontWeight SubjectWeight => Unread ? FontWeight.Bold : FontWeight.Normal;
    public bool ShowNew => Unread;
    public bool HasPortrait => Portrait is not null;
    public IBrush AccentBrush => Visuals.Brush(Category switch
    {
        "Transfer" => "#F5C044",
        "Board" => "#5AA7F0",
        "Player" => "#2EC4A6",
        "Media" => "#8A93A2",
        _ => "#3A4759",
    });
}

public sealed record TickerEntry(string Player, string Line, Bitmap? Portrait)
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
            Rows.Add(new NewsEntry(m.Id, IconFor(m.Category), m.Category, m.Subject, m.Body,
                m.Matchday is { } md and > 0 ? $"MD{md}" : "", !m.IsRead, face,
                m.Subject.Contains("DEADLINE DAY")));
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
                var (path, _) = _s.NewsFaceOf(hero.PlayerId);
                HeroPortrait = Visuals.LoadBitmap(path);
            }
            Ticker.Clear();
            foreach (var t in feed)
            {
                var (path, _) = _s.NewsFaceOf(t.PlayerId);
                Ticker.Add(new TickerEntry(t.Player,
                    t.Fee > 0 ? $"→ {t.ToTeam} · £{t.Fee:N0}" : $"→ {t.ToTeam}",
                    Visuals.LoadBitmap(path)));
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
        using (var cmd = _s.Db.Connection.CreateCommand())
        {
            cmd.CommandText = "UPDATE inbox SET is_read=1 WHERE id=$id";
            cmd.Parameters.AddWithValue("$id", entry.Id);
            cmd.ExecuteNonQuery();
        }
        var i = Rows.IndexOf(entry);
        if (i >= 0) Rows[i] = entry with { Unread = false };
        Header = $"News — {Rows.Count(r => r.Unread)} unread";
    }

    private static string IconFor(string c) => c switch
    {
        "Board" => "🏛️",
        "Player" => "👤",
        "Media" => "📰",
        "Transfer" => "🔁",
        _ => "•",
    };
}
