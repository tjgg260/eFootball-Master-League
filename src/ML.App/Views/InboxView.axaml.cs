using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class InboxView : UserControl
{
    public InboxView()
    {
        InitializeComponent();

        // Every name in the news is an entity again (P10): stories, the market ticker and
        // the done-deal hero all answer to the same right-click vocabulary.
        MlMenu.Attach<NewsEntry>(this.FindControl<ItemsControl>("FeedList")!,
            e => (DataContext as InboxViewModel)?.MenuFor(e));
        MlMenu.Attach<TickerEntry>(this.FindControl<ItemsControl>("TickerList")!,
            t => (DataContext as InboxViewModel)?.MenuForTicker(t));

        var hero = this.FindControl<Border>("HeroCard")!;
        hero.AddHandler(InputElement.PointerPressedEvent, (_, e) =>
        {
            if (!e.GetCurrentPoint(hero).Properties.IsRightButtonPressed) return;
            var menu = (DataContext as InboxViewModel)?.MenuForHero();
            if (menu is null || menu.Items.Count == 0) return;
            menu.Placement = PlacementMode.Pointer;
            menu.Open(hero);
            e.Handled = true;
        }, RoutingStrategies.Tunnel);
    }

    /// <summary>The ⋯ on a news card: the SAME menu the right-click opens. Nested inside the
    /// card's own mark-read Button — the inner Button's Click is handled before it can bubble
    /// to the outer one, so this never also marks the story read.</summary>
    private void OnFeedRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as InboxViewModel;
        NewsEntry? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<NewsEntry>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = "Couldn't bring up this story's options.";
            e.Handled = true;
        }
        catch (Exception ex)
        {
            Program.Log("Inbox.OnFeedRowMenu", ex);
            if (vm is not null) vm.Status = "Couldn't bring up this story's options.";
        }
    }

    /// <summary>The ⋯ on a ticker row: the SAME menu the right-click opens.</summary>
    private void OnTickerRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as InboxViewModel;
        TickerEntry? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<TickerEntry>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuForTicker(row), btn)) vm.Status = "Couldn't bring up his options.";
        }
        catch (Exception ex)
        {
            Program.Log("Inbox.OnTickerRowMenu", ex);
            if (vm is not null) vm.Status = "Couldn't bring up his options.";
        }
    }

    /// <summary>The ⋯ on the DONE DEAL hero: the SAME menu the right-click opens.</summary>
    private void OnHeroMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as InboxViewModel;
        try
        {
            if (vm is null || sender is not Control btn) return;
            if (!MlMenu.OpenAt(vm.MenuForHero(), btn)) vm.Status = "Couldn't bring up its options.";
        }
        catch (Exception ex)
        {
            Program.Log("Inbox.OnHeroMenu", ex);
            if (vm is not null) vm.Status = "Couldn't bring up its options.";
        }
    }
}
