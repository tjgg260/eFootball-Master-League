using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.VisualTree;

namespace ML.App;

/// <summary>
/// The shared right-click vocabulary. One registry builds the same FM-style menu for an
/// entity wherever it is rendered; screens attach it with MlMenu.Attach and pass their own
/// status line + reload so verb results land where that screen already talks.
/// Verbs with engine guards are called and their refusal strings surfaced honestly — the
/// menu pre-disables only what it can know cheaply (scout busy, already captain).
/// </summary>
public static class EntityActions
{
    /// <summary>Build the context menu for an entity. Menus are built fresh per open, so
    /// toggle states (shortlist, transfer list, captain) are always current.</summary>
    /// <summary>Keys a screen can pass in <c>omit</c> when its own extra does the job better
    /// (Tactics' captain verb also moves the armband on the pitch).</summary>
    public const string ItemCaptain = "captain";

    public static ContextMenu BuildMenu(Session s, EntityRef e,
        Action<string>? status = null, Action? refresh = null, IEnumerable<MenuItem>? extras = null,
        params string[] omit)
    {
        var menu = new ContextMenu();
        var items = new List<Control>();
        var skip = new HashSet<string>(omit ?? Array.Empty<string>());

        void Add(string header, Action act, bool enabled = true, string? key = null)
        {
            if (key is not null && skip.Contains(key)) return;
            var mi = new MenuItem { Header = header, IsEnabled = enabled };
            mi.Click += (_, _) =>
            {
                try { act(); refresh?.Invoke(); }
                catch (Exception ex) { status?.Invoke(ex.Message); }
            };
            items.Add(mi);
        }
        void Info(string header) => items.Add(new MenuItem { Header = header, IsEnabled = false });
        void Sep() => items.Add(new Separator());
        void Do(Func<string> verb) { var line = verb(); if (line.Length > 0) status?.Invoke(line); }

        switch (e.Kind)
        {
            case EntityKind.Player: BuildPlayer(s, e, Add, Info, Sep, Do, status); break;
            case EntityKind.Club: BuildClub(s, e, Add, Info, Sep, Do); break;
        }

        if (extras is not null)
        {
            if (items.Count > 0) Sep();
            items.AddRange(extras);
        }

        foreach (var i in items) menu.Items.Add(i);
        return menu;
    }

    private static void BuildPlayer(Session s, EntityRef e,
        AddItem add, Action<string> info, Action sep, Action<Func<string>> run,
        Action<string>? status)
    {
        void Add(string h, Action a, bool en = true, string? key = null) => add(h, a, en, key);
        var id = e.Id;
        var name = e.Name.Length > 0 ? e.Name : s.PlayerNameOf(id);
        var (teamId, club) = s.ClubOfPlayer(id);
        var own = teamId == s.CurrentTeamId;
        var free = teamId is null;

        info($"{name} · {(own ? "your squad" : club)}");
        sep();

        if (own)
        {
            if (teamId is { } tid0)
                Add("👤 View profile", () => Nav.Go("Squad", EntityRef.Player(id, name)));
            var isCaptain = s.Captain == id;
            Add("© Make captain", () => { s.Captain = id; status?.Invoke($"{name} wears the armband."); }, !isCaptain, ItemCaptain);
            Add("📃 Renew contract", () => run(() => s.RenewContract(id)));
            Add("👍 Praise", () => run(() => s.TalkTo(id, name, praise: true)));
            Add("👎 Criticise", () => run(() => s.TalkTo(id, name, praise: false)));
            sep();
            var listed = s.IsTransferListed(id);
            Add(listed ? "📋 Take off the transfer list" : "📋 Transfer-list",
                () => { s.SetTransferListed(id, !listed); status?.Invoke(listed ? $"{name} taken off the list." : $"{name} is on the transfer list."); });
            var loanListed = s.IsLoanListed(id);
            Add(loanListed ? "↔ Take off the loan list" : "↔ Make available on loan",
                () => { s.SetLoanListed(id, !loanListed); status?.Invoke(loanListed ? $"{name} is off the loan list." : $"{name} is available on loan."); });
            Add("📢 Offer to clubs", () => run(() => s.OfferToClubs(id)));
            Add("✈ Loan out", () => run(() => s.LoanOut(id)));
            sep();
            Add("🎯 Set training", () => Nav.Go("Training", EntityRef.Player(id, name)));
            var age = s.PlayerAgeOf(id) ?? 25;
            if (age <= 21 && teamId is { } tid)
            {
                Add("🧒 Move to U21s", () => run(() => s.DemoteToYouth(id, tid, "u21")));
                if (age <= 18) Add("🧒 Move to U18s", () => run(() => s.DemoteToYouth(id, tid, "u18")));
            }
        }
        else
        {
            if (!free)
                Add("👤 View profile", () => Nav.Go("Squad", EntityRef.Player(id, name)));
            Add("🛒 Open in Market", () => Nav.Go("Market", EntityRef.Player(id, name)));
            sep();
            var scoutBusy = s.ActiveScoutJob() is not null;
            var noScout = s.StaffFor("Scout") is null;
            Add(noScout ? "🔍 Scout player — needs a scout" : scoutBusy ? "🔍 Scout player — scout on a mission" : "🔍 Scout player",
                () => run(() => s.StartScoutJob("player", id, name)), !noScout && !scoutBusy);
            if (free)
            {
                Add("🧪 Offer trial", () => run(() => s.TrialPlayer(id)));
            }
            else
            {
                Add("💬 Make enquiry", () => run(() => s.MakeEnquiry(id)));
            }
            var shortlisted = s.IsShortlisted(id);
            Add(shortlisted ? "⭐ Remove from shortlist" : "⭐ Add to shortlist",
                () => { s.SetShortlisted(id, !shortlisted); status?.Invoke(shortlisted ? $"{name} removed from the shortlist." : $"{name} shortlisted."); });
            if (teamId is { } tid)
            {
                sep();
                Add($"🏟 View {club}", () => Nav.Go("Squad", EntityRef.Club(tid, club)));
                var scoutClubLocked = noScout || scoutBusy;
                Add($"🔍 Scout {club}", () => run(() => s.StartScoutJob("club", tid, club)), !scoutClubLocked);
            }
        }
    }

