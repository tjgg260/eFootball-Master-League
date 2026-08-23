using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public sealed record BackroomCard(
    long Id, string Role, string Name, string AgeLine, string Stars, string Wage,
    string StyleLine, string AttrLine, bool Filled);

public sealed record StaffMarketRow(
    long Id, string Name, string Age, string Stars, string KeyAttrs, string Style, string Wage);

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
    }

    [ObservableProperty] private bool _isOn;
    partial void OnIsOnChanged(bool value) => _s.SetDelegation(Key, value);

    public string Hint => RoleFilled ? "" : $"needs {("AEIOU".Contains(RoleNeeded[0]) ? "an" : "a")} {RoleNeeded}";
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

    /// <summary>Top style strengths, e.g. "Overload · Quick Counter" — the styles he drills best.</summary>
    private static string StylesSummary(StaffPerson p) =>
        string.Join(" · ", p.StyleStrengths.Take(3).Select(s => s.Style));

    private void Reload()
    {
        Backroom.Clear();
        var mine = _s.MyBackroom().ToDictionary(p => p.Role);
        foreach (var role in Session.StaffRoles)
        {
            Backroom.Add(mine.TryGetValue(role, out var p)
                ? new BackroomCard(p.Id, role, p.Name, $"{p.Age} yrs", StarLine(p.Stars),
                    $"£{p.Wage:N0}/wk", $"prefers {p.PrefFormation} · {StylesSummary(p)}",
                    AttrSummary(p), true)
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
        if (SelectedRole is not null)
        {
            foreach (var p in _s.StaffMarket(SelectedRole))
            {
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

    [ObservableProperty] private string? _selectedRole;
    [ObservableProperty] private StaffMarketRow? _selectedCandidate;
    [ObservableProperty] private string _wageLine = "";
    [ObservableProperty] private bool _hasMarket;

    [ObservableProperty]
    private string _status = "Every desk has a real effect: an excellent Coach speeds training · " +
        "Physio shortens layoffs · Youth Coach lifts intakes · GK Coach develops keepers · " +
        "DoF and Scout work the delegations below.";

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
    private void SelectDesk(BackroomCard card) => SelectedRole = card.Role;

    [RelayCommand]
    private void Release(BackroomCard card)
    {
        if (!card.Filled) return;
        Status = _s.ReleaseStaff(card.Id);
        Reload();
    }
}
