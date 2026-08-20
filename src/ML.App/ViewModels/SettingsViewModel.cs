using System.Collections.ObjectModel;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- Settings: display, realism, matchday, world and data care-taking -------------

public sealed partial class SettingsViewModel : PageViewModel
{
    private readonly Session _s;

    public SettingsViewModel(Session s)
    {
        _s = s;
        _steamRoot = s.GetSetting("steam_root") ?? ScoreImport.SteamRoot;
        _steamUserId = s.GetSetting("steam_user_id") ?? ScoreImport.SteamUserId;
        _fmAttributes = s.FmAttributeMode;
        _selectedSkin = s.GetSetting("ui_skin") ?? "Midnight";
        _maskStrict = s.GetSetting("mask_strict") ?? "Standard";
        _transferDifficulty = s.GetSetting("transfer_difficulty") ?? "Normal";
        _injuryFreq = s.GetSetting("injury_freq") ?? "Normal";
        _sackLeniency = s.GetSetting("sack_leniency") ?? "Normal";
        _autoBoot = s.GetSetting("auto_boot") != "0";
        _realNames = s.GetSetting("real_names") != "0";
        WorldSeedLine = $"World seed: {s.WorldSeed} (this career's universe — unique per save)";
        LoadBackups();
    }

    public override string Title => "Settings";
    public override string Icon => "⚙️";

    // ---------------------------------------------------------------- display / skins

    public IReadOnlyList<string> Skins { get; } = Theme.Skins.Select(sk => sk.Name).ToList();
    [ObservableProperty] private string _selectedSkin;
    partial void OnSelectedSkinChanged(string value)
    {
        _s.SetSetting("ui_skin", value);
        Theme.Apply(value, _s.PrimaryColor);
        Status = $"Skin: {value}. (Full per-screen theming lands with the design-polish pass.)";
    }

    [ObservableProperty] private bool _fmAttributes;
    partial void OnFmAttributesChanged(bool value)
    {
        _s.FmAttributeMode = value;
        Status = value
            ? "FM view ON — colour bands (red poor · amber average · green good · blue elite), " +
              "unscouted players hidden. Reports stay on."
            : "FM view OFF — raw attribute numbers everywhere.";
    }

    // ---------------------------------------------------------------- realism

    public IReadOnlyList<string> MaskOptions { get; } = new[] { "Relaxed", "Standard", "Strict" };
    [ObservableProperty] private string _maskStrict;
    partial void OnMaskStrictChanged(string value) =>
        Save("mask_strict", value, "Masking strictness — how much you know of unscouted players.");

    public IReadOnlyList<string> DifficultyOptions { get; } = new[] { "Easy", "Normal", "Hard" };
    [ObservableProperty] private string _transferDifficulty;
    partial void OnTransferDifficultyChanged(string value) =>
        Save("transfer_difficulty", value, "Transfer difficulty — how hard selling clubs ask.");

    public IReadOnlyList<string> InjuryOptions { get; } = new[] { "Low", "Normal", "High" };
    [ObservableProperty] private string _injuryFreq;
    partial void OnInjuryFreqChanged(string value) =>
        Save("injury_freq", value, "Injury frequency across the world.");

    public IReadOnlyList<string> SackOptions { get; } = new[] { "Patient", "Normal", "Ruthless" };
    [ObservableProperty] private string _sackLeniency;
    partial void OnSackLeniencyChanged(string value) =>
        Save("sack_leniency", value, "Board patience before the axe falls.");

    // ---------------------------------------------------------------- matchday / world

    [ObservableProperty] private bool _autoBoot;
    partial void OnAutoBootChanged(bool value)
    {
        _s.SetSetting("auto_boot", value ? "1" : "0");
        MatchLauncher.AutoBoot = value;
        Status = value ? "Play Match boots eFootball automatically." : "Play Match compiles only — you boot the game.";
    }

    [ObservableProperty] private bool _realNames;
    partial void OnRealNamesChanged(bool value) =>
        Save("real_names", value ? "1" : "0",
            "Real club names in-game (applies on the next Play Match compile).");

    public string WorldSeedLine { get; }

    // ---------------------------------------------------------------- OCR paths

    [ObservableProperty] private string _steamRoot;
    [ObservableProperty] private string _steamUserId;

    [RelayCommand]
    private void SaveSettings()
    {
        _s.SetSetting("steam_root", SteamRoot.Trim());
        _s.SetSetting("steam_user_id", SteamUserId.Trim());
        ScoreImport.SteamRoot = SteamRoot.Trim();
        ScoreImport.SteamUserId = SteamUserId.Trim();
        Status = "Saved — the next 📷 Import uses these paths.";
    }

    // ---------------------------------------------------------------- data care-taking

    public ObservableCollection<string> Backups { get; } = new();
    [ObservableProperty] private string? _selectedBackup;

    private string? BackupsDir()
    {
        var src = _s.Db.Connection.DataSource;
        return string.IsNullOrEmpty(src) ? null : Path.Combine(Path.GetDirectoryName(src)!, "backups");
    }

    private void LoadBackups()
    {
        Backups.Clear();
        var dir = BackupsDir();
        if (dir is null || !Directory.Exists(dir)) return;
        foreach (var f in new DirectoryInfo(dir).GetFiles("*.db")
                     .OrderByDescending(f => f.LastWriteTime).Take(10))
        {
            Backups.Add(f.Name);
        }
    }

    [RelayCommand]
    private void BackupNow()
    {
        try
        {
            _s.BackupCareer();
            LoadBackups();
            Status = "Backup taken — the newest five are kept in build/backups.";
        }
        catch (Exception ex) { Status = $"Backup failed: {ex.Message}"; }
    }

    [RelayCommand]
    private void RestoreBackup()
    {
        if (SelectedBackup is null) { Status = "Pick a backup first."; return; }
        try
        {
            var dir = BackupsDir()!;
            var src = Path.Combine(dir, SelectedBackup);
            var pending = Path.Combine(Path.GetDirectoryName(dir)!, "master.restore.db");
            File.Copy(src, pending, overwrite: true);
            Status = $"Restore staged from {SelectedBackup} — CLOSE and reopen the app to apply. " +
                     "(The current career is replaced at next launch.)";
        }
        catch (Exception ex) { Status = $"Restore failed: {ex.Message}"; }
    }

    // ---------------------------------------------------------------- shared

    [ObservableProperty]
    private string _status =
        "Everything here saves instantly to the career. Skins recolour the app chrome; realism " +
        "options bite from the next matchday.";

    private void Save(string key, string value, string what)
    {
        _s.SetSetting(key, value);
        Status = $"{what}  →  {value}.";
    }
}
