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

    public string Hint => RoleFilled ? "" : $"needs a {RoleNeeded}";
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
        foreach (var (key, label) in Session.Delegations)
            Toggles.Add(new DelegationToggle(s, key, label));
        Reload();
    }

    private static string AttrSummary(StaffPerson p) => p.Role switch
    {
        "Assistant Manager" => $"Tactical {p.Tactical} · Man Mgmt {p.ManManagement} · Coaching {p.Coaching}",
        "Director of Football" => $"Judging {p.JudgingAbility} · Potential {p.JudgingPotential} · Man Mgmt {p.ManManagement}",
        "Coach" or "GK Coach" => $"Coaching {p.Coaching} · Tactical {p.Tactical} · Youth {p.Youth}",
        "Fitness Coach" => $"Fitness {p.Fitness} · Coaching {p.Coaching}",
        "Youth Coach" => $"Youth {p.Youth} · Potential {p.JudgingPotential} · Coaching {p.Coaching}",
        "Physio" => $"Physio {p.Physio} · Fitness {p.Fitness}",
        "Scout" => $"Judging {p.JudgingAbility} · Potential {p.JudgingPotential}",
        "Analyst" => $"Tactical {p.Tactical} · Judging {p.JudgingAbility}",
        _ => "",
    };

    private void Reload()
    {
        Backroom.Clear();
        var mine = _s.MyBackroom().ToDictionary(p => p.Role);
        foreach (var role in Session.StaffRoles)
        {
            Backroom.Add(mine.TryGetValue(role, out var p)
                ? new BackroomCard(p.Id, role, p.Name, $"{p.Age} yrs", new string('★', p.Stars),
                    $"£{p.Wage:N0}/wk", p.StyleLine, AttrSummary(p), true)
                : new BackroomCard(0, role, "— vacant —", "", "", "", "", "", false));
        }
        WageLine = $"Backroom wage bill: £{_s.StaffWages():N0}/week across {mine.Count} of 9 desks";
        ReloadMarket();
    }

    private void ReloadMarket()
    {
        Market.Clear();
        if (SelectedRole is null) return;
        foreach (var p in _s.StaffMarket(SelectedRole))
        {
            Market.Add(new StaffMarketRow(p.Id, p.Name, p.Age.ToString(),
                new string('★', p.Stars), AttrSummary(p), p.StyleLine, $"£{p.Wage:N0}/wk"));
        }
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

    [ObservableProperty]
    private string _status = "Attributes are 1-20, FM-style. Every desk has a real effect: " +
        "Coach 14+ speeds training · Physio shortens layoffs · Youth Coach lifts intakes · " +
        "GK Coach develops keepers · DoF and Scout work the delegations below.";

    partial void OnSelectedRoleChanged(string? value) => ReloadMarket();

    [RelayCommand]
    private void Hire()
    {
        if (SelectedCandidate is null) { Status = "Pick a candidate first."; return; }
        Status = _s.HireStaffPerson(SelectedCandidate.Id);
        Reload();
    }

    [RelayCommand]
    private void Release(BackroomCard card)
    {
        if (!card.Filled) return;
        Status = _s.ReleaseStaff(card.Id);
        Reload();
    }
}
