using System.Collections.ObjectModel;
using Avalonia.Controls;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

/// <summary>
/// Stable, name-keyed avatar brush for people who will never have portrait art (staff,
/// chairmen). Deterministic hash so the same person keeps the same colour across runs.
/// Belongs in Visuals eventually; lives here until that file is open for edits.
/// </summary>
internal static class NameAvatar
{
    private static readonly string[] Palette =
    {
        "#3E7CB1", "#7A5FA0", "#2E8F83", "#B3703C",
        "#4E8A3C", "#A8556E", "#5C6DBF", "#8A7A2E",
    };

    public static Avalonia.Media.IBrush For(string name)
    {
        var h = 0;
        foreach (var c in name) h = (h * 31 + c) & 0x7FFFFFFF;
        return Visuals.Brush(Palette[h % Palette.Length]);
    }
}

public sealed record BackroomCard(
    long Id, string Role, string Name, string AgeLine, string Stars, string Wage,
    string StyleLine, string AttrLine, bool Filled, string ContractLine = "")
{
    /// <summary>Release is a two-step confirm — the label carries the arm state per desk.</summary>
    public const string ReleaseIdle = "⛔ Release";
    public const string ReleaseArm = "⛔ Sure?";

    // No staff photos exist anywhere in the pipeline — the initials avatar IS the treatment.
    public Avalonia.Media.IBrush AvatarBrush => NameAvatar.For(Name);
    public string Mark => Filled ? Visuals.Initials(Name) : "";
    public string ReleaseLabel { get; init; } = ReleaseIdle;
}

public sealed record StaffMarketRow(
    long Id, string Name, string Age, string Stars, string KeyAttrs, string Style, string Wage)
{
    public Avalonia.Media.IBrush AvatarBrush => NameAvatar.For(Name);
    public string Mark => Visuals.Initials(Name);
}

public sealed partial class DelegationToggle : ObservableObject
{
    private readonly Session _s;
    public string Key { get; }
    public string Label { get; }
    public string RoleNeeded { get; }
    public bool RoleFilled { get; }

    public DelegationToggle(Session s, string key, string label)
    {
        _s = s;
        Key = key;
        Label = label;
        RoleNeeded = Session.DelegationRole(key);
        RoleFilled = s.StaffPersonFor(RoleNeeded) is not null;
        _isOn = s.DelegationOn(key);
        // The one duty with a standing caveat: an XI you picked by hand outranks the assistant,
        // so the weekly pass leaves it alone. Said here rather than left for you to infer from a
        // team sheet that never changes. (Not yet bound in StaffView.axaml — the layout of that
        // panel belongs to another pass; the letter in the inbox carries it in the meantime.)
        Note = key == "delegate_xi" && _isOn && RoleFilled && s.ManualXi
            ? "holding — you picked this XI by hand, and he will not overwrite it"
            : "";
    }

    [ObservableProperty] private bool _isOn;
    partial void OnIsOnChanged(bool value) => _s.SetDelegation(Key, value);

    /// <summary>A live caveat about this duty, or empty when it simply runs.</summary>
    public string Note { get; }
    public bool HasNote => Note.Length > 0;

    public string Hint => RoleFilled ? "" : $"needs {("AEIOU".Contains(RoleNeeded[0]) ? "an" : "a")} {RoleNeeded}";

    /// <summary>The hint as an offer of help: clicking it aims the market at the empty desk.</summary>
    public string HintLink => RoleFilled ? "" : $"{Hint} — browse candidates →";
}

/// <summary>The staff database: your backroom, the market per role, and delegation.</summary>
public sealed partial class StaffViewModel : PageViewModel
{
    private readonly Session _s;

    public StaffViewModel(Session s)
    {
        _s = s;
        s.EnsureStaffPool();
        foreach (var r in Session.StaffRoles) RoleOptions.Add(r);
        SelectedRole = RoleOptions.FirstOrDefault();
        Reload();
    }

