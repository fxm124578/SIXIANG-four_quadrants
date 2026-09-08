// 安装目录里的 uninstall.exe：转调 Inno 生成的 unins000.exe。
// 编译：csc /nologo /target:winexe /optimize+ /out:setup\uninstall.exe setup\uninstall_launcher.cs
using System.Diagnostics;
using System.IO;
using System.Reflection;

internal static class Program
{
    private static void Main()
    {
        string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        if (string.IsNullOrEmpty(dir))
        {
            return;
        }
        string unins = Path.Combine(dir, "unins000.exe");
        if (!File.Exists(unins))
        {
            return;
        }
        Process.Start(new ProcessStartInfo
        {
            FileName = unins,
            WorkingDirectory = dir,
            UseShellExecute = true
        });
    }
}
