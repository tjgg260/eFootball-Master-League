using System;
using System.Runtime.InteropServices;

// Window helpers for tools/shoot_mlapp.ps1. Kept in its own file because PowerShell 5.1's
// here-string parser mangles inline C# in this repo's LF-ended scripts.
public static class WinShot
{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();

    /// <summary>
    /// Must run before any GetWindowRect. Without it Windows reports a DPI-virtualised rect to
    /// this (unaware) process, and the capture silently loses the right and bottom of the window
    /// — which reads as "the layout is wrong" rather than "the screenshot is cropped".
    /// </summary>
    public static void MakeDpiAware() { SetProcessDPIAware(); }

    /// <summary>
    /// Capture a window's own pixels, even when another app is on top. Avalonia renders into
    /// the window DC, so PW_RENDERFULLCONTENT (2) gets the whole client area — the WebView2
    /// cropping problem that forced screen-grabs for ML.Web does not apply here.
    /// </summary>
    public static System.Drawing.Bitmap Capture(IntPtr h)
    {
        RECT r;
        GetWindowRect(h, out r);
        int w = r.Right - r.Left, ht = r.Bottom - r.Top;
        var bmp = new System.Drawing.Bitmap(w, ht);
        using (var g = System.Drawing.Graphics.FromImage(bmp))
        {
            IntPtr hdc = g.GetHdc();
            try { PrintWindow(h, hdc, 2); }
            finally { g.ReleaseHdc(hdc); }
        }
        return bmp;
    }

    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr i);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after,
        int x, int y, int cx, int cy, uint flags);

    /// <summary>
    /// Pin the window above everything. Windows will not let a background process steal focus,
    /// so topmost is the only reliable way to put real clicks (and popup menus, which are their
    /// own windows) in front of the capture.
    /// </summary>
    public static void ForceTop(IntPtr h)
    {
        SetWindowPos(h, new IntPtr(-1), 0, 0, 0, 0, 0x0001 | 0x0002);   // TOPMOST, NOSIZE|NOMOVE
        ShowWindow(h, 9);
        SetForegroundWindow(h);
        System.Threading.Thread.Sleep(600);
    }

    /// <summary>Right-click a point in screen coordinates.</summary>
    public static void RightClick(int x, int y)
    {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(300);
        mouse_event(0x0008, 0, 0, 0, IntPtr.Zero);   // RIGHTDOWN
        mouse_event(0x0010, 0, 0, 0, IntPtr.Zero);   // RIGHTUP
    }

    /// <summary>Click a point in screen coordinates (used to pass the career-picker gate).</summary>
    public static void Click(int x, int y)
    {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(250);
        mouse_event(0x0002, 0, 0, 0, IntPtr.Zero);   // LEFTDOWN
        mouse_event(0x0004, 0, 0, 0, IntPtr.Zero);   // LEFTUP
    }

    /// <summary>Restore, raise and focus a window, returning its screen rectangle.</summary>
    public static RECT Raise(IntPtr h)
    {
        ShowWindow(h, 9);              // SW_RESTORE
        SetForegroundWindow(h);
        System.Threading.Thread.Sleep(700);
        RECT r;
        GetWindowRect(h, out r);
        return r;
    }
}
