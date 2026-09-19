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
            r => MenuOrSay(r.Name, onLoan: false, vm => vm.MenuFor(r)),
            r => { if (DataContext is SquadViewModel vm) vm.Selected = r; });

        // Loanees are players too — the strip is not a dead list of prose.
        MlMenu.Attach<LoanRowVm>(this.FindControl<ItemsControl>("LoansList")!,
            r => MenuOrSay(r.Name, onLoan: true, vm => vm.MenuForLoan(r)));

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

    /// <summary>
    /// The right-click's menu builder, made to SPEAK. THE BUG: the ⋯ handlers below say
    /// "Couldn't bring up his options" on a null or empty menu, but the right-click on the very
    /// same rows went through MlMenu.Attach, which returns without a word on the same result —
    /// and logs without a word when the builder throws. Two gestures, one menu, and only one of
    /// them admitted when it had nothing to show. This wraps the builder so both paths end in
    /// the same sentence on the status line; Attach still receives null and opens nothing.
    /// </summary>
    private ContextMenu? MenuOrSay(string name, bool onLoan, Func<SquadViewModel, ContextMenu?> build)
    {
        if (DataContext is not SquadViewModel vm) return null;
        try
        {
            var menu = build(vm);
            if (menu is null || menu.Items.Count == 0) vm.SayMenuUnavailable(name, onLoan);
            return menu;
        }
        catch (Exception ex)
        {
            Program.Log(onLoan ? "SquadView.MenuOrSay (loan)" : "SquadView.MenuOrSay", ex);
            vm.SayMenuUnavailable(name, onLoan);
            return null;
        }
    }

    /// <summary>
    /// The ⋯ on a roster row: the SAME menu the right-click opens, for anyone who never
    /// right-clicks. THE BUG it fixes: both gestures on this grid were invisible — nothing on
    /// screen was clickable to reach a player's verbs, so the twelve of them may as well not
    /// have existed. A ContextMenu has to be opened AT a control, which a Command cannot do
    /// from a ViewModel, so the trigger lives here and delegates to the one builder.
    /// </summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as SquadViewModel;
        SquadEntry? row = null;
        // THE BUG: this handler ran naked, unlike MlMenu.Attach beside it. Setting Selected runs
        // SquadViewModel.OnSelectedChanged, which reads the live 2.2 GB career file, and a throw
        // from any of that landed on the UI thread mid-input-dispatch. The right-click path was
        // caught by Attach's own guard; the ⋯ path — the one visible trigger — took the app down.
        try
        {
            if (vm is null || sender is not Control btn) return;
            // Same walk MlMenu.Attach uses, so the button and the right-click can never disagree
            // about which player was hit.
            row = MlMenu.RowAt<SquadEntry>(btn);
            if (row is null) return;
            vm.Selected = row;   // the card beside the grid follows the man you are acting on
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.SayMenuUnavailable(row.Name);
        }
        catch (Exception ex)
        {
            Program.Log("SquadView.OnRowMenu", ex);
            vm?.SayMenuUnavailable(row?.Name ?? "");
        }
    }

    /// <summary>The ⋯ on a loans-strip row — the loanee's own copy of the shared menu.</summary>
    private void OnLoanMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as SquadViewModel;
        LoanRowVm? row = null;
        try   // guarded for the same reason OnRowMenu is: a throw here is a click that kills the app
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<LoanRowVm>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuForLoan(row), btn)) vm.SayMenuUnavailable(row.Name, onLoan: true);
        }
        catch (Exception ex)
        {
            Program.Log("SquadView.OnLoanMenu", ex);
            vm?.SayMenuUnavailable(row?.Name ?? "", onLoan: true);
        }
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
