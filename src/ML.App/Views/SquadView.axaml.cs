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
    public SquadView() => InitializeComponent();

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
