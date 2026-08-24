using System.Collections.ObjectModel;
using System.IO;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- Transfermarket (browse the full master DB, with real fees) -------------------

public sealed record MarketPlayer(
    long Id, string Name, string Position, int Overall, int? Age, long ValueRaw, string Club,
    string? PortraitPath = null, int? SkinTone = null, int Knowledge = 100,
    string? TransferStatus = null, string? ClubLogoPath = null, bool Mine = false)
{
    public string StatusLabel => TransferStatus switch
    {
        "not-for-sale" => "NOT FOR SALE",
        "listed" => "LISTED",
        "loan-listed" => "LOAN",
        _ => "",
    };
    public bool HasStatus => StatusLabel.Length > 0;
    // Your own player has no buy-side action: the cell says so and the right-click menu
    // carries his real verbs (renew, transfer-list, loan out) instead.
    public bool ShowStatus => HasStatus && !Mine;
    public Avalonia.Media.IBrush StatusBrush => Visuals.Brush(TransferStatus switch
    {
        "not-for-sale" => "#D64545",
        "listed" => "#1F9D4D",
        _ => "#2D7DD2",
    });
    public string AgeLabel => Age?.ToString() ?? "—";
    public string Value => $"£{ValueRaw:N0}";
    // The overall is shown ONLY as a qualitative letter, and masked until the player is well
    // scouted or on your team ("?" / "B?" instead of the real grade).
    public string Grade => ML.Core.Development.AttributeKnowledge.GradeMasked(Overall, Knowledge);
    public Avalonia.Media.IBrush RatingBrush =>
        Knowledge >= 75 ? Visuals.RatingBrush(Overall) : Visuals.Brush("#8A93A2");
    public Avalonia.Media.Imaging.Bitmap? Portrait => Visuals.LoadBitmap(PortraitPath);
    public bool HasPortrait => Portrait is not null;
    public string Mark => Visuals.PlayerMark(Name);
    public Avalonia.Media.IBrush FaceBrush => Visuals.SkinBrush(SkinTone);
    // Lazily evaluated at bind time — i.e. on the UI thread, never in the background query.
    public Avalonia.Media.Imaging.Bitmap? ClubCrest => Visuals.LoadBitmap(ClubLogoPath);
    public bool HasClubCrest => ClubCrest is not null;
}

public sealed record OfferRow(long PlayerId, string Line);

public sealed partial class MarketViewModel : PageViewModel, IFocusTarget
{
    private static readonly string[] PositionFilters =
        { "All", "GK", "CB", "LB", "RB", "DMF", "CMF", "LMF", "RMF", "AMF", "LWF", "RWF", "SS", "CF" };

    private readonly Session _s;

