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

    /// <summary>The bidding verb's key — for the Bidding screen itself, where a row that
    /// navigates to the page you are already on is only a reload.</summary>
    public const string ItemBidding = "bidding";

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

        // THE BUG: building this menu asks the Session about ten separate things — his club,
        // whether he is yours, the armband, both list flags, his age, the scout, the shortlist —
        // and only the transfer window was guarded. One failed read threw straight out of here,
        // up through the right-click handler and into Avalonia's input dispatch, where it showed
        // as a right-click that did nothing at all (or took the window down). Indistinguishable
        // from the feature being broken. Every probe is guarded one by one below; this is the
        // backstop, so whatever HAD been built still reaches the manager as a usable menu.
        try
        {
            switch (e.Kind)
            {
                case EntityKind.Player: BuildPlayer(s, e, Add, Info, Sep, Do, status); break;
                case EntityKind.Club: BuildClub(s, e, Add, Info, Sep, Do); break;
            }
        }
        catch (Exception ex)
        {
            Program.Log($"EntityActions.BuildMenu({e.Kind})", ex);
        }

        if (extras is not null)
        {
            // A screen may carry its own copy of a verb the shared menu has since grown — the
            // Player screen's own "💷 Open bidding" is exactly that, and it was written before
            // this menu had one. Two identical rows in one menu is a fault the user sees, so an
            // extra whose header is already on the menu is dropped and the shared verb stands.
            // The separator is only laid down if something actually survives, or a menu whose
            // extras were all duplicates would end on a hanging line.
            var already = items.OfType<MenuItem>()
                .Select(m => m.Header?.ToString() ?? "")
                .Where(h => h.Length > 0)
                .ToHashSet(StringComparer.Ordinal);
            var keep = extras.Where(m => !already.Contains(m.Header?.ToString() ?? "")).ToList();
            if (keep.Count > 0)
            {
                if (items.Count > 0) Sep();
                items.AddRange(keep);
            }
        }

        foreach (var i in items) menu.Items.Add(i);
        return menu;
    }

    /// <summary>
    /// Every Session read here goes through <see cref="Probe"/>. One of ten failing costs that
    /// one verb its certainty; it never costs the manager the menu.
    /// </summary>
    private static void BuildPlayer(Session s, EntityRef e,
        AddItem add, Action<string> info, Action sep, Action<Func<string>> run,
        Action<string>? status)
    {
        void Add(string h, Action a, bool en = true, string? key = null) => add(h, a, en, key);
        var id = e.Id;
        var name = e.Name.Length > 0 ? e.Name : Probe("PlayerNameOf", () => s.PlayerNameOf(id), "");

        // A read that FAILED and a read that came back "no club" are different answers, and the
        // menu turns on the difference: only a successful (null, "Free agent") is a free agent.
        // If the club read threw we offer the enquiry and never the trial — a trial is a verb
        // that cannot work on a contracted player, and inventing one is worse than omitting it.
        var clubRead = Probe("ClubOfPlayer",
            () => { var (t, c) = s.ClubOfPlayer(id); return (Known: true, TeamId: t, Club: c); },
            (Known: false, TeamId: (int?)null, Club: "club unknown"));
        var teamId = clubRead.TeamId;
        var club = clubRead.Club;
        var free = clubRead.Known && teamId is null;

        // Ownership is asked, not computed here: a lad in your own U21s sits in team 9,000,014,
        // so comparing the raw side id against your club called him a rival's asset and offered
        // you the chance to bid for your own player. IsOwnPlayer walks parent_team_id.
        var own = Probe<bool?>("IsOwnPlayer", () => s.IsOwnPlayer(id), null);
        // That walk costs a second query of its own. If it failed but the club read did not, two
        // of the three answers are still safe to reach without it: a free agent is nobody's, and
        // a man in your senior side is plainly yours. A third club's number is NOT safe — it may
        // be your own U21s, which is the entire reason the walk exists — so that case stays
        // unknown and takes the reduced menu below rather than a guess.
        if (own is null && clubRead.Known)
        {
            if (teamId is null) own = false;
            else if (teamId == s.CurrentTeamId) own = true;
        }

        info($"{name} · {(own == true ? "your squad" : club)}");
        sep();

        if (own is null)
        {
            // Whose player this is came back unreadable, and EVERY verb below turns on the
            // answer: one branch renews his contract, the other bids for him. The one verb that
            // is right either way is a better menu than a guess at the other nine.
            Add("👤 View profile", () => Nav.Go("Player", EntityRef.Player(id, name)));
            return;
        }

        if (own == true)
        {
            // The profile is its own full-width screen now. It used to mean "go to Squad and
            // select his row", which put a man's whole career into a 262px column beside a
            // roster — the one implementation of a profile, for every player in the world.
            Add("👤 View profile", () => Nav.Go("Player", EntityRef.Player(id, name)));
            var isCaptain = Probe("Captain", () => s.Captain, (long?)null) == id;
            Add("© Make captain", () => { s.Captain = id; status?.Invoke($"{name} wears the armband."); }, !isCaptain, ItemCaptain);
            Add("📃 Renew contract", () => run(() => s.RenewContract(id)));
            Add("👍 Praise", () => run(() => s.TalkTo(id, name, praise: true)));
            Add("👎 Criticise", () => run(() => s.TalkTo(id, name, praise: false)));
            sep();
            // Both list flags fall back to "not listed", so a failed read leaves the verb offering
            // to PUT him on the list. Doing that to a man already on it changes nothing; the
            // opposite guess would quietly take him off a list you had deliberately put him on.
            var listed = Probe("IsTransferListed", () => s.IsTransferListed(id), false);
            Add(listed ? "📋 Take off the transfer list" : "📋 Transfer-list",
                () => { s.SetTransferListed(id, !listed); status?.Invoke(listed ? $"{name} taken off the list." : $"{name} is on the transfer list."); });
            var loanListed = Probe("IsLoanListed", () => s.IsLoanListed(id), false);
            Add(loanListed ? "↔ Take off the loan list" : "↔ Make available on loan",
                () => { s.SetLoanListed(id, !loanListed); status?.Invoke(loanListed ? $"{name} is off the loan list." : $"{name} is available on loan."); });
            Add("📢 Offer to clubs", () => run(() => s.OfferToClubs(id)));
            Add("✈ Loan out", () => run(() => s.LoanOut(id)));
            sep();
            Add("🎯 Set training", () => Nav.Go("Training", EntityRef.Player(id, name)));
            // An unreadable age falls back to a settled 25, which offers no youth move at all —
            // the safe direction, because the two verbs below physically move a player between
            // sides and we will not do that on a number we could not read.
            var age = Probe("PlayerAgeOf", () => s.PlayerAgeOf(id), (int?)null) ?? 25;
            if (age <= 21 && teamId is { } tid)
            {
                Add("🧒 Move to U21s", () => run(() => s.DemoteToYouth(id, tid, "u21")));
                if (age <= 18) Add("🧒 Move to U18s", () => run(() => s.DemoteToYouth(id, tid, "u18")));
            }
        }
        else
        {
            // Free agents get a profile too now: the Player screen is one man at a time and
            // needs no club, where the old Squad-focused verb had nothing to select him in.
            Add("👤 View profile", () => Nav.Go("Player", EntityRef.Player(id, name)));

            // Buying him is a screen now, not a 330px rail. Outside the window nothing binding
            // can be agreed, so the verb is not offered then — what IS legal (an enquiry to his
            // club, a trial for a free agent) is right there in this same menu, a line below.
            // A failed read must never silently remove a verb.
            var windowOpen = Probe("TransferWindowOpen", () => s.TransferWindowOpen(), true);
            if (windowOpen)
                Add("💷 Open bidding", () => Nav.Go("Bidding", EntityRef.Player(id, name)),
                    true, ItemBidding);

            Add("🛒 Open in Market", () => Nav.Go("Market", EntityRef.Player(id, name)));
            sep();
            // Both scout gates fall back to OPEN. StartScoutJob re-checks each of them itself and
            // refuses in plain words, so a failed read costs a wasted click and an honest
            // sentence — where guessing "locked" hides a verb that was there for the taking.
            var scoutBusy = Probe("ActiveScoutJob", () => s.ActiveScoutJob() is not null, false);
            var noScout = Probe("StaffFor(Scout)", () => s.StaffFor("Scout") is null, false);
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
            var shortlisted = Probe("IsShortlisted", () => s.IsShortlisted(id), false);
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
        var name = e.Name.Length > 0 ? e.Name : Probe("TeamName", () => s.TeamName(tid), "?");
        var mine = tid == s.CurrentTeamId;

        info(name);
        sep();
        Add(mine ? "👥 View my squad" : "👥 View squad", () => Nav.Go("Squad", EntityRef.Club(tid, name)));
        if (!mine)
        {
            var scoutBusy = Probe("ActiveScoutJob", () => s.ActiveScoutJob() is not null, false);
            var noScout = Probe("StaffFor(Scout)", () => s.StaffFor("Scout") is null, false);
            Add(noScout ? "🔍 Scout club — needs a scout" : scoutBusy ? "🔍 Scout club — scout on a mission" : "🔍 Scout club",
                () => run(() => s.StartScoutJob("club", tid, name)), !noScout && !scoutBusy);
            // A head-to-head we could not read is left OFF the menu entirely. "Never met
            // competitively" is a claim about the club's history, and printing it because a
            // query failed invents a fact rather than admitting a gap.
            var h2h = Probe("HeadToHead",
                () => { var (w, d, l) = s.HeadToHead(s.CurrentTeamId, tid); return (Known: true, W: w, D: d, L: l); },
                (Known: false, W: 0, D: 0, L: 0));
            if (h2h.Known)
            {
                info(h2h.W + h2h.D + h2h.L == 0
                    ? "⚔ Never met competitively"
                    : $"⚔ Head-to-head: W{h2h.W} D{h2h.D} L{h2h.L}");
            }
        }
    }

    /// <summary>
    /// One Session read, plus what to believe when it fails. Every fallback in this file is
    /// picked so the wrong answer is the harmless one: a verb offered and then refused in words
    /// beats a verb that silently vanishes, and a flag guessed "off" beats one guessed "on"
    /// wherever acting on it writes to the career.
    /// </summary>
    private static T Probe<T>(string what, Func<T> read, T fallback)
    {
        try { return read(); }
        catch (Exception ex)
        {
            Program.Log($"EntityActions probe: {what}", ex);
            return fallback;
        }
    }
}

