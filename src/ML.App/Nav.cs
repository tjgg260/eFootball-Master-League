namespace ML.App;

/// <summary>
/// App-wide navigation bus. Any page raises Nav.Go("Squad", EntityRef.Player(id, name));
/// the shell (MainWindowViewModel) is the single handler: it rebuilds the page, hands the
/// focus to it through IFocusTarget, and swaps it in. A settable single handler (not an
/// event) so the full-window rebuild on job acceptance replaces the old shell cleanly.
/// Static because page VMs are built by Session-only factories (NavItem) — threading a
/// navigator through 17 constructors would churn every screen for no gain.
/// </summary>
public static class Nav
{
    public static Action<string, EntityRef?>? Handler { get; set; }

    public static void Go(string pageTitle, EntityRef? focus = null) => Handler?.Invoke(pageTitle, focus);
}