    /// <summary>Five-slot star line, Academy-style: ★ filled, ☆ padding (P6).</summary>
    private static string StarLine(int stars)
    {
        var n = Math.Clamp(stars, 0, 5);
        return new string('★', n) + new string('☆', 5 - n);
    }

    // A 1-20 attribute as a word (UX P4): the desk card reads like a reference, not a spreadsheet.
    private static string Word(int v) => v switch
    {
        >= 17 => "elite", >= 14 => "excellent", >= 11 => "good", >= 8 => "average", _ => "weak",
    };

    private static string AttrSummary(StaffPerson p) => p.Role switch
    {
        "Assistant Manager" => $"{Word(p.Tactical)} tactically · {Word(p.ManManagement)} man-manager · {Word(p.Coaching)} coach",
        "Director of Football" => $"{Word(p.JudgingAbility)} judge of ability · {Word(p.JudgingPotential)} eye for potential · {Word(p.ManManagement)} man-manager",
        "Coach" or "GK Coach" => $"{Word(p.Coaching)} coach · {Word(p.Tactical)} tactically · {Word(p.Youth)} with youngsters",
        "Fitness Coach" => $"{Word(p.Fitness)} conditioner · {Word(p.Coaching)} coach",
        "Youth Coach" => $"{Word(p.Youth)} with youngsters · {Word(p.JudgingPotential)} eye for potential · {Word(p.Coaching)} coach",
        "Physio" => $"{Word(p.Physio)} physio · {Word(p.Fitness)} conditioner",
        "Scout" => $"{Word(p.JudgingAbility)} judge of ability · {Word(p.JudgingPotential)} eye for potential",
        "Analyst" => $"{Word(p.Tactical)} tactically · {Word(p.JudgingAbility)} judge of ability",
        _ => "",
    };

    /// <summary>
    /// The whole 1-20 sheet, in the same words the desk cards use. The staff database stores
    /// eight attributes but only the role-relevant two or three ever reached the screen — this
    /// is the missing profile, surfaced where you actually decide: the right-click on a candidate.
    /// </summary>
    private static readonly (string Label, Func<StaffPerson, int> Value)[] AttrFields =
    {
        ("Coaching", p => p.Coaching),
        ("Working with youngsters", p => p.Youth),
        ("Fitness", p => p.Fitness),
        ("Physiotherapy", p => p.Physio),
        ("Judging ability", p => p.JudgingAbility),
        ("Judging potential", p => p.JudgingPotential),
        ("Tactical knowledge", p => p.Tactical),
        ("Man management", p => p.ManManagement),
    };

    /// <summary>Top style strengths, e.g. "Overload · Quick Counter" — the styles he drills best.</summary>
    private static string StylesSummary(StaffPerson p) =>
        string.Join(" · ", p.StyleStrengths.Take(3).Select(s => s.Style));

    /// <summary>
    /// "under contract to 2029" — ContractUntil is a season id, turned into a calendar year the
    /// same way the rest of the app does it (no base-year literals: offset from this season).
    /// </summary>
    private string ContractLineFor(StaffPerson p)
    {
        if (p.ContractUntil is not { } until) return "no fixed term";
        var year = _s.SeasonYear + (until - _s.SeasonId);
        return until <= _s.SeasonId
            ? $"contract expires this summer ({year}) — renew or lose him"
            : $"under contract to {year}";
    }

