using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public sealed record StaffRow(string Role, string Name, string Stars, string Wage, bool Filled);

public sealed record StaffCandidateRow(StaffMember Member, string Line);

/// <summary>The backroom: current staff per role + candidates to hire (FM phase A1).</summary>
public sealed partial class StaffViewModel : PageViewModel
{
    private readonly Session _s;

    public StaffViewModel(Session s)
    {
        _s = s;
        foreach (var r in Session.StaffRoles) RoleOptions.Add(r);
        SelectedRole = RoleOptions.FirstOrDefault();
        Reload();
    }

    private void Reload()
    {
        Rows.Clear();
        foreach (var role in Session.StaffRoles)
        {
            var m = _s.StaffFor(role);
            Rows.Add(m is null
                ? new StaffRow(role, "— vacant —", "", "", false)
                : new StaffRow(role, m.Name, new string('★', m.Quality), $"£{m.Wage:N0}/wk", true));
        }
        ReloadCandidates();
    }

    private void ReloadCandidates()
    {
        Candidates.Clear();
        if (SelectedRole is null) return;
        foreach (var c in _s.StaffCandidates(SelectedRole))
        {
            Candidates.Add(new StaffCandidateRow(c,
                $"{c.Name}  {new string('★', c.Quality)}  £{c.Wage:N0}/wk"));
        }
        SelectedCandidate = Candidates.FirstOrDefault();
    }

    public override string Title => "Staff";
    public override string Icon => "🧑‍💼";

    public ObservableCollection<StaffRow> Rows { get; } = new();
    public ObservableCollection<string> RoleOptions { get; } = new();
    public ObservableCollection<StaffCandidateRow> Candidates { get; } = new();

    [ObservableProperty] private string? _selectedRole;
    [ObservableProperty] private StaffCandidateRow? _selectedCandidate;

    [ObservableProperty]
    private string _status = "Coach 4★+ speeds up training · Physio 3★+ shortens injuries · " +
                             "the Assistant explains XI picks · the Scout unlocks reports.";

    partial void OnSelectedRoleChanged(string? value) => ReloadCandidates();

    [RelayCommand]
    private void Hire()
    {
        if (SelectedCandidate is null) { Status = "Pick a candidate first."; return; }
        Status = _s.HireStaff(SelectedCandidate.Member);
        Reload();
    }

    [RelayCommand]
    private void Fire()
    {
        if (SelectedRole is null) return;
        Status = _s.FireStaff(SelectedRole);
        Reload();
    }
}
