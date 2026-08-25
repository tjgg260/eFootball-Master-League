using System;
using System.IO;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Platform.Storage;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class SquadView : UserControl
{
    public SquadView()
    {
        InitializeComponent();

        // The shared right-click vocabulary. A roster row selects first, then opens the menu
        // EntityActions builds for that player — own-squad verbs on your own club, the
        // scout/enquiry/shortlist set on anyone else's, which is how you act on a browsed
        // club at all. DataContext resolves at click time, so attaching in the ctor is safe.
        MlMenu.Attach<SquadEntry>(this.FindControl<DataGrid>("RosterGrid")!,
            r => (DataContext as SquadViewModel)?.MenuFor(r),
            r => { if (DataContext is SquadViewModel vm) vm.Selected = r; });

        // Loanees are players too — the strip is not a dead list of prose.
        MlMenu.Attach<LoanRowVm>(this.FindControl<ItemsControl>("LoansList")!,
            r => (DataContext as SquadViewModel)?.MenuForLoan(r));

        // Double-click a man to OPEN him: his whole profile, the full width of the window,
        // instead of the card that used to be squeezed into the 262px column beside this
        // grid. The gesture resolves the row exactly as the right-click menu does, and it
        // leaves single-click selection and the menu alone — a double-click is two single
        // clicks first, so the row is already selected and the card beside the grid still
        // follows the keyboard.
        MlMenu.OnDoubleClick<SquadEntry>(this.FindControl<DataGrid>("RosterGrid")!,
            r => Nav.Go("Player", EntityRef.Player(r.PlayerId, r.Name)));
        MlMenu.OnDoubleClick<LoanRowVm>(this.FindControl<ItemsControl>("LoansList")!,
            r => Nav.Go("Player", EntityRef.Player(r.PlayerId, r.Name)));
    }

    /// <summary>"Set photo…" — copy the owner's chosen image to custom_faces/&lt;player_id&gt;,
    /// where the portrait resolver's tier 0 picks it up ahead of every pack.</summary>
    private async void OnSetPhoto(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not SquadViewModel vm || vm.Selected is null) return;
        var top = TopLevel.GetTopLevel(this);
        if (top is null) return;
        var files = await top.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = $"Choose a photo for {vm.Selected.Name}",
            AllowMultiple = false,
            FileTypeFilter = new[]
            {
                new FilePickerFileType("Images") { Patterns = new[] { "*.png", "*.jpg", "*.jpeg", "*.webp" } },
            },
        });
        var src = files.FirstOrDefault()?.TryGetLocalPath();
        if (src is null) return;
        var root = MatchLauncher.FindRepoRoot();
        if (root is null) return;
        try
        {
            var dir = Path.Combine(root, "custom_faces");
            Directory.CreateDirectory(dir);
            var pid = vm.Selected.PlayerId;
            // one photo per player: clear other extensions before writing the new one
            foreach (var ext in new[] { "png", "jpg", "jpeg", "webp" })
            {
                var old = Path.Combine(dir, $"{pid}.{ext}");
                if (File.Exists(old)) File.Delete(old);
            }
            var dest = Path.Combine(dir, $"{pid}{Path.GetExtension(src).ToLowerInvariant()}");
            File.Copy(src, dest);
            vm.RefreshSelectedPortrait();
        }
        catch (Exception ex)
        {
            Program.Log("SetPhoto", ex);
        }
    }
}