    public MarketViewModel(Session s)
    {
        _s = s;
        // P6: typing must not requery 376k rows per keystroke — restartable 300ms debounce.
        _searchDebounce = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(300) };
        _searchDebounce.Tick += (_, _) => { _searchDebounce.Stop(); Requery(); };
        var masterDb = FindMasterDb();
        if (masterDb is not null)
        {
            using var con = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={masterDb};Mode=ReadOnly");
            con.Open();
            using var count = con.CreateCommand();
            count.CommandText = "SELECT COUNT(*) FROM players";
            TotalPlayers = Convert.ToInt32(count.ExecuteScalar());
            Requery();
        }
        LoadOffers();
    }

    public override string Title => "Market";
    public override string Icon => "🔁";
    public int TotalPlayers { get; }
    public string Header => TotalPlayers > 0 ? $"Transfermarket — {TotalPlayers:N0} players" : "Transfermarket";
    public ObservableCollection<MarketPlayer> Rows { get; } = new();
    public IReadOnlyList<string> Positions => PositionFilters;

    // Offers from CPU clubs for YOUR players.
    public ObservableCollection<OfferRow> Offers { get; } = new();
    public bool HasOffers => Offers.Count > 0;

    [ObservableProperty] private OfferRow? _selectedOffer;
    [ObservableProperty] private MarketPlayer? _selectedPlayer;

    // --- filters (all re-query live) ------------------------------------------------

    [ObservableProperty] private string _searchText = "";
    [ObservableProperty] private string _positionFilter = "All";
    [ObservableProperty] private decimal _maxAge = 45;
    // Calibre filter (UX P4): a letter floor, never a raw-number spinner. The thresholds are
    // the same bands AttributeKnowledge grades with, so "B or better" means what the card says.
    public IReadOnlyList<string> GradeFloors { get; } = new[]
        { "Any calibre", "C or better", "B or better", "A or better" };
    [ObservableProperty] private string _gradeFloor = "Any calibre";
    private decimal MinRating => GradeFloor switch
    {
        "A or better" => 78, "B or better" => 64, "C or better" => 52, _ => 40,
    };
    [ObservableProperty] private bool _freeAgentsOnly;

    // ⭐ The shortlist chip: when it's on the market shows EXACTLY the players you starred,
    // ignoring every other filter (including the search box) — it is a saved list, not a query.
    [ObservableProperty] private bool _shortlistOnly;

    // 🏟 A club focus (Nav.Go("Market", EntityRef.Club(...))) filters the world down to that
    // squad. Shown as a removable chip so it can never become an invisible filter.
    [ObservableProperty] private string _clubFilter = "";
    public bool HasClubFilter => ClubFilter.Length > 0;
    public string ClubFilterChip => $"🏟 {ClubFilter}  ✕";

    public IReadOnlyList<string> ValueCaps { get; } = new[]
        { "Any value", "≤ £100k", "≤ £250k", "≤ £500k", "≤ £1m", "≤ £2m", "≤ £5m", "≤ £10m" };

    [ObservableProperty] private string _valueCap = "Any value";

    public IReadOnlyList<string> SortOptions { get; } = new[]
        { "Best rated", "Most valuable", "Youngest", "Name A–Z" };

    [ObservableProperty] private string _sortBy = "Most valuable";

    private readonly DispatcherTimer _searchDebounce;

    partial void OnSearchTextChanged(string value)
    {
        _searchDebounce.Stop();     // restart pattern: only 300ms of silence fires the query
        _searchDebounce.Start();
    }
    partial void OnPositionFilterChanged(string value) => Requery();
    partial void OnMaxAgeChanged(decimal value) => Requery();
    partial void OnGradeFloorChanged(string value) => Requery();
    partial void OnFreeAgentsOnlyChanged(bool value) => Requery();
    partial void OnValueCapChanged(string value) => Requery();
    partial void OnSortByChanged(string value) => Requery();
    partial void OnShortlistOnlyChanged(bool value)
    {
        OnPropertyChanged(nameof(EmptyLine));
        Requery();
    }
    partial void OnClubFilterChanged(string value)
    {
        OnPropertyChanged(nameof(HasClubFilter));
        OnPropertyChanged(nameof(ClubFilterChip));
        Requery();
    }

    [RelayCommand]
    private void ToggleShortlist() => ShortlistOnly = !ShortlistOnly;

    [RelayCommand]
    private void ClearClubFilter() => ClubFilter = "";

    private static long CapOf(string label) => label switch
    {
        "≤ £100k" => 100_000,
        "≤ £250k" => 250_000,
        "≤ £500k" => 500_000,
        "≤ £1m" => 1_000_000,
        "≤ £2m" => 2_000_000,
        "≤ £5m" => 5_000_000,
        "≤ £10m" => 10_000_000,
        _ => long.MaxValue,
    };

    // Bidding: your offer as a share of market value. Clubs want a premium; free agents want value.
    public IReadOnlyList<string> BidOptions { get; } = new[]
        { "Lowball (−15%)", "Market value", "Premium (+15%)" };

    [ObservableProperty] private string _selectedBid = "Market value";
    [ObservableProperty] private string _windowLine = "";
    [ObservableProperty] private string _signStatus =
        "Search the world's players — click one for the full profile. Fees are real.";

    // --- async requery (P6): the 376k-row read happens off the UI thread ------------
    // Rows only ever mutate on the UI thread; a generation counter drops stale results
    // when a newer query has been issued while an older one was still running.

    [ObservableProperty] private bool _isSearching;
    [ObservableProperty] private bool _queryFailed;
    private int _queryGeneration;   // only incremented on the UI thread

    /// <summary>The grid's empty overlay: searching / no db / nothing matches.</summary>
    public bool ShowEmpty => Rows.Count == 0 && !QueryFailed;
    public string EmptyLine => IsSearching
        ? "Searching…"
        : TotalPlayers == 0
            ? "No master.db found — build the reference world to browse the market."
            : ShortlistOnly
                ? "Nothing on the shortlist yet — right-click a player and star him."
                : "0 players match these filters — loosen the calibre, age or value cap.";

    partial void OnIsSearchingChanged(bool value)
    {
        OnPropertyChanged(nameof(ShowEmpty));
        OnPropertyChanged(nameof(EmptyLine));
    }
    partial void OnQueryFailedChanged(bool value) => OnPropertyChanged(nameof(ShowEmpty));

    /// <summary>Everything the background query needs, snapshotted on the UI thread.
    /// Shortlist ids are read HERE (career connection) and handed over as plain numbers —
    /// the background thread never touches the Session.</summary>
    private sealed record QuerySnapshot(
        string Search, string Position, int MaxAge, int MinRating,
        bool FreeAgentsOnly, long Cap, string SortBy, string Club = "",
        IReadOnlyList<long>? Shortlist = null);

    private void Requery()
    {
        var gen = System.Threading.Interlocked.Increment(ref _queryGeneration);
        try { WindowLine = _s.TransferWindowLabel(); } catch { WindowLine = ""; }
        IReadOnlyList<long>? shortlist = null;
        if (ShortlistOnly)
        {
            try { shortlist = _s.ShortlistIds(); } catch { shortlist = Array.Empty<long>(); }
        }
        // The star list is exact: it bypasses the search box and every dropdown, so a shortlisted
        // 34-year-old still shows under an "under 24" filter you forgot you set.
        var snapshot = shortlist is not null
            ? new QuerySnapshot("", "All", 45, 0, false, long.MaxValue, SortBy, "", shortlist)
            : new QuerySnapshot(SearchText, PositionFilter, (int)MaxAge, (int)MinRating,
                FreeAgentsOnly, CapOf(ValueCap), SortBy, ClubFilter);
        IsSearching = true;
        Task.Run(() =>
        {
            try
            {
                var rows = QueryRows(snapshot);
                Dispatcher.UIThread.Post(() =>
                {
                    if (gen != _queryGeneration) return;    // superseded — drop the stale result
                    Rows.Clear();
                    // Knowledge masking resolves HERE, on the UI thread: KnowledgeOf reads the
                    // shared career Session connection, which the background thread must never
                    // touch. Only the 300 shown rows pay the lookup. Own-squad membership is one
                    // set read for the whole page, not a query per row.
                    var mine = OwnSquadIds();
                    foreach (var row in rows)
                    {
                        Rows.Add(row with { Knowledge = KnowledgeSafe(row.Id), Mine = mine.Contains(row.Id) });
                    }
                    QueryFailed = false;
                    IsSearching = false;                    // last: re-evaluates ShowEmpty with the new rows
                });
            }
            catch (Exception ex)
            {
                Program.Log("Market.Requery", ex);          // and P6: no longer swallowed silently —
                Dispatcher.UIThread.Post(() =>              // the grid shows the failure line below
                {
                    if (gen != _queryGeneration) return;
                    Rows.Clear();
                    QueryFailed = true;
                    IsSearching = false;
                });
            }
        });
    }

    /// <summary>Runs on a background thread. Touches only local connections and the Session
    /// value/knowledge lookups; it must NOT touch Rows or any other UI-bound state.</summary>
    private List<MarketPlayer> QueryRows(QuerySnapshot q)
    {
        var result = new List<MarketPlayer>();
        var masterDb = FindMasterDb();
        if (masterDb is null) return result;
        using var con = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={masterDb};Mode=ReadOnly");
        con.Open();

        using var cmd = con.CreateCommand();
        var where = new List<string>();
        if (!string.IsNullOrWhiteSpace(q.Search)) where.Add("p.name LIKE $q");
        if (q.Position != "All") where.Add("p.position = $pos");
        if (q.MaxAge < 45) where.Add("COALESCE(p.age, 25) <= $age");
        if (q.MinRating > 40) where.Add("COALESCE(p.overall_rating, 0) >= $min");
        if (q.Club.Length > 0)
        {
            where.Add("EXISTS (SELECT 1 FROM squad_members s2 JOIN teams t2 ON t2.id=s2.team_id " +
                      "WHERE s2.player_id=p.id AND t2.name=$club)");
        }
        // Shortlist mode: ids only, straight from the career DB — inlined because they are our own
        // numbers, and Requery already blanked every other filter so nothing else can narrow it.
        if (q.Shortlist is { } starred)
        {
            where.Clear();
            where.Add(starred.Count == 0 ? "0" : $"p.id IN ({string.Join(",", starred)})");
        }
        // The candidate pool is ordered by the chosen sort so "Most valuable" surfaces the world's
        // priciest players, not the highest-rated. A player's club is his ACTUAL team (any league,
        // not just the career divisions) — so the reference world reads as real clubs, and only a
        // genuinely unattached player is a free agent.
        var order = q.SortBy switch
        {
            "Most valuable" => "COALESCE((SELECT value FROM player_market WHERE player_id=p.id),0) DESC, " +
                               "p.overall_rating DESC",
            "Youngest" => "COALESCE(p.age,99) ASC, p.overall_rating DESC",
            "Name A–Z" => "p.name ASC",
            _ => "p.overall_rating DESC",
        };
        cmd.CommandText =
            "SELECT p.id, p.name, p.position, COALESCE(p.overall_rating,0), p.age, " +
            "COALESCE(p.real_face_path, p.portrait_path), " +
            "(SELECT skin_tone FROM player_appearance a WHERE a.player_id=p.id), " +
            "(SELECT t.name FROM squad_members s JOIN teams t ON t.id=s.team_id " +
            " WHERE s.player_id=p.id LIMIT 1), " +
            "(SELECT transfer_status FROM player_market m WHERE m.player_id=p.id), " +
            "COALESCE((SELECT value FROM player_market m WHERE m.player_id=p.id), 0), " +
            "(SELECT t.logo_path FROM squad_members s JOIN teams t ON t.id=s.team_id " +
            " WHERE s.player_id=p.id LIMIT 1) " +
            "FROM players p " +
            (where.Count > 0 ? "WHERE " + string.Join(" AND ", where) + " " : "") +
            "ORDER BY " + order + " LIMIT 4000";
        if (!string.IsNullOrWhiteSpace(q.Search)) cmd.Parameters.AddWithValue("$q", $"%{q.Search.Trim()}%");
        if (q.Position != "All") cmd.Parameters.AddWithValue("$pos", q.Position);
        if (q.MaxAge < 45) cmd.Parameters.AddWithValue("$age", q.MaxAge);
        if (q.MinRating > 40) cmd.Parameters.AddWithValue("$min", q.MinRating);
        if (q.Club.Length > 0) cmd.Parameters.AddWithValue("$club", q.Club);

        var found = new List<(long Id, string Name, string Pos, int Rating, int? Age, long Value,
            string Club, string? Portrait, int? Skin, string? Status, string? ClubLogo)>();
        using (var r = cmd.ExecuteReader())
        {
            while (r.Read())
            {
                var rating = r.GetInt32(3);
                int? age = r.IsDBNull(4) ? null : r.GetInt32(4);
                var id = r.GetInt64(0);           // player ids run past Int32 (curated/generated bands)
                var club = r.IsDBNull(7) ? "Free agent" : r.GetString(7);
                if (q.FreeAgentsOnly && club != "Free agent") continue;
                // Value comes from THIS master connection (thread-safety: the background query
                // must never touch the shared career Session connection); model fallback is pure.
                var stored = r.GetInt64(9);
                var value = stored > 0 ? stored : Session.ValuationOf(rating, age);
                if (value > q.Cap) continue;
                found.Add((id, r.GetString(1), r.GetString(2), rating, age, value, club,
                    r.IsDBNull(5) ? null : r.GetString(5), r.IsDBNull(6) ? null : r.GetInt32(6),
                    r.IsDBNull(8) ? null : r.GetString(8),
                    r.IsDBNull(10) ? null : r.GetString(10)));
            }
        }
        IEnumerable<(long Id, string Name, string Pos, int Rating, int? Age, long Value,
            string Club, string? Portrait, int? Skin, string? Status, string? ClubLogo)> sorted = q.SortBy switch
        {
            "Youngest" => found.OrderBy(p => p.Age ?? 99).ThenByDescending(p => p.Rating),
            "Name A–Z" => found.OrderBy(p => p.Name),
            "Best rated" => found.OrderByDescending(p => p.Rating),
            _ => found.OrderByDescending(p => p.Value).ThenByDescending(p => p.Rating),  // Most valuable
        };
        // Knowledge stays at the placeholder here — the UI-thread marshal fills it in
        // (KnowledgeOf uses the shared career connection; this thread must not).
        foreach (var p in sorted.Take(300))
        {
            result.Add(new MarketPlayer(p.Id, p.Name, p.Pos, p.Rating, p.Age, p.Value, p.Club,
                p.Portrait, p.Skin, 100, p.Status, p.ClubLogo));
        }
        return result;
    }

    private int KnowledgeSafe(long id)
    {
        try { return _s.FmAttributeMode ? _s.KnowledgeOf(id) : 100; }
        catch { return 100; }
    }

    /// <summary>Your squad's player ids — one read per page of rows, not one query per row.</summary>
    private HashSet<long> OwnSquadIds()
    {
        try { return _s.Repo.Squad(_s.CurrentTeamId).Select(m => m.PlayerId).ToHashSet(); }
        catch { return new HashSet<long>(); }
    }

    /// <summary>
    /// One player by id, straight from master.db — the path for a subject that isn't in the
    /// current result set: an incoming offer for a squad player, or a focused Nav.Go landing.
    /// </summary>
    private MarketPlayer? LoadPlayerById(long id)
    {
        var masterDb = FindMasterDb();
        if (masterDb is null) return null;
        try
        {
            using var con = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={masterDb};Mode=ReadOnly");
            con.Open();
            using var cmd = con.CreateCommand();
            cmd.CommandText =
                "SELECT p.id, p.name, p.position, COALESCE(p.overall_rating,0), p.age, " +
                "COALESCE(p.real_face_path, p.portrait_path), " +
                "(SELECT skin_tone FROM player_appearance a WHERE a.player_id=p.id), " +
                "(SELECT t.name FROM squad_members s JOIN teams t ON t.id=s.team_id " +
                " WHERE s.player_id=p.id LIMIT 1), " +
                "(SELECT transfer_status FROM player_market m WHERE m.player_id=p.id), " +
                "COALESCE((SELECT value FROM player_market m WHERE m.player_id=p.id), 0), " +
                "(SELECT t.logo_path FROM squad_members s JOIN teams t ON t.id=s.team_id " +
                " WHERE s.player_id=p.id LIMIT 1) " +
                "FROM players p WHERE p.id=$id";
            cmd.Parameters.AddWithValue("$id", id);
            using var r = cmd.ExecuteReader();
            if (!r.Read()) return null;
            var rating = r.GetInt32(3);
            int? age = r.IsDBNull(4) ? null : r.GetInt32(4);
            var stored = r.GetInt64(9);
            return new MarketPlayer(
                r.GetInt64(0), r.GetString(1), r.GetString(2), rating, age,
                stored > 0 ? stored : Session.ValuationOf(rating, age),
                r.IsDBNull(7) ? "Free agent" : r.GetString(7),
                r.IsDBNull(5) ? null : r.GetString(5),
                r.IsDBNull(6) ? null : r.GetInt32(6),
                KnowledgeSafe(id),
                r.IsDBNull(8) ? null : r.GetString(8),
                r.IsDBNull(10) ? null : r.GetString(10),
                IsMineSafe(id));
        }
        catch (Exception ex) { Program.Log("Market.LoadPlayerById", ex); return null; }
    }

    private bool IsMineSafe(long id)
    {
        try { return _s.IsOwnPlayer(id); }
        catch { return false; }
    }

    // --- the profile card: click a row, see the player -------------------------------

    [ObservableProperty] private bool _hasProfile;
    [ObservableProperty] private string _profileName = "";
    [ObservableProperty] private string _profilePosition = "";
    [ObservableProperty] private string _profileGrade = "?";
    [ObservableProperty] private Avalonia.Media.IBrush _profileRatingBrush = Visuals.Brush("#C7CEDA");
    [ObservableProperty] private Avalonia.Media.IBrush _profileFill = Visuals.Brush("#3A4759");
    [ObservableProperty] private Avalonia.Media.Imaging.Bitmap? _profilePortrait;
    [ObservableProperty] private bool _profileHasPortrait;
    [ObservableProperty] private string _profileBio = "";
    [ObservableProperty] private string _profileValueLine = "";
    [ObservableProperty] private string _profileClub = "";
    [ObservableProperty] private Avalonia.Media.Imaging.Bitmap? _profileCrest;
    [ObservableProperty] private bool _profileHasCrest;
    [ObservableProperty] private string _profilePlaystyle = "";
    [ObservableProperty] private Points _profileRadar = new();
    [ObservableProperty] private IReadOnlyList<AbilityEntry> _profileAbilities = Array.Empty<AbilityEntry>();
    [ObservableProperty] private string _profileKnowledgeLine = "";
    [ObservableProperty] private string _profileCoachLine = "";
    // The scout's one-line fit verdict, lifted out of the full dossier.
    [ObservableProperty] private string _profileVerdictLine = "";
    [ObservableProperty] private bool _profileHasVerdict;
    // Your own player has no buy-side row: the pane says "yours" and the menu does the rest.
    [ObservableProperty] private bool _profileIsMine;
    [ObservableProperty] private string _scoutButtonLabel = "🔍 Send scout";
    [ObservableProperty] private bool _canScout;

    /// <summary>
    /// Whoever the profile pane is currently showing. Usually the selected grid row, but an
    /// incoming-offer click can put a player in the pane who isn't in the result set — every
    /// pane action works on THIS, so the buttons can never act on a different player.
    /// </summary>
    private MarketPlayer? _profileSubject;
    private MarketPlayer? Subject => _profileSubject ?? SelectedPlayer;

    partial void OnSelectedPlayerChanged(MarketPlayer? value)
    {
        if (value is null) { _profileSubject = null; HasProfile = false; return; }
        BuildProfile(value);
    }

    /// <summary>
    /// An offer names one of YOUR players — clicking it should show him, not leave the pane on
    /// whatever the grid happened to be sitting on. He is rarely in the market rows, so he is
    /// looked up by id when he isn't.
    /// </summary>
    partial void OnSelectedOfferChanged(OfferRow? value)
    {
        if (value is null) return;
        try
        {
            var row = Rows.FirstOrDefault(r => r.Id == value.PlayerId);
            if (row is not null)
            {
                SelectedPlayer = row;   // grid selection follows the offer
                BuildProfile(row);      // ...and the pane rebuilds even if the row was already selected
                return;
            }
            if (LoadPlayerById(value.PlayerId) is { } loaded) BuildProfile(loaded);
        }
        catch { /* the offer list must never take the screen down */ }
    }

    private void BuildProfile(MarketPlayer value)
    {
        // A new subject kills any half-open negotiation: the fee/wage boxes belong to one player.
        if (_profileSubject?.Id != value.Id)
        {
            Negotiating = false;
            DealAgreed = false;
        }
        _profileSubject = value;
        try
        {
            ProfileName = value.Name;
            ProfilePosition = value.Position;
            ProfileGrade = value.Grade;                 // gated letter, never the raw number
            ProfileRatingBrush = value.RatingBrush;
            ProfileFill = Visuals.PositionBrush(value.Position);
            ProfileClub = value.Club;
            ProfileCrest = value.ClubCrest;         // UI thread — selection change
            ProfileHasCrest = ProfileCrest is not null;
            ProfileIsMine = value.Mine;
            ProfileValueLine = $"Market value {value.Value}" +
                               (value.HasStatus ? $"   ·   {value.StatusLabel}" : "");

            using var con = new Microsoft.Data.Sqlite.SqliteConnection(
                $"Data Source={FindMasterDb()};Mode=ReadOnly");
            con.Open();
            using (var cmd = con.CreateCommand())
            {
                cmd.CommandText = "SELECT age, height_cm, weight_kg, nationality, " +
                                  "COALESCE(real_face_path, portrait_path), " +
                                  "(SELECT playstyle FROM player_playstyles WHERE player_id=$p LIMIT 1) " +
                                  "FROM players WHERE id=$p";
                cmd.Parameters.AddWithValue("$p", value.Id);
                using var r = cmd.ExecuteReader();
                if (r.Read())
                {
                    var bits = new List<string>();
                    if (!r.IsDBNull(0)) bits.Add($"{r.GetInt32(0)} yrs");
                    if (!r.IsDBNull(1)) bits.Add($"{r.GetInt32(1)} cm");
                    if (!r.IsDBNull(2)) bits.Add($"{r.GetInt32(2)} kg");
                    if (!r.IsDBNull(3) && r.GetString(3).Length > 0) bits.Add(r.GetString(3));
                    ProfileBio = bits.Count > 0 ? string.Join("  ·  ", bits) : "";
                    ProfilePortrait = r.IsDBNull(4) ? null : Visuals.LoadBitmap(r.GetString(4));
                    ProfileHasPortrait = ProfilePortrait is not null;
                    ProfilePlaystyle = r.IsDBNull(5) ? "" : r.GetString(5);
                }
            }
            var abilities = new Dictionary<string, int>();
            using (var cmd = con.CreateCommand())
            {
                cmd.CommandText = "SELECT attribute, value FROM player_attributes WHERE player_id=$p";
                cmd.Parameters.AddWithValue("$p", value.Id);
                using var r = cmd.ExecuteReader();
                while (r.Read()) abilities[r.GetString(0)] = r.GetInt32(1);
            }
            var isGk = value.Position == "GK";
            // Knowledge gates the profile (P5): unknown players are blanks until scouted.
            var knowledge = 100;
            var fm = false;
            try { knowledge = _s.KnowledgeOf(value.Id); fm = _s.FmAttributeMode; } catch { }
            ProfileKnowledgeLine = fm
                ? $"Knowledge: {ML.Core.Development.AttributeKnowledge.KnowledgeLabel(knowledge)}" +
                  (knowledge < 75 ? "  ·  send a scout to reveal more" : "")
                : "";
            ProfileRadar = !fm || knowledge >= 45
                ? PlayerCard.BuildRadarPoints(Visuals.RadarAxes(abilities, isGk))
                : new Points();
            ProfileAbilities = PlayerCard.BuildAbilityList(abilities, isGk, fm, knowledge, value.Id);
            try { ProfileCoachLine = string.Join("  ·  ", _s.CoachReportOf(value.Id, value.Position)); }
            catch { ProfileCoachLine = ""; }
            LoadVerdict(value, fm, knowledge);
            RefreshScoutButton();
            HasProfile = true;
        }
        catch { HasProfile = false; }
    }

    /// <summary>
    /// The scout's bottom line — his fit against your incumbent — and nothing else from the
    /// dossier. Only for a player the club actually has a read on: a dossier of his own, or a
    /// name already well enough known that the grade isn't masked either.
    /// </summary>
    private void LoadVerdict(MarketPlayer value, bool fm, int knowledge)
    {
        ProfileVerdictLine = "";
        ProfileHasVerdict = false;
        if (value.Mine) return;
        try
        {
            // He must exist in the CAREER world — PlayerScoutReport reads that DB, and a
            // reference-only player would come back as a nameless zero-rated comparison.
            if (_s.PlayerNameOf(value.Id).Length == 0) return;
            var scouted = _s.CompletedScoutJobs(50)
                .Any(j => j.Kind == "player" && j.TargetId == value.Id);
            if (!scouted && fm && knowledge < 75) return;
            var line = _s.PlayerScoutReport(value.Id)
                .Split('\n')
                .Select(l => l.Trim())
                .FirstOrDefault(l => l.StartsWith("Verdict:"));
            if (string.IsNullOrEmpty(line)) return;
            ProfileVerdictLine = $"🔍 {line}";
            ProfileHasVerdict = true;
        }
        catch { ProfileVerdictLine = ""; ProfileHasVerdict = false; }
    }

    /// <summary>The same pre-checks the shared right-click menu uses: no scout, or scout busy.</summary>
    private void RefreshScoutButton()
    {
        try
        {
            var noScout = _s.StaffFor("Scout") is null;
            var busy = _s.ActiveScoutJob() is not null;
            ScoutButtonLabel = noScout
                ? "🔍 Send scout — needs a scout"
                : busy ? "🔍 Send scout — scout on a mission" : "🔍 Send scout";
            CanScout = !noScout && !busy;
        }
        catch { ScoutButtonLabel = "🔍 Send scout"; CanScout = false; }
    }

    [RelayCommand]
    private void SendScout()
    {
        if (Subject is not { } p) { SignStatus = "Pick a player first."; return; }
        SignStatus = _s.StartScoutJob("player", p.Id, p.Name);
        RefreshScoutButton();
    }

    [RelayCommand]
    private void Enquire()
    {
        if (Subject is not { } p) { SignStatus = "Pick a player first."; return; }
        SignStatus = _s.MakeEnquiry(p.Id);
    }

    /// <summary>
    /// The shared right-click vocabulary on a market row, plus the two verbs this screen owns:
    /// the negotiation table and the loan. MlMenu selects the row first, so both act on him.
    /// </summary>
    public ContextMenu? MenuFor(MarketPlayer row)
    {
        var extras = new List<MenuItem>();
        if (!row.Mine && row.Club != "Free agent")
        {
            var talks = new MenuItem { Header = "🤝 Open negotiation" };
            talks.Click += (_, _) => OpenTalks();
            var loan = new MenuItem { Header = "↔ Loan until June" };
            loan.Click += (_, _) => LoanIn();
            extras.Add(talks);
            extras.Add(loan);
        }
        return EntityActions.BuildMenu(_s, EntityRef.Player(row.Id, row.Name),
            status: t => SignStatus = t,
            // A full requery would drop the profile pane and the selection; the verbs report
            // through the status line instead. The one list that must follow is the star list.
            refresh: () => { if (ShortlistOnly) Requery(); },
            extras: extras.Count > 0 ? extras : null);
    }

    /// <summary>
    /// Focused arrival (Nav.Go("Market", …)). A player is pulled into the rows and selected even
    /// if no search would have found him; a club narrows the whole market to that squad.
    /// </summary>
    public void Focus(EntityRef target)
    {
        try
        {
            if (target.Kind == EntityKind.Club)
            {
                var club = target.Name.Length > 0 ? target.Name : _s.TeamName((int)target.Id);
                if (club.Length > 0 && club != "?") ClubFilter = club;   // setter requeries
                return;
            }
            if (target.Kind != EntityKind.Player) return;

            var name = target.Name.Length > 0 ? target.Name : _s.PlayerNameOf(target.Id);
            SearchText = name;          // the box names who you came looking for…
            _searchDebounce.Stop();     // …but its pending query must not wipe the row below
            // and neither must the constructor's search, which is still in flight on arrival
            System.Threading.Interlocked.Increment(ref _queryGeneration);

            var row = Rows.FirstOrDefault(r => r.Id == target.Id) ?? LoadPlayerById(target.Id);
            if (row is null)
            {
                IsSearching = false;
                SignStatus = $"{name} isn't in the reference world — nothing to show.";
                return;
            }
            if (Rows.All(r => r.Id != row.Id)) Rows.Insert(0, row);
            SelectedPlayer = row;
            BuildProfile(row);
            IsSearching = false;                        // re-evaluates the empty overlay…
            OnPropertyChanged(nameof(ShowEmpty));       // …even if it was already false
        }
        catch { /* focused navigation must never take the screen down */ }
    }

    private void LoadOffers()
    {
        Offers.Clear();
        try
        {
            foreach (var o in _s.PendingOffers())
            {
                Offers.Add(new OfferRow(o.PlayerId, $"{o.FromTeam} bid £{o.Fee:N0} for {o.PlayerName}"));
            }
        }
        catch { /* offers are optional */ }
        OnPropertyChanged(nameof(HasOffers));
    }

    [RelayCommand]
    private void Sign()
    {
        if (Subject is not { } p) { SignStatus = "Pick a player first."; return; }
        if (p.Mine) { SignStatus = $"{p.Name} is already yours — right-click him for squad actions."; return; }
        var pct = SelectedBid.StartsWith("Lowball") ? 85 : SelectedBid.StartsWith("Premium") ? 115 : 100;
        SignStatus = _s.BuyPlayer(p.Id, pct);
        Requery();   // club ownership may have changed hands
    }

    // --- negotiation v2 (P5): rounds vs the selling club, then the agent ---------------

    [ObservableProperty] private bool _negotiating;
    [ObservableProperty] private bool _dealAgreed;
    [ObservableProperty] private string _negLine = "";
    [ObservableProperty] private string _negStance = "";
    [ObservableProperty] private decimal _negFee;
    [ObservableProperty] private bool _negSellOn;
    [ObservableProperty] private bool _negInstalments;
    [ObservableProperty] private string _likelihoodLine = "";
    [ObservableProperty] private decimal _negWage;
    [ObservableProperty] private string _negYears = "3";
    public IReadOnlyList<string> YearsOptions { get; } = new[] { "1", "2", "3", "4" };

    partial void OnNegFeeChanged(decimal value) => RefreshLikelihood();
    partial void OnNegSellOnChanged(bool value) => RefreshLikelihood();
    partial void OnNegInstalmentsChanged(bool value) => RefreshLikelihood();

    private void RefreshLikelihood()
    {
        if (Subject is not { } p || !Negotiating) return;
        var pctv = _s.DealLikelihood(p.Id, (long)NegFee, NegSellOn ? 15 : 0, NegInstalments);
        LikelihoodLine = $"Deal likelihood ~{pctv}% · sell-on counts as real money · round talks end at 3";
    }

    [RelayCommand]
    private void OpenTalks()
    {
        if (Subject is not { } p) { SignStatus = "Pick a player first."; return; }
        NegLine = _s.StartNegotiation(p.Id);
        var n = _s.NegotiationFor(p.Id);
        if (n is null || n.State == "dead") { Negotiating = false; SignStatus = NegLine; return; }
        Negotiating = true;
        DealAgreed = n.State == "agreed";
        NegStance = n.Stance;
        NegFee = n.Ask;
        NegWage = _s.SigningWageDemand(p.Id, int.Parse(NegYears));
        RefreshLikelihood();
    }

    [RelayCommand]
    private void LoanIn()
    {
        if (Subject is not { } p) { SignStatus = "Pick a player first."; return; }
        SignStatus = _s.LoanIn(p.Id);
        if (SignStatus.StartsWith("Loan DONE")) Requery();
    }

    [RelayCommand]
    private void SendOffer()
    {
        if (Subject is not { } p || !Negotiating) return;
        var (msg, agreed, dead) = _s.SendClubOffer(
            p.Id, (long)NegFee, NegSellOn ? 15 : 0, NegInstalments);
        NegLine = msg;
        DealAgreed = agreed;
        if (dead) Negotiating = false;
        if (!dead && !agreed && _s.NegotiationFor(p.Id) is { } n)
        {
            NegStance = n.Stance;
            RefreshLikelihood();
        }
    }

    [RelayCommand]
    private void CompleteDeal()
    {
        if (Subject is not { } p || !DealAgreed) return;
        SignStatus = _s.CompleteSigning(p.Id, (long)NegFee, NegSellOn ? 15 : 0,
            NegInstalments, (long)NegWage, int.Parse(NegYears));
        if (SignStatus.StartsWith("DONE DEAL"))
        {
            Negotiating = false;
            DealAgreed = false;
            Requery();
        }
        else
        {
            NegLine = SignStatus;   // the agent said no — adjust wages/years and retry
        }
    }

    [RelayCommand]
    private void WalkAway()
    {
        if (Subject is not { } p) return;
        _s.WalkAwayFromNegotiation(p.Id);
        Negotiating = false;
        DealAgreed = false;
        SignStatus = "You walked away from the table.";
    }

    [RelayCommand]
    private void AcceptOffer()
    {
        if (SelectedOffer is null) { SignStatus = "Pick an offer first."; return; }
        SignStatus = _s.AcceptOffer(SelectedOffer.PlayerId);
        LoadOffers();
    }

    [RelayCommand]
    private void RejectOffer()
    {
        if (SelectedOffer is null) { SignStatus = "Pick an offer first."; return; }
        _s.RejectOffer(SelectedOffer.PlayerId);
        SignStatus = "Offer rejected — they'll come back next summer if they're still keen.";
        LoadOffers();
    }

    private static string? FindMasterDb()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "build", "master.db");
            if (File.Exists(candidate))
            {
                return candidate;
            }
            dir = dir.Parent;
        }
        return null;
    }
}