/// <summary>
/// Row gestures for any list-shaped control. Right-click on a row whose DataContext is T
/// selects it (optional) and opens the menu built for it; double-click opens it. Both resolve
/// the row through the same walk, so the menu and the double-click can never act on different
/// players.
/// </summary>
public static class MlMenu
{
    /// <summary>
    /// The nearest thing under a click that IS a T — the row the gesture is about. Every
    /// affordance on a list resolves its subject through this one walk (right-click, and
    /// double-click-to-open), so they can never disagree about which player was hit.
    /// </summary>
    public static T? RowAt<T>(object? source, Control? stopAt = null) where T : class
    {
        for (Visual? el = source as Visual; el is not null; el = el.GetVisualParent())
        {
            if (el is StyledElement se && se.DataContext is T t) return t;
            if (ReferenceEquals(el, stopAt)) break;
        }
        return null;
    }

    /// <summary>
    /// Double-click a row to OPEN it. Bubbling, and it never touches selection: a double-click
    /// is two single clicks first, so the list has already selected the row by the time this
    /// runs — the single-click select and the right-click menu are both left exactly as they
    /// were. Same gesture the touchline strip uses to bring a substitute on.
    /// </summary>
    public static void OnDoubleClick<T>(Control host, Action<T> open) where T : class
    {
        host.AddHandler(Gestures.DoubleTappedEvent,
            new EventHandler<TappedEventArgs>((_, e) =>
            {
                // Guarded for the same reason Attach is: `open` is a screen's own callback and
                // usually a Nav.Go, so it can throw for every reason a page build can. Unhandled
                // here it is an exception raised inside input dispatch, not a failed navigation.
                try
                {
                    if (RowAt<T>(e.Source, host) is not { } row) return;
                    open(row);
                    e.Handled = true;
                }
                catch (Exception ex)
                {
                    Program.Log($"MlMenu.OnDoubleClick<{typeof(T).Name}>", ex);
                }
            }), RoutingStrategies.Bubble);
    }

    public static void Attach<T>(Control host, Func<T, ContextMenu?> menuFor, Action<T>? select = null)
        where T : class
    {
        host.AddHandler(InputElement.PointerPressedEvent, (_, e) =>
        {
            // THE BUG: this handler ran naked. menuFor reaches EntityActions.BuildMenu, which
            // interrogates the Session about a dozen things before a single row exists, and a
            // throw from any of them landed unhandled on the UI thread mid-input-dispatch — so
            // the right-click did nothing, or the app went down. Both read as "the menu feature
            // is broken" rather than "one read failed", and this one handler is wired to every
            // list in the app. It fails soft now, and the reason lands in ml-crash.log.
            try
            {
                if (!e.GetCurrentPoint(host).Properties.IsRightButtonPressed) return;
                var item = RowAt<T>(e.Source, host);
                if (item is null) return;
                select?.Invoke(item);
                var menu = menuFor(item);
                if (menu is null || menu.Items.Count == 0) return;
                menu.Placement = PlacementMode.Pointer;
                menu.Open(host);
                e.Handled = true;
            }
            catch (Exception ex)
            {
                Program.Log($"MlMenu.Attach<{typeof(T).Name}>", ex);
            }
        }, RoutingStrategies.Tunnel);
    }
}
