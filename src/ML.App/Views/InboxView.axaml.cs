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
}
