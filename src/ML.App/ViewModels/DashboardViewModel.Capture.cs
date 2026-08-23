using Avalonia.Threading;

namespace ML.App.ViewModels;

// --- Screenshot capture wiring (the "press F12, the app pre-fills the result" half) -----------
//
// Lives in its own partial so the capture loop can evolve without touching DashboardViewModel.cs.
// Hook point: LoadNextMatch() always rewrites NextMatchLabel (in the constructor and after every
// recorded result), so the generated OnNextMatchLabelChanged partial method fires reliably at
// construction — the one moment this partial can attach without editing the main file's ctor.

public sealed partial class DashboardViewModel
{
    private bool _captureHooked;

    partial void OnNextMatchLabelChanged(string value)
    {
        if (_captureHooked) return;
        _captureHooked = true;

        var capture = CaptureService.Instance;
        capture.OnCaptured = HandleCapture;   // newest dashboard owns the capture line
        capture.Start();

        // A screenshot OCR'd while you were on another screen still lands here.
        if (capture.TakePending() is { } missed) HandleCapture(missed);
    }

    /// <summary>
    /// A new F12 capture, already OCR'd (worker thread): pre-fill the pending score and say so
    /// on the existing MatchStatus line, leaving the user one click — Record — to confirm.
    /// </summary>
    private void HandleCapture(CaptureResult r)
    {
        Dispatcher.UIThread.Post(() =>
        {
            if (!HasNextMatch)
            {
                Log($"📸 Screenshot captured {r.Time:HH:mm} — no fixture waiting, so nothing was pre-filled.");
                return;
            }

            HomeScore = r.Home;
            AwayScore = r.Away;
            ResultEntryOpen = true;   // a capture means full time — the card becomes the entry desk
            var caveat = r.Confident ? "" : " (LOW OCR confidence — check the digits)";
            Log($"📸 Screenshot captured {r.Time:HH:mm} — looks like {r.Home}-{r.Away}{caveat}, " +
                "confirm with Record.");
        });
    }
}
