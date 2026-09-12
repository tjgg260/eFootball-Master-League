using System.Collections.ObjectModel;
using System.IO;
using Avalonia.Threading;
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
        _managerName = s.ManagerName;
        _recordMatches = s.GetSetting("record_matches") == "1";
        _obsUrl = s.GetSetting("obs_url") ?? VideoCapture.ObsUrl;
        _obsPassword = s.GetSetting("obs_password") ?? "";
        _ffmpegPath = s.GetSetting("ffmpeg_path") ?? "ffmpeg";
        _videoDir = s.GetSetting("video_dir") ?? "";
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
        // Honest scope: the skin swaps the Theme* dynamic brushes (window ground, nav rail,
        // nav hover, accent). Panels/cards/text now sit on the fixed Ml* palette.
        Status = $"Skin: {value} — recolours the window ground, nav and accent. " +
                 "Panels and text keep the app palette.";
        FlashSaved();
    }

    [ObservableProperty] private bool _fmAttributes;
    partial void OnFmAttributesChanged(bool value)
    {
        _s.FmAttributeMode = value;
        Status = value
            ? "FM view ON — colour bands (red poor · amber average · green good · blue elite), " +
              "unscouted players hidden. Reports stay on."
            : "FM view OFF — raw attribute numbers everywhere.";
        FlashSaved();
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
        FlashSaved();
    }

    [ObservableProperty] private bool _realNames;
    partial void OnRealNamesChanged(bool value) =>
        Save("real_names", value ? "1" : "0",
            "Real club names in-game (applies on the next Play Match compile).");

    public string WorldSeedLine { get; }

    // ---------------------------------------------------------------- match video (OBS + ffmpeg)

    [ObservableProperty] private bool _recordMatches;
    partial void OnRecordMatchesChanged(bool value)
    {
        _s.SetSetting("record_matches", value ? "1" : "0");
        VideoCapture.RecordMatches = value;
        Status = value
            ? "Matches record via OBS (needs OBS running with WebSocket server on). Analyse from the Dashboard."
            : "Match recording off.";
        FlashSaved();
    }

    // Text fields autosave as they change (a tiny settings write per edit) — no Save button,
    // no "did I save?" ambiguity. The quiet "Saved." flash confirms each persist.

    [ObservableProperty] private string _obsUrl;
    partial void OnObsUrlChanged(string value)
    {
        _s.SetSetting("obs_url", value.Trim());
        VideoCapture.ObsUrl = value.Trim();
        FlashSaved();
    }

    [ObservableProperty] private string _obsPassword;
    partial void OnObsPasswordChanged(string value)
    {
        _s.SetSetting("obs_password", value.Trim());
        VideoCapture.ObsPassword = value.Trim();
        FlashSaved();
    }

    [ObservableProperty] private string _ffmpegPath;
    partial void OnFfmpegPathChanged(string value)
    {
        _s.SetSetting("ffmpeg_path", value.Trim());
        VideoCapture.FfmpegPath = value.Trim();
        FlashSaved();
    }

    [ObservableProperty] private string _videoDir;
    partial void OnVideoDirChanged(string value)
    {
        _s.SetSetting("video_dir", value.Trim());
        VideoCapture.VideoDir = value.Trim();
        FlashSaved();
    }

    [ObservableProperty] private string _managerName;
    partial void OnManagerNameChanged(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return;
        _s.ManagerName = value;
        Status = $"You are {_s.ManagerName} — the press and the board use this name.";
        FlashSaved();
    }

    // ---------------------------------------------------------------- OCR paths

    [ObservableProperty] private string _steamRoot;
    partial void OnSteamRootChanged(string value)
    {
        _s.SetSetting("steam_root", value.Trim());
        ScoreImport.SteamRoot = value.Trim();
        FlashSaved();
    }

    [ObservableProperty] private string _steamUserId;
    partial void OnSteamUserIdChanged(string value)
    {
        _s.SetSetting("steam_user_id", value.Trim());
        ScoreImport.SteamUserId = value.Trim();
        FlashSaved();
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
        DisarmRestore();
        var dir = BackupsDir();
        if (dir is null || !Directory.Exists(dir)) return;
        // THE BUG: this offered EVERY *.db in build/backups. The python pipeline drops its own
        // restore points in the same folder — master-pre-overall-fix-1787214657.db is an 88 MB
        // copy of a DIFFERENT WORLD from 2026-08-20, and three master-20260824-pre*.db snapshots
        // sat beside it — and any of them was one click from replacing the live 2.2 GB career.
        // Only copies of THIS career are offered now; the rule lives on Session so that the
        // vault's prune and this list can never disagree about which files are ours.
        foreach (var f in new DirectoryInfo(dir).GetFiles("*.db")
                     .Where(f => Session.IsCareerBackupName(f.Name))
                     .OrderByDescending(f => f.LastWriteTime).Take(10))
        {
            Backups.Add(f.Name);
        }
    }

    // --- the career vault (P8): save slots as first-class citizens --------------------

    [ObservableProperty] private string _vaultStatus = "";

    /// <summary>Export the career to careers/ as a named save slot (compact, ~5MB).</summary>
    [RelayCommand]
    private async System.Threading.Tasks.Task SaveToVault()
    {
        VaultStatus = "Saving career to the vault…";
        var ok = await CareerBuilder.RunTool("career_snapshot.py", new[] { "save" },
            s => VaultStatus = s);
        VaultStatus = ok ? "✔ Saved — find it under Load on the launch screen."
                         : "Vault save failed — is Python reachable? See the log.";
    }

    /// <summary>Back to the launch screen (vault): continue, load, or start a new career.</summary>
    [RelayCommand]
    private void SwitchCareer()
    {
        if (Avalonia.Application.Current?.ApplicationLifetime
            is not Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop) return;
        var picker = new NewCareerViewModel();
        var window = new Views.NewCareerWindow { DataContext = picker };
        picker.CareerStarted += session =>
        {
            var main = new Views.MainWindow { DataContext = new MainWindowViewModel(session) };
            desktop.MainWindow = main;
            main.Show();
            window.Close();
        };
        var old = desktop.MainWindow;
        desktop.MainWindow = window;
        window.Show();
        old?.Close();
    }

    [RelayCommand]
    private void BackupNow()
    {
        try
        {
            _s.BackupCareer();
            LoadBackups();
            // THE BUG: this said "Backup taken" whatever happened. BackupCareer never throws for
            // a copy that failed — it discards the half-written file, logs, and leaves the reason
            // on LastBackupProblem — so a full drive or a locked database was announced here as a
            // success, and the manager walked on believing the safety net was under them.
            Status = _s.LastBackupProblem
                     ?? (_s.LastBackupPath is null
                         ? "Nothing to back up — this career is not a save on disk."
                         : $"Backup taken ({Path.GetFileName(_s.LastBackupPath)}) — the newest " +
                           $"{Session.BackupsKept} are kept in build/backups.");
        }
        catch (Exception ex) { Status = $"Backup failed: {ex.Message}"; }
    }

    // --- restore: two-step, because it replaces a 2.2 GB world at next launch ----------------
    //
    // THE BUG: one click on "Restore selected" staged any file in the list as the next launch's
    // career — no question asked, no word about what it cost. Same idiom as releasing a member
    // of staff or borrowing from the bank: the first press turns the button into the question,
    // and the question names the copy's date and what pressing again does to the current world.

    public const string RestoreIdle = "↩ Restore selected";
    [ObservableProperty] private string _restoreLabel = RestoreIdle;
    private string? _restoreArmedFor;

    // Arming is per file: pick a different copy and the question is withdrawn, so a press meant
    // for one date can never restore another.
    partial void OnSelectedBackupChanged(string? value) => DisarmRestore();

    private void DisarmRestore()
    {
        _restoreArmedFor = null;
        RestoreLabel = RestoreIdle;
    }

    [RelayCommand]
    private void RestoreBackup()
    {
        if (SelectedBackup is null) { Status = "Pick a backup first."; return; }
        try
        {
            var dir = BackupsDir()!;
            var src = Path.Combine(dir, SelectedBackup);
            var when = new FileInfo(src).LastWriteTime
                .ToString("d MMM yyyy 'at' HH:mm", System.Globalization.CultureInfo.InvariantCulture);
            if (_restoreArmedFor != SelectedBackup)
            {
                _restoreArmedFor = SelectedBackup;
                RestoreLabel = $"↩ Sure? Replace the current world at next launch with the copy from {when}";
                Status = $"Go back to {when}? The career as it stands now is replaced the next time the " +
                         "app opens — every result, signing and contract since then goes with it. A copy " +
                         "of today's world is taken first and kept in build/backups. Press again to " +
                         "confirm, or pick a different copy.";
                return;
            }
            var pending = Path.Combine(Path.GetDirectoryName(dir)!, "master.restore.db");
            File.Copy(src, pending, overwrite: true);
            DisarmRestore();
            Status = $"Restore staged — the copy from {when} replaces the current world when you next " +
                     "open the app. Close and reopen to apply. Today's world is copied into build/backups " +
                     "as a -prerestore file before anything is overwritten.";
        }
        catch (Exception ex) { DisarmRestore(); Status = $"Restore failed: {ex.Message}"; }
    }

    // ---------------------------------------------------------------- shared

    [ObservableProperty]
    private string _status =
        "Everything on this page saves the moment you change it — no Save buttons. Skins " +
        "recolour the window chrome; realism options bite from the next matchday.";

    /// <summary>The quiet confirmation: "Saved." appears for a couple of seconds per persist.</summary>
    [ObservableProperty] private string _savedFlash = "";

    private DispatcherTimer? _flashTimer;

    private void FlashSaved()
    {
        SavedFlash = "Saved.";
        if (_flashTimer is null)
        {
            _flashTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2.2) };
            _flashTimer.Tick += (_, _) => { SavedFlash = ""; _flashTimer!.Stop(); };
        }
        _flashTimer.Stop();
        _flashTimer.Start();
    }

    private void Save(string key, string value, string what)
    {
        _s.SetSetting(key, value);
        Status = $"{what}  →  {value}.";
        FlashSaved();
    }
}
