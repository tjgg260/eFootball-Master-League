using Avalonia.Controls;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class BoardView : UserControl
{
    public BoardView()
    {
        InitializeComponent();

        // A job offer is a club: right-click gets the shared club menu, so you can walk the
        // squad and the head-to-head before you decide whether to leave. Focusing another
        // row also disarms a primed "Accept job". DataContext resolves lazily at click time.
        MlMenu.Attach<JobOfferRow>(
            this.FindControl<ItemsControl>("OffersList")!,
            o => (DataContext as BoardViewModel)?.MenuFor(o),
            o => { if (DataContext is BoardViewModel vm) vm.FocusOffer(o); });
    }
}