    private delegate void AddItem(string header, Action act, bool enabled = true, string? key = null);

    private static void BuildClub(Session s, EntityRef e,
        AddItem add, Action<string> info, Action sep, Action<Func<string>> run)
    {
        void Add(string h, Action a, bool en = true) => add(h, a, en);
        var tid = (int)e.Id;
        var name = e.Name.Length > 0 ? e.Name : s.TeamName(tid);
        var mine = tid == s.CurrentTeamId;

        info(name);
        sep();
        Add(mine ? "👥 View my squad" : "👥 View squad", () => Nav.Go("Squad", EntityRef.Club(tid, name)));
        if (!mine)
        {
            var scoutBusy = s.ActiveScoutJob() is not null;
            var noScout = s.StaffFor("Scout") is null;
            Add(noScout ? "🔍 Scout club — needs a scout" : scoutBusy ? "🔍 Scout club — scout on a mission" : "🔍 Scout club",
                () => run(() => s.StartScoutJob("club", tid, name)), !noScout && !scoutBusy);
            var (w, d, l) = s.HeadToHead(s.CurrentTeamId, tid);
            info(w + d + l == 0 ? "⚔ Never met competitively" : $"⚔ Head-to-head: W{w} D{d} L{l}");
        }
    }
}

/// <summary>
/// Attaches the shared menu to any list-shaped control: right-click on a row whose
/// DataContext is T selects it (optional) and opens the menu built for it.
/// </summary>
public static class MlMenu
{
    public static void Attach<T>(Control host, Func<T, ContextMenu?> menuFor, Action<T>? select = null)
        where T : class
    {
        host.AddHandler(InputElement.PointerPressedEvent, (_, e) =>
        {
            if (!e.GetCurrentPoint(host).Properties.IsRightButtonPressed) return;
            T? item = null;
            for (Visual? el = e.Source as Visual; el is not null; el = el.GetVisualParent())
            {
                if (el is StyledElement se && se.DataContext is T t) { item = t; break; }
                if (ReferenceEquals(el, host)) break;
            }
            if (item is null) return;
            select?.Invoke(item);
            var menu = menuFor(item);
            if (menu is null || menu.Items.Count == 0) return;
            menu.Placement = PlacementMode.Pointer;
            menu.Open(host);
            e.Handled = true;
        }, RoutingStrategies.Tunnel);
    }
}
