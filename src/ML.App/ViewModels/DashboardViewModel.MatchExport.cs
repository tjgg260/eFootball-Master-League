using System.IO;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.Input;
using ML.Ingest;

namespace ML.App.ViewModels;

// --- Match data from efootball-re's stats host ------------------------------------------------
//
// The host writes every finished match to <eFootball>\ml_stats\match_*.json. When one arrives and
// it is the fixture that is waiting (by PID, see ExportLinker), the entry desk opens pre-filled:
// score, scorers, ratings. The manager checks and presses Record, which also stores the export's
// team stats and per-player counters against the fixture.
//
// Hook point: LoadNextMatch() always rewrites NextMatchLabel, so the generated
// OnNextMatchLabelChanged partial fires at construction — the one moment a partial can attach
// without editing the main file's constructor.

public sealed partial class DashboardViewModel
{
    private enum ExportTrigger { Arrived, CatchUp, Manual }

    private bool _exportHooked;
    private LinkedMatch? _exportForFixture;
    private int _exportFixtureId;

    partial void OnNextMatchLabelChanged(string value)
    {
        if (_exportHooked) return;
        _exportHooked = true;

        var service = MatchExportService.Instance;
        service.OnExport = path => Dispatcher.UIThread.Post(() => PrefillFromExportFile(path, ExportTrigger.Arrived));
        service.Start(_s.MatchExportDir);

        // After construction finishes: LoadNextMatch is still running and would clear the pickers.
        var missed = service.TakePending();
        Dispatcher.UIThread.Post(() =>
        {
            if (missed is not null) PrefillFromExportFile(missed, ExportTrigger.Arrived);
            else if (MatchExportFolder.LatestFinal(_s.MatchExportDir, out _) is { } latest)
                PrefillFromExport(latest, ExportTrigger.CatchUp);
        });
    }

    /// <summary>Load the newest finished match from the stats host into the entry desk.</summary>
    [RelayCommand]
    private void LoadMatchExport()
    {
        ImportNotice = "";
        var export = MatchExportFolder.LatestFinal(_s.MatchExportDir, out var reason);
        if (export is null)
        {
            RefuseExport(reason + " The stats host writes one per match; install it with tools/vendor/efootball-re/memprobe/deploy_host.sh.");
            return;
        }
        PrefillFromExport(export, ExportTrigger.Manual);
    }

    private void PrefillFromExportFile(string path, ExportTrigger trigger)
    {
        MatchExport export;
        try
        {
            export = MatchExport.Load(path);
        }
        catch (Exception ex)
        {
            Log($"📥 Couldn't read {Path.GetFileName(path)}: {ex.Message}");
            return;
        }
        PrefillFromExport(export, trigger);
    }

    private void PrefillFromExport(MatchExport export, ExportTrigger trigger)
    {
        if (!HasNextMatch)
        {
            if (trigger != ExportTrigger.CatchUp) Log($"📥 Match export {export.Stem} — no fixture waiting, nothing pre-filled.");
            return;
        }
        if (!_s.IsAfterExportWatermark(export))
        {
            if (trigger == ExportTrigger.Manual)
                RefuseExport($"{export.Stem} is from a match played before your last recorded result.");
            return;
        }

        var linked = _s.LinkMatchExport(export, _homeId, _awayId, out var reason);
        if (linked is null)
        {
            if (trigger == ExportTrigger.Manual) RefuseExport($"{export.Stem}: {reason}");
            else if (trigger == ExportTrigger.Arrived) Log($"📥 Match export {export.Stem} arrived — {reason}");
            return;
        }

        HomeScore = linked.Home.Goals;
        AwayScore = linked.Away.Goals;
        GoalPicks.Clear();
        foreach (var name in Session.ExportScorers(linked))
        {
            // A substitute scorer is not among the XI names the pickers were built from.
            if (!MatchPlayerNames.Contains(name)) MatchPlayerNames.Add(name);
            GoalPicks.Add(new EventPickRow(MatchPlayerNames) { Selected = name });
        }
        RatingsText = Session.ExportRatingsText(linked);
        _exportForFixture = linked;
        _exportFixtureId = _fixtureId;

        var unresolved = Session.UnresolvedScorers(linked);
        ImportNotice = unresolved.Count > 0
            ? $"⚠ Goals by players in neither squad: {string.Join(", ", unresolved)}. Add those scorers by hand."
            : "";
        ResultEntryOpen = true;
        Log($"📥 {export.Stem}: {_homeName} {linked.Home.Goals}–{linked.Away.Goals} {_awayName}, " +
            $"{GoalPicks.Count} scorer(s) and {linked.Resolved} ratings pre-filled from the stats host. " +
            "Goals are the host's inferred counter, so check the score, then Record.");
    }

    /// <summary>After Record: keep the pre-filled export's numbers, and retire every export so far.</summary>
    private string StoreExportForRecordedFixture(int fixtureId)
    {
        var note = "";
        try
        {
            if (_exportForFixture is { } linked && _exportFixtureId == fixtureId)
                note = "\n" + _s.StoreMatchExport(fixtureId, linked);
        }
        catch (Exception ex)
        {
            Program.Log("Dashboard.StoreMatchExport", ex);
            note = $"\nMatch data not stored: {ex.Message}";
        }
        finally
        {
            _exportForFixture = null;
        }
        try { _s.AdvanceExportWatermark(); }
        catch (Exception ex) { Program.Log("Dashboard.AdvanceExportWatermark", ex); }
        return note;
    }

    private void RefuseExport(string message)
    {
        ImportNotice = $"⚠ {message}";
        Log($"📥 {message}");
    }
}
