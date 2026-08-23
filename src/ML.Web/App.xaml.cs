using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using ML.Web.Data;

namespace ML.Web;

public partial class App : Application
{
    public App()
    {
        var services = new ServiceCollection();
        services.AddWpfBlazorWebView();
#if DEBUG
        services.AddBlazorWebViewDeveloperTools();
#endif
        services.AddSingleton<Db>();
        services.AddSingleton<AppState>();
        services.AddSingleton<CareerSeeder>();
        services.AddSingleton<MatchdayEngine>();
        services.AddSingleton<GameHost>();
        Resources.Add("services", services.BuildServiceProvider());
    }
}
