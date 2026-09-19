namespace ML.App;

/// <summary>
/// App-wide "the shell's badges may be stale" bus — the same single-handler shape as
/// <see cref="Nav"/>, for the same reason (page VMs are Session-only, threading the shell
/// through 17 constructors would churn every screen for no gain).
///
/// THE BUG this exists to fix (audit C7): marking a story read on the News screen updates
/// that screen, but the sidebar's unread pill is only ever re-read by MainWindowViewModel's
/// own RefreshShell — which runs on navigation, not on every click inside a page. So the pill
/// stayed lit until you left News and came back, which read as "marking it read didn't work".
/// InboxViewModel calls <see cref="Request"/> after MarkRead/MarkAllRead; the shell is the
/// only handler, and it just re-runs the same RefreshShell a navigation already triggers.
/// </summary>
public static class ShellRefresh
{
    public static Action? Handler { get; set; }

    public static void Request() => Handler?.Invoke();
}
