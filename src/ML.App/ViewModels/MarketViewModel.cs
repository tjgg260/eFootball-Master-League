using System.Collections.ObjectModel;
using System.IO;
using Avalonia;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- Transfermarket (browse the full master DB, with real fees) -------------------

public sealed record MarketPlayer(
    int Id, string Name, string Position, int Overall, int? Age, long ValueRaw, string Club,
    string? PortraitPath = null, int? SkinTone = null, int Knowledge = 100,
    string? TransferStatus = null)
{
    public string StatusLabel => TransferStatus switch
    {
        "not-for-sale" => "NOT FOR SALE",
        "listed" => "LISTED",
        "loan-listed" => "LOAN",
        _ => "",
    };
    public bool HasStatus => StatusLabel.Length > 0;
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
}

public sealed record OfferRow(int PlayerId, string Line);

public sealed partial class MarketViewModel : PageViewModel
{
    private static readonly string[] PositionFilters =
        { "All", "GK", "CB", "LB", "RB", "DMF", "CMF", "LMF", "RMF", "AMF", "LWF", "RWF", "SS", "CF" };

    private readonly Session _s;

    public MarketViewModel(Session s)
    {
        _s = s;
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
    [ObservableProperty] private decimal _minRating = 40;
    [ObservableProperty] private bool _freeAgentsOnly;

    public IReadOnlyList<string> ValueCaps { get; } = new[]
        { "Any value", "≤ £100k", "≤ £250k", "≤ £500k", "≤ £1m", "≤ £2m", "≤ £5m", "≤ £10m" };

    [ObservableProperty] private string _valueCap = "Any value";

    public IReadOnlyList<string> SortOptions { get; } = new[]
        { "Best rated", "Most valuable", "Youngest", "Name A–Z" };

    [ObservableProperty] private string _sortBy = "Most valuable";

    partial void OnSearchTextChanged(string value) => Requery();
    partial void OnPositionFilterChanged(string value) => Requery();
    partial void OnMaxAgeChanged(decimal value) => Requery();
    partial void OnMinRatingChanged(decimal value) => Requery();
    partial void OnFreeAgentsOnlyChanged(bool value) => Requery();
    partial void OnValueCapChanged(string value) => Requery();
    partial void OnSortByChanged(string value) => Requery();

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

    private void Requery()
    {
        try { RequeryCore(); }
        catch (Exception ex) { Program.Log("Market.Requery", ex); }
    }

    private void RequeryCore()
    {
        var masterDb = FindMasterDb();
        if (masterDb is null) return;
        using var con = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={masterDb};Mode=ReadOnly");
        con.Open();

        try { WindowLine = _s.TransferWindowLabel(); } catch { WindowLine = ""; }

        Rows.Clear();
        using var cmd = con.CreateCommand();
        var where = new List<string>();
        if (!string.IsNullOrWhiteSpace(SearchText)) where.Add("p.name LIKE $q");
        if (PositionFilter != "All") where.Add("p.position = $pos");
        if (MaxAge < 45) where.Add("COALESCE(p.age, 25) <= $age");
        if (MinRating > 40) where.Add("COALESCE(p.overall_rating, 0) >= $min");
        // The candidate pool is ordered by the chosen sort so "Most valuable" surfaces the world's
        // priciest players, not the highest-rated. A player's club is his ACTUAL team (any league,
        // not just the career divisions) — so the reference world reads as real clubs, and only a
        // genuinely unattached player is a free agent.
        var order = SortBy switch
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
            "(SELECT transfer_status FROM player_market m WHERE m.player_id=p.id) " +
            "FROM players p " +
            (where.Count > 0 ? "WHERE " + string.Join(" AND ", where) + " " : "") +
            "ORDER BY " + order + " LIMIT 4000";
        if (!string.IsNullOrWhiteSpace(SearchText)) cmd.Parameters.AddWithValue("$q", $"%{SearchText.Trim()}%");
        if (PositionFilter != "All") cmd.Parameters.AddWithValue("$pos", PositionFilter);
        if (MaxAge < 45) cmd.Parameters.AddWithValue("$age", (int)MaxAge);
        if (MinRating > 40) cmd.Parameters.AddWithValue("$min", (int)MinRating);

        var cap = CapOf(ValueCap);
        var found = new List<(int Id, string Name, string Pos, int Rating, int? Age, long Value,
            string Club, string? Portrait, int? Skin, string? Status)>();
        using (var r = cmd.ExecuteReader())
        {
            while (r.Read())
            {
                var rating = r.GetInt32(3);
                int? age = r.IsDBNull(4) ? null : r.GetInt32(4);
                var id = r.GetInt32(0);
                var club = r.IsDBNull(7) ? "Free agent" : r.GetString(7);
                if (FreeAgentsOnly && club != "Free agent") continue;
                var value = _s.MarketValueOf(id, rating, age);
                if (value > cap) continue;
                found.Add((id, r.GetString(1), r.GetString(2), rating, age, value, club,
                    r.IsDBNull(5) ? null : r.GetString(5), r.IsDBNull(6) ? null : r.GetInt32(6),
                    r.IsDBNull(8) ? null : r.GetString(8)));
            }
        }
        IEnumerable<(int Id, string Name, string Pos, int Rating, int? Age, long Value,
            string Club, string? Portrait, int? Skin, string? Status)> sorted = SortBy switch
        {
            "Youngest" => found.OrderBy(p => p.Age ?? 99).ThenByDescending(p => p.Rating),
            "Name A–Z" => found.OrderBy(p => p.Name),
            "Best rated" => found.OrderByDescending(p => p.Rating),
            _ => found.OrderByDescending(p => p.Value).ThenByDescending(p => p.Rating),  // Most valuable
        };
        // Knowledge is only looked up for the 300 shown, so the grade masking costs nothing extra.
        foreach (var p in sorted.Take(300))
        {
            var knowledge = KnowledgeSafe(p.Id);
            Rows.Add(new MarketPlayer(p.Id, p.Name, p.Pos, p.Rating, p.Age, p.Value, p.Club,
                p.Portrait, p.Skin, knowledge, p.Status));
        }
    }

    private int KnowledgeSafe(int id)
    {
        try { return _s.FmAttributeMode ? _s.KnowledgeOf(id) : 100; }
        catch { return 100; }
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
    [ObservableProperty] private string _profilePlaystyle = "";
    [ObservableProperty] private Points _profileRadar = new();
    [ObservableProperty] private IReadOnlyList<AbilityEntry> _profileAbilities = Array.Empty<AbilityEntry>();
    [ObservableProperty] private string _profileKnowledgeLine = "";
    [ObservableProperty] private string _profileCoachLine = "";

    partial void OnSelectedPlayerChanged(MarketPlayer? value)
    {
        if (value is null) { HasProfile = false; return; }
        try
        {
            ProfileName = value.Name;
            ProfilePosition = value.Position;
            ProfileGrade = value.Grade;                 // gated letter, never the raw number
            ProfileRatingBrush = value.RatingBrush;
            ProfileFill = Visuals.PositionBrush(value.Position);
            ProfileClub = value.Club;
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
            HasProfile = true;
        }
        catch { HasProfile = false; }
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
        if (SelectedPlayer is null) { SignStatus = "Pick a player first."; return; }
        var pct = SelectedBid.StartsWith("Lowball") ? 85 : SelectedBid.StartsWith("Premium") ? 115 : 100;
        SignStatus = _s.BuyPlayer(SelectedPlayer.Id, pct);
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
        if (SelectedPlayer is null || !Negotiating) return;
        var pctv = _s.DealLikelihood(SelectedPlayer.Id, (long)NegFee, NegSellOn ? 15 : 0, NegInstalments);
        LikelihoodLine = $"Deal likelihood ~{pctv}% · sell-on counts as real money · round talks end at 3";
    }

    [RelayCommand]
    private void OpenTalks()
    {
        if (SelectedPlayer is null) { SignStatus = "Pick a player first."; return; }
        NegLine = _s.StartNegotiation(SelectedPlayer.Id);
        var n = _s.NegotiationFor(SelectedPlayer.Id);
        if (n is null || n.State == "dead") { Negotiating = false; SignStatus = NegLine; return; }
        Negotiating = true;
        DealAgreed = n.State == "agreed";
        NegStance = n.Stance;
        NegFee = n.Ask;
        NegWage = _s.SigningWageDemand(SelectedPlayer.Id, int.Parse(NegYears));
        RefreshLikelihood();
    }

    [RelayCommand]
    private void LoanIn()
    {
        if (SelectedPlayer is null) { SignStatus = "Pick a player first."; return; }
        SignStatus = _s.LoanIn(SelectedPlayer.Id);
        if (SignStatus.StartsWith("Loan DONE")) Requery();
    }

    [RelayCommand]
    private void SendOffer()
    {
        if (SelectedPlayer is null || !Negotiating) return;
        var (msg, agreed, dead) = _s.SendClubOffer(
            SelectedPlayer.Id, (long)NegFee, NegSellOn ? 15 : 0, NegInstalments);
        NegLine = msg;
        DealAgreed = agreed;
        if (dead) Negotiating = false;
        if (!dead && !agreed && _s.NegotiationFor(SelectedPlayer.Id) is { } n)
        {
            NegStance = n.Stance;
            RefreshLikelihood();
        }
    }

    [RelayCommand]
    private void CompleteDeal()
    {
        if (SelectedPlayer is null || !DealAgreed) return;
        SignStatus = _s.CompleteSigning(SelectedPlayer.Id, (long)NegFee, NegSellOn ? 15 : 0,
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
        if (SelectedPlayer is null) return;
        _s.WalkAwayFromNegotiation(SelectedPlayer.Id);
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