    private void Reload()
    {
        _releaseArmedId = 0;   // rebuilt cards come back disarmed
        Backroom.Clear();
        var mine = _s.MyBackroom().ToDictionary(p => p.Role);
        foreach (var role in Session.StaffRoles)
        {
            Backroom.Add(mine.TryGetValue(role, out var p)
                ? new BackroomCard(p.Id, role, p.Name, $"{p.Age} yrs", StarLine(p.Stars),
                    $"£{p.Wage:N0}/wk", $"prefers {p.PrefFormation} · {StylesSummary(p)}",
                    AttrSummary(p), true, ContractLineFor(p))
                : new BackroomCard(0, role, "— vacant —", "", "", "", "", "", false));
        }
        WageLine = $"Backroom wage bill: £{_s.StaffWages():N0}/week across {mine.Count} of 9 desks";

        // Toggles snapshot RoleFilled/Hint at construction, so rebuild them on every
        // reload — hiring or releasing a desk must refresh hints and enablement (P6).
        Toggles.Clear();
        foreach (var (key, label) in Session.Delegations)
            Toggles.Add(new DelegationToggle(_s, key, label));

        ReloadMarket();
    }

    private void ReloadMarket()
    {
        Market.Clear();
        _marketPeople.Clear();
        if (SelectedRole is not null)
        {
            foreach (var p in _s.StaffMarket(SelectedRole))
            {
                _marketPeople[p.Id] = p;   // the row is a summary; the menu needs the whole person
                Market.Add(new StaffMarketRow(p.Id, p.Name, p.Age.ToString(),
                    StarLine(p.Stars), AttrSummary(p),
                    $"prefers {p.PrefFormation} · {StylesSummary(p)}", $"£{p.Wage:N0}/wk"));
            }
        }
        HasMarket = Market.Count > 0;
        SelectedCandidate = Market.FirstOrDefault();
    }

    public override string Title => "Staff";
    public override string Icon => "🧑‍💼";

    public ObservableCollection<BackroomCard> Backroom { get; } = new();
    public ObservableCollection<string> RoleOptions { get; } = new();
    public ObservableCollection<StaffMarketRow> Market { get; } = new();
    public ObservableCollection<DelegationToggle> Toggles { get; } = new();

    /// <summary>The full people behind the market rows, keyed by id — the menu's source.</summary>
    private readonly Dictionary<long, StaffPerson> _marketPeople = new();

    [ObservableProperty] private string? _selectedRole;
    [ObservableProperty] private StaffMarketRow? _selectedCandidate;
    [ObservableProperty] private string _wageLine = "";
    [ObservableProperty] private bool _hasMarket;

    [ObservableProperty]
    private string _status = "Every desk has a real effect: an excellent Coach speeds training · " +
        "Physio shortens layoffs · Youth Coach lifts intakes · GK Coach develops keepers · " +
        "Assistant, DoF, Scout and Fitness Coach work the delegations below. " +
        "Right-click a candidate for his full 1-20 sheet beside the man he would replace.";

    partial void OnSelectedRoleChanged(string? value) => ReloadMarket();

    [RelayCommand]
    private void Hire()
    {
        if (SelectedCandidate is null) { Status = "Pick a candidate first."; return; }
        Status = _s.HireStaffPerson(SelectedCandidate.Id);
        Reload();
    }

    // Clicking a desk card points the market picker at that desk's role (P6) — the
    // natural next move on a vacant desk is "show me who I could hire for it".
    [RelayCommand]
    private void SelectDesk(BackroomCard card)
    {
        // Moving your attention to a DIFFERENT desk resets a primed release, exactly as
        // changing the selection does on the squad screen. Re-clicking the armed card doesn't.
        if (_releaseArmedId != card.Id) ArmRelease(0);
        AimAtRole(card.Role);
    }

    /// <summary>Point the market picker at a role. Shared by the desk cards and the
    /// delegation hints — "needs a Scout" is a link to the Scout market, not a dead label.</summary>
    [RelayCommand]
    private void AimAtRole(string role)
    {
        if (role.Length == 0) return;
        SelectedRole = role;
        Status = $"Staff market: {role}.";
    }

    [RelayCommand]
    private void Renew(BackroomCard card)
    {
        if (!card.Filled) return;
        ArmRelease(0);
        Status = _s.RenewStaffContract(card.Id);
        Reload();
    }

    // --- release: two-step, because a desk you empty is a desk your rivals can fill ------
    private long _releaseArmedId;

