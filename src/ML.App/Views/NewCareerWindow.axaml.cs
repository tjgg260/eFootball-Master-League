using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Platform.Storage;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class NewCareerWindow : Window
{
    public NewCareerWindow() => InitializeComponent();

    /// <summary>The first run could not find eFootball: let the player point at the folder, then
    /// build from it. The pick is remembered (build/efootball_dir.txt) for every tool after.</summary>
    private async void OnChooseGameDir(object? sender, RoutedEventArgs e)
    {
        var picked = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = "Choose the folder eFootball is installed in",
            AllowMultiple = false,
        });
        var path = picked.Count > 0 ? picked[0].TryGetLocalPath() : null;
        if (path is not null && DataContext is NewCareerViewModel vm)
            await vm.BuildWorldCommand.ExecuteAsync(path);
    }
}