    [RelayCommand]
    private void Release(BackroomCard card)
    {
        if (!card.Filled) return;
        if (_releaseArmedId != card.Id)
        {
            ArmRelease(card.Id);
            Status = $"Release {card.Name} ({card.Role})? Click again to confirm.";
            return;
        }
        ArmRelease(0);
        Status = _s.ReleaseStaff(card.Id);
        Reload();
    }

    /// <summary>Arm exactly one desk (0 = none) by re-stamping the cards' button labels.</summary>
    private void ArmRelease(long id)
    {
        _releaseArmedId = id;
        for (var i = 0; i < Backroom.Count; i++)
        {
            var want = id != 0 && Backroom[i].Id == id
                ? BackroomCard.ReleaseArm : BackroomCard.ReleaseIdle;
            if (Backroom[i].ReleaseLabel != want)
                Backroom[i] = Backroom[i] with { ReleaseLabel = want };
        }
    }

    // --- the candidate menu: hire, the full 1-20 sheet, and the man he'd replace --------

    /// <summary>
    /// Right-click on a market candidate. Hand-built rather than EntityActions: staff are not
    /// players or clubs, and the payload here is the attribute profile that has no screen of
    /// its own. Info rows are disabled MenuItems — the same chrome, read-only.
    /// </summary>
    public ContextMenu? MenuFor(StaffMarketRow row)
    {
        if (!_marketPeople.TryGetValue(row.Id, out var p)) return null;

        var menu = new ContextMenu();
        void Info(string header) => menu.Items.Add(new MenuItem { Header = header, IsEnabled = false });
        void Sep() => menu.Items.Add(new Separator());

        Info($"{p.Name} · {p.Age} · {p.Role}");
        Sep();

        var hire = new MenuItem { Header = $"✒ Hire {p.Name}" };
        hire.Click += (_, _) =>
        {
            SelectedCandidate = row;
            Hire();
        };
        menu.Items.Add(hire);

        // The man already at the desk, fetched BEFORE the sheet is drawn so every attribute row
        // can carry the comparison. Hiring releases him, and that is a decision you cannot take
        // back from a screen that only showed you the newcomer.
        StaffPerson? incumbent = null;
        try { incumbent = _s.StaffPersonFor(p.Role); } catch { /* the comparison is additive */ }
        if (incumbent is not null && incumbent.Id == p.Id) incumbent = null;

        if (incumbent is not null)
        {
            Info($"   ⚠ that releases {incumbent.Name}, who holds this desk");
        }
        Sep();

        // The real 1-20 values, not just the adjective. Two people can both be "good" four points
        // apart, which is the whole of the decision — the word alone hid it. The word stays
        // because it is how the rest of the screen reads; the number is what you compare.
        Info(incumbent is null
            ? "ATTRIBUTES · 1-20"
            : $"ATTRIBUTES · 1-20 · {p.Name} vs {incumbent.Name}");
        foreach (var (label, value) in AttrFields)
        {
            var mine = value(p);
            if (incumbent is null)
            {
                Info($"{label} · {mine}  {Word(mine)}");
                continue;
            }
            var his = value(incumbent);
            var arrow = mine > his ? "▲" : mine < his ? "▼" : "=";
            Info($"{label} · {mine}  {Word(mine)}   {arrow} {his}");
        }
        Sep();
        Info($"{StarLine(p.Stars)} · £{p.Wage:N0}/wk");
        Info($"prefers {p.PrefFormation} · drills {StylesSummary(p)}");
        if (incumbent is not null)
        {
            Info($"⚖ {incumbent.Name} ({incumbent.Age}) · {StarLine(incumbent.Stars)} · " +
                 $"£{incumbent.Wage:N0}/wk · {ContractLineFor(incumbent)}");
            Info($"   prefers {incumbent.PrefFormation} · drills {StylesSummary(incumbent)}");
        }
        return menu;
    }
}
