// Refit Studio - лаунчер. Собирается встроенным в Windows компилятором (.NET Framework 4), см. build.bat.
// 1) находит Blender, WolvenKit CLI, игру и папки с модами; 2) шаг 1 - тело (профиль из мода тела);
// 3) шаг 2 - открывает мастерскую в Blender с выбранным телом.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Reflection;

[assembly: AssemblyTitle("Refit Studio")]
[assembly: AssemblyDescription("Refit Studio launcher. Makes clothing refits for Cyberpunk 2077 body mods in Blender.")]
[assembly: AssemblyProduct("Refit Studio")]
[assembly: AssemblyCompany("Altshuler")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Altshuler")]
[assembly: AssemblyVersion("0.3.0.0")]
[assembly: AssemblyFileVersion("0.3.0.0")]
[assembly: AssemblyInformationalVersion("0.3.0")]

namespace RefitStudio
{
    static class App
    {
        public static readonly string Dir = AppDomain.CurrentDomain.BaseDirectory;
        public static readonly string Core = Path.Combine(Dir, "core");
        // REFIT_DATA - другая папка данных (для проверки "как у нового пользователя")
        public static readonly string Data = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("REFIT_DATA"))
            ? Environment.GetEnvironmentVariable("REFIT_DATA")
            : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RefitStudio");
        public static readonly string ConfigPath = Path.Combine(Data, "config.json");
        public static readonly string Profiles = Path.Combine(Data, "bodies");
        // язык интерфейса: "en" (по умолчанию) или "ru"; задаётся до остальных строк
        public static readonly string Lang = DetectLang();

        static string DetectLang()
        {
            string env = Environment.GetEnvironmentVariable("REFIT_LANG");
            if (!string.IsNullOrEmpty(env)) return env == "ru" ? "ru" : "en";
            try
            {
                if (File.Exists(ConfigPath))
                {
                    var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(ConfigPath, Encoding.UTF8));
                    object v; if (d != null && d.TryGetValue("lang", out v) && v != null && v.ToString() == "ru") return "ru";
                }
            }
            catch { }
            return "en";
        }

        public static string T(string ru, string en) { return Lang == "ru" ? ru : en; }
        public static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        public static float Scale = 1f;

        // палитра «киберпанк»: почти чёрный фон, жёлтый неон #FCEE0A (главные кнопки), бирюза #02D7F2 (выбранное)
        public static readonly Color Bg = Color.FromArgb(13, 13, 20);
        public static readonly Color Card = Color.FromArgb(22, 22, 31);
        public static readonly Color Line = Color.FromArgb(42, 42, 56);
        public static readonly Color Text = Color.FromArgb(242, 242, 245);
        public static readonly Color Dim = Color.FromArgb(142, 142, 163);
        public static readonly Color Accent = Color.FromArgb(252, 238, 10);
        public static readonly Color Sel = Color.FromArgb(2, 215, 242);
        public static readonly Color SelRow = Color.FromArgb(11, 43, 51);
        // как в мастерской: кнопки, поля ввода, шапка списков
        public static readonly Color Btn = Color.FromArgb(30, 30, 42);
        public static readonly Color BtnHover = Color.FromArgb(42, 42, 56);
        public static readonly Color Field = Color.FromArgb(16, 16, 24);
        public static readonly Color Good = Color.FromArgb(90, 200, 120);
        public static readonly Color Bad = Color.FromArgb(235, 90, 90);

        public static int S(int v) { return (int)Math.Round(v * Scale); }

        [DllImport("user32.dll")] static extern bool SetProcessDPIAware();

        [STAThread]
        static void Main()
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using (var g = Graphics.FromHwnd(IntPtr.Zero)) Scale = g.DpiX / 96f;
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072; // TLS 1.2 для GitHub
            Application.Run(new MainForm());
        }

        // ---------- настройки ----------
        public static Dictionary<string, object> LoadConfig()
        {
            try
            {
                if (File.Exists(ConfigPath))
                    return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(ConfigPath, Encoding.UTF8));
            }
            catch { }
            return new Dictionary<string, object>();
        }

        public static void SaveConfig(Dictionary<string, object> cfg)
        {
            Directory.CreateDirectory(Data);
            string tmp = ConfigPath + ".tmp";
            File.WriteAllText(tmp, Pretty(Json.Serialize(cfg)), new UTF8Encoding(false));
            if (File.Exists(ConfigPath)) File.Delete(ConfigPath);
            File.Move(tmp, ConfigPath);
        }

        static string Pretty(string json)
        {
            var sb = new StringBuilder(); int ind = 0; bool str = false;
            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (c == '"' && (i == 0 || json[i - 1] != '\\')) str = !str;
                if (str) { sb.Append(c); continue; }
                if (c == '{' || c == '[') { sb.Append(c).Append('\n').Append(' ', ++ind * 2); }
                else if (c == '}' || c == ']') { sb.Append('\n').Append(' ', --ind * 2).Append(c); }
                else if (c == ',') { sb.Append(c).Append('\n').Append(' ', ind * 2); }
                else if (c == ':') sb.Append(": ");
                else sb.Append(c);
            }
            return sb.ToString();
        }

        public static string Str(Dictionary<string, object> d, string key)
        {
            object v; return d.TryGetValue(key, out v) && v != null ? v.ToString() : "";
        }

        public static List<string> List(Dictionary<string, object> d, string key)
        {
            object v; var res = new List<string>();
            if (d.TryGetValue(key, out v) && v is System.Collections.IEnumerable && !(v is string))
                foreach (var x in (System.Collections.IEnumerable)v) if (x != null) res.Add(x.ToString());
            return res;
        }

        // ---------- проверка путей ----------
        public static bool GameOk(string p) { return p != "" && File.Exists(Path.Combine(p, "bin", "x64", "Cyberpunk2077.exe")); }
        public static bool WkOk(string p) { return p != "" && File.Exists(p) && Path.GetFileName(p).ToLower().Contains("wolvenkit"); }
        public static bool BlenderOk(string p) { return p != "" && File.Exists(p) && Path.GetFileName(p).ToLower() == "blender.exe"; }

        public static string BlenderVersion(string exe)
        {
            try
            {
                var psi = new ProcessStartInfo(exe, "--version") { UseShellExecute = false, RedirectStandardOutput = true, CreateNoWindow = true };
                using (var p = Process.Start(psi))
                {
                    string o = p.StandardOutput.ReadToEnd(); p.WaitForExit(20000);
                    var m = Regex.Match(o, @"Blender (\d+)\.(\d+)(\.\d+)?");
                    return m.Success ? m.Groups[1].Value + "." + m.Groups[2].Value + m.Groups[3].Value : "";
                }
            }
            catch { return ""; }
        }

        public static bool BlenderNewEnough(string ver)
        {
            var m = Regex.Match(ver ?? "", @"^(\d+)\.(\d+)");
            if (!m.Success) return false;
            int a = int.Parse(m.Groups[1].Value), b = int.Parse(m.Groups[2].Value);
            return a > 4 || (a == 4 && b >= 2);
        }

        // ---------- поиск программ ----------
        static IEnumerable<string> Drives()
        {
            foreach (var d in DriveInfo.GetDrives())
            {
                bool ok = false;
                try { ok = d.DriveType == DriveType.Fixed && d.IsReady; } catch { }
                if (ok) yield return d.RootDirectory.FullName;
            }
        }

        public static List<string> SteamLibraries()
        {
            var libs = new List<string>();
            var roots = new List<string> {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Steam"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Steam") };
            foreach (var d in Drives()) { roots.Add(Path.Combine(d, "Steam")); roots.Add(Path.Combine(d, "SteamLibrary")); }
            foreach (var r in roots)
            {
                if (Directory.Exists(Path.Combine(r, "steamapps"))) libs.Add(r);
                string vdf = Path.Combine(r, "steamapps", "libraryfolders.vdf");
                if (!File.Exists(vdf)) continue;
                try
                {
                    foreach (Match m in Regex.Matches(File.ReadAllText(vdf), "\"path\"\\s+\"([^\"]+)\""))
                        libs.Add(m.Groups[1].Value.Replace("\\\\", "\\"));
                }
                catch { }
            }
            return libs.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        public static string FindGame()
        {
            var c = new List<string>();
            foreach (var lib in SteamLibraries()) c.Add(Path.Combine(lib, "steamapps", "common", "Cyberpunk 2077"));
            string epic = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), @"Epic\EpicGamesLauncher\Data\Manifests");
            try
            {
                if (Directory.Exists(epic))
                    foreach (var f in Directory.GetFiles(epic, "*.item"))
                    {
                        string t = File.ReadAllText(f);
                        if (!t.Contains("Cyberpunk")) continue;
                        var m = Regex.Match(t, "\"InstallLocation\"\\s*:\\s*\"([^\"]+)\"");
                        if (m.Success) c.Add(m.Groups[1].Value.Replace("\\\\", "\\"));
                    }
            }
            catch { }
            foreach (var d in Drives())
            {
                c.Add(Path.Combine(d, @"GOG Games\Cyberpunk 2077"));
                c.Add(Path.Combine(d, @"Games\Cyberpunk 2077"));
                c.Add(Path.Combine(d, @"Program Files (x86)\GOG Galaxy\Games\Cyberpunk 2077"));
                c.Add(Path.Combine(d, @"Epic Games\Cyberpunk2077"));
                c.Add(Path.Combine(d, @"Program Files\Epic Games\Cyberpunk2077"));
            }
            return c.FirstOrDefault(GameOk) ?? "";
        }

        public static string FindBlender()
        {
            var c = new List<string>();
            c.Add(Path.Combine(Dir, @"tools\blender\blender.exe"));
            foreach (var pf in new[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86) })
            {
                string bf = Path.Combine(pf, "Blender Foundation");
                try
                {
                    if (Directory.Exists(bf))
                        c.AddRange(Directory.GetDirectories(bf).OrderByDescending(VersionKey).Select(d => Path.Combine(d, "blender.exe")));
                }
                catch { }
            }
            foreach (var lib in SteamLibraries()) c.Add(Path.Combine(lib, @"steamapps\common\Blender\blender.exe"));
            return c.FirstOrDefault(BlenderOk) ?? "";
        }

        static string VersionKey(string dir)
        {
            var m = Regex.Match(Path.GetFileName(dir), @"(\d+)\.(\d+)");
            return m.Success ? int.Parse(m.Groups[1].Value).ToString("D3") + int.Parse(m.Groups[2].Value).ToString("D3") : "";
        }

        public static string FindWolvenKit()
        {
            var c = new List<string> {
                Path.Combine(Dir, @"tools\wolvenkit\WolvenKit.CLI.exe"),
                Path.Combine(Data, @"tools\wolvenkit\WolvenKit.CLI.exe") };
            return c.FirstOrDefault(WkOk) ?? "";
        }

        public static List<string> FindModSources(string game)
        {
            var c = new List<string> {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), @"Vortex\cyberpunk2077\mods"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"ModOrganizer\Cyberpunk 2077\mods") };
            var res = c.Where(Directory.Exists).ToList();
            // Vortex и MO2 сами раскладывают моды в папку игры: если они есть, папка игры дала бы дубли
            if (res.Count == 0 && GameOk(game) && Directory.Exists(Path.Combine(game, @"archive\pc\mod")))
                res.Add(Path.Combine(game, @"archive\pc\mod"));
            return res;
        }

        // ---------- архивы и моды ----------
        public const string PFA = @"base\characters\common\player_base_bodies\player_female_average\";
        public static readonly string PartBody = T("тело", "body");
        public static readonly Dictionary<string, string> BodyFiles = new Dictionary<string, string> {
            { PartBody, PFA + "t0_000_pwa_base__full.mesh" },
            { T("руки", "arms"), PFA + @"arms_hq\a0_000_pwa_base_hq__l.mesh" },
            { T("ступни", "feet"), PFA + "l0_000_pwa_base__cs_flat.mesh" } };
        // мужской V: те же файлы в player_man_average с pma; ступни входят в модель тела
        public const string PMA = @"base\characters\common\player_base_bodies\player_man_average\";
        public static readonly Dictionary<string, string> BodyFilesMale = new Dictionary<string, string> {
            { PartBody, PMA + "t0_000_pma_base__full.mesh" },
            { T("руки", "arms"), PMA + @"arms_hq\a0_000_pma_base_hq__l.mesh" } };
        public static Dictionary<string, string> BodyFilesFor(string gender) { return gender == "male" ? BodyFilesMale : BodyFiles; }
        public static string Gender(Dictionary<string, object> c) { return Str(c, "gender") == "male" ? "male" : "female"; }

        public static ulong Fnv(string s)
        {
            ulong h = 0xcbf29ce484222325UL;
            foreach (byte b in Encoding.UTF8.GetBytes(s.ToLowerInvariant())) { h ^= b; h *= 0x100000001b3UL; }
            return h;
        }

        public static HashSet<ulong> ArchiveHashes(string path)
        {
            var res = new HashSet<ulong>();
            using (var f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var r = new BinaryReader(f))
            {
                if (f.Length < 40 || Encoding.ASCII.GetString(r.ReadBytes(4)) != "RDAR") return res;
                r.ReadUInt32(); long ipos = (long)r.ReadUInt64(); int isz = (int)r.ReadUInt32();
                f.Seek(ipos, SeekOrigin.Begin);
                byte[] ix = r.ReadBytes(isz);
                int cnt = BitConverter.ToInt32(ix, 16);
                for (int i = 0; i < cnt && 28 + i * 56 + 8 <= ix.Length; i++) res.Add(BitConverter.ToUInt64(ix, 28 + i * 56));
            }
            return res;
        }

        public static string CleanName(string n)
        {
            string s = Regex.Replace(n, @"\s+\d{3,6}(\s+[\d.]+)*\s+20\d\d-\d\d-\d\dT\S+(\s+\S+)?$", "");
            s = Regex.Replace(s, @"[-_ ]\d{3,6}([-_. ]\d+)+$", "");
            s = Regex.Replace(s, @"_\d{3,6}(_[\d.]+)*_20\d\d-\d\d-\d\dT\S+$", "");
            s = s.Trim(' ', '-', '_');
            return s == "" ? n : s;
        }
    }

    class Mod
    {
        public string Name, Path, Source;
        public List<string> Archives = new List<string>();
        public List<string> Parts = new List<string>();
        public bool IsBody { get { return Parts.Count > 0; } }

        static List<string> ArchivesIn(string dir)
        {
            try { return Directory.GetFiles(dir, "*.archive", SearchOption.AllDirectories).ToList(); }
            catch { return new List<string>(); }
        }

        public static List<Mod> Scan(IEnumerable<string> sources)
        {
            var res = new List<Mod>(); var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var src in sources)
            {
                if (!Directory.Exists(src)) continue;
                string[] entries;
                try { entries = Directory.GetFileSystemEntries(src); } catch { continue; }
                foreach (var e in entries.OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
                {
                    var m = new Mod { Path = e, Source = src };
                    if (File.Exists(e) && e.EndsWith(".archive", StringComparison.OrdinalIgnoreCase))
                    {
                        m.Name = System.IO.Path.GetFileNameWithoutExtension(e); m.Archives.Add(e);
                    }
                    else if (Directory.Exists(e))
                    {
                        m.Name = System.IO.Path.GetFileName(e); m.Archives = ArchivesIn(e);
                    }
                    if (m.Archives.Count == 0 || !seen.Add(e)) continue;
                    if (m.Archives.All(a => System.IO.Path.GetFileName(a).ToLower().StartsWith("#refit_") ||
                                            System.IO.Path.GetFileName(a).ToLower().StartsWith("#slim_thin_refit_"))) continue;
                    res.Add(m);
                }
            }
            return res;
        }

        public void Detect(string gender = "female")
        {
            var want = App.BodyFilesFor(gender).ToDictionary(k => k.Key, k => App.Fnv(k.Value));
            foreach (var a in Archives)
            {
                try
                {
                    var hs = App.ArchiveHashes(a);
                    foreach (var w in want) if (hs.Contains(w.Value) && !Parts.Contains(w.Key)) Parts.Add(w.Key);
                }
                catch { }
            }
        }
    }

    // ---------- общие элементы интерфейса ----------
    static class UI
    {
        public static Font F(float size, FontStyle st = FontStyle.Regular) { return new Font("Segoe UI", size, st); }

        // «техно»-шрифт для заголовков и главных кнопок: Bahnschrift есть в Windows 10/11, иначе Segoe UI
        static string tech;
        public static Font Tech(float size)
        {
            if (tech == null)
            {
                tech = "Segoe UI";
                using (var fc = new System.Drawing.Text.InstalledFontCollection())
                    foreach (var f in fc.Families)
                        if (f.Name == "Bahnschrift SemiBold SemiConden") { tech = f.Name; break; }
            }
            return new Font(tech, size, tech == "Segoe UI" ? FontStyle.Bold : FontStyle.Regular);
        }

        public static Label Label(Control parent, string text, int x, int y, int w, int h, float size = 9.5f, Color? color = null, FontStyle st = FontStyle.Regular)
        {
            var l = new Label { Text = text, Left = App.S(x), Top = App.S(y), Width = App.S(w), Height = App.S(h), Font = F(size, st),
                ForeColor = color ?? App.Text, BackColor = Color.Transparent, AutoEllipsis = true };
            parent.Controls.Add(l); return l;
        }

        public static Button Button(Control parent, string text, int x, int y, int w, int h, EventHandler click, bool accent = false)
        {
            var b = new Button { Text = text, Left = App.S(x), Top = App.S(y), Width = App.S(w), Height = App.S(h), FlatStyle = FlatStyle.Flat,
                Font = accent ? Tech(12.5f) : F(9.5f), Cursor = Cursors.Hand,
                BackColor = accent ? App.Accent : App.Btn, ForeColor = accent ? App.Bg : App.Text, UseVisualStyleBackColor = false };
            b.FlatAppearance.BorderSize = 0;
            b.FlatAppearance.MouseOverBackColor = accent ? Color.FromArgb(255, 246, 92) : App.BtnHover;
            b.FlatAppearance.MouseDownBackColor = accent ? Color.FromArgb(222, 208, 0) : App.Line;
            if (accent) b.Text = text.ToUpper();
            b.EnabledChanged += (s, e) => { b.BackColor = b.Enabled ? (accent ? App.Accent : App.Btn) : Color.FromArgb(26, 26, 36);
                                             b.ForeColor = b.Enabled ? (accent ? App.Bg : App.Text) : App.Dim; };
            Round(b, accent ? 10 : 8);
            if (click != null) b.Click += click;
            parent.Controls.Add(b); return b;
        }

        // «стеклянная» кнопка, как на макете: почти прозрачная, с тонкой светлой рамкой
        public static Button Glass(Control parent, string text, int x, int y, int w, int h, EventHandler click)
        {
            var b = Button(parent, text, x, y, w, h, click);
            b.BackColor = Color.FromArgb(14, 255, 255, 255);
            b.FlatAppearance.MouseOverBackColor = Color.FromArgb(34, 255, 255, 255);
            b.FlatAppearance.MouseDownBackColor = Color.FromArgb(50, 255, 255, 255);
            b.EnabledChanged += (s, e) => { b.BackColor = Color.FromArgb(b.Enabled ? 14 : 6, 255, 255, 255); };
            b.Paint += (s, e) =>
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using (var pen = new Pen(Color.FromArgb(b.Enabled ? 52 : 24, 255, 255, 255), 1f))
                using (var path = RoundRect(new Rectangle(0, 0, b.Width - 1, b.Height - 1), App.S(8)))
                    e.Graphics.DrawPath(pen, path);
            };
            return b;
        }

        // заголовок блока, как подписи в панели мастерской: небольшой, серый, заглавными
        public static Label Heading(Control parent, string text, int x, int y, int w = 400)
        {
            return Label(parent, text.ToUpper(), x, y, w, 22, 9f, App.Dim, FontStyle.Bold);
        }

        // скруглённые углы, как у кнопок и панелей в Blender
        public static void Round(Control c, int radius)
        {
            Action apply = () =>
            {
                int d = App.S(radius) * 2;
                if (c.Width < d || c.Height < d) return;
                var p = new System.Drawing.Drawing2D.GraphicsPath();
                p.AddArc(0, 0, d, d, 180, 90);
                p.AddArc(c.Width - d, 0, d, d, 270, 90);
                p.AddArc(c.Width - d, c.Height - d, d, d, 0, 90);
                p.AddArc(0, c.Height - d, d, d, 90, 90);
                p.CloseFigure();
                c.Region = new Region(p);
            };
            c.SizeChanged += (s, e) => apply();
            apply();
        }

        // «стеклянная» карточка: полупрозрачная (сквозь неё видно пятна света фона) и с тонкой рамкой
        public static Panel Card(Control parent, int x, int y, int w, int h)
        {
            var p = new Panel { Left = App.S(x), Top = App.S(y), Width = App.S(w), Height = App.S(h), BackColor = Color.FromArgb(150, App.Card) };
            Round(p, 14);
            p.Paint += (s, e) =>
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using (var pen = new Pen(Color.FromArgb(40, 255, 255, 255), 1f))
                using (var path = RoundRect(new Rectangle(0, 0, p.Width - 1, p.Height - 1), App.S(14)))
                    e.Graphics.DrawPath(pen, path);
            };
            parent.Controls.Add(p); return p;
        }

        public static System.Drawing.Drawing2D.GraphicsPath RoundRect(Rectangle r, int radius)
        {
            int d = radius * 2;
            var p = new System.Drawing.Drawing2D.GraphicsPath();
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        // мягкое пятно света (как на макете): яркое в центре, к краям прозрачное
        public static void Glow(Graphics g, Rectangle r, Color c, int alpha)
        {
            using (var path = new System.Drawing.Drawing2D.GraphicsPath())
            {
                path.AddEllipse(r);
                using (var b = new System.Drawing.Drawing2D.PathGradientBrush(path))
                {
                    b.CenterColor = Color.FromArgb(alpha, c);
                    b.SurroundColors = new[] { Color.FromArgb(0, c) };
                    g.FillPath(b, path);
                }
            }
        }

        public static TextBox Box(Control parent, int x, int y, int w, bool ro = true)
        {
            var t = new TextBox { Left = App.S(x), Top = App.S(y), Width = App.S(w), Font = F(9.5f), ReadOnly = ro,
                BackColor = App.Field, ForeColor = App.Text, BorderStyle = BorderStyle.FixedSingle };
            parent.Controls.Add(t); return t;
        }

        public static ListView List(Control parent, int x, int y, int w, int h, params object[] cols)
        {
            var lv = new ListView { Left = App.S(x), Top = App.S(y), Width = App.S(w), Height = App.S(h), View = View.Details, FullRowSelect = true,
                MultiSelect = false, HideSelection = false, BackColor = App.Field, ForeColor = App.Text, Font = F(9.5f),
                BorderStyle = BorderStyle.None, HeaderStyle = ColumnHeaderStyle.Nonclickable };
            for (int i = 0; i < cols.Length; i += 2) lv.Columns.Add((string)cols[i], App.S((int)cols[i + 1]));
            // ширина столбцов фиксированная: перетаскивать границы в шапке нельзя
            var widths = new int[lv.Columns.Count];
            for (int i = 0; i < widths.Length; i++) widths[i] = lv.Columns[i].Width;
            // последний столбец тянется ровно до края (иначе справа в шапке остаётся белая полоска)
            Action fill = () =>
            {
                int last = widths.Length - 1, used = 0;
                for (int i = 0; i < last; i++) used += widths[i];
                int fw = Math.Max(App.S(40), lv.ClientSize.Width - used);
                if (widths[last] != fw) { widths[last] = fw; lv.Columns[last].Width = fw; }
            };
            lv.ClientSizeChanged += (s, e) => fill();
            lv.HandleCreated += (s, e) => fill();
            lv.ColumnWidthChanging += (s, e) => { e.Cancel = true; e.NewWidth = widths[e.ColumnIndex]; };
            lv.ColumnWidthChanged += (s, e) => { if (lv.Columns[e.ColumnIndex].Width != widths[e.ColumnIndex]) lv.Columns[e.ColumnIndex].Width = widths[e.ColumnIndex]; };
            lv.AllowColumnReorder = false;
            // строки повыше: высоту строки ListView задаёт картинка-пустышка
            lv.SmallImageList = new ImageList { ImageSize = new Size(1, App.S(30)) };
            // своя отрисовка: шапка мелкими заглавными, выбранная строка с бирюзовой полоской слева
            lv.OwnerDraw = true;
            lv.DrawColumnHeader += (s, e) =>
            {
                using (var b = new SolidBrush(lv.BackColor)) e.Graphics.FillRectangle(b, e.Bounds);
                using (var b = new SolidBrush(App.Line)) e.Graphics.FillRectangle(b, e.Bounds.X, e.Bounds.Bottom - 1, e.Bounds.Width, 1);
                var r = e.Bounds; r.X += App.S(10);
                TextRenderer.DrawText(e.Graphics, e.Header.Text.ToUpper(), F(8f, FontStyle.Bold), r, App.Dim, TextFormatFlags.VerticalCenter | TextFormatFlags.Left);
            };
            lv.DrawItem += (s, e) => { };
            lv.DrawSubItem += (s, e) =>
            {
                bool sel = e.Item.Selected, first = e.ColumnIndex == 0;
                using (var b = new SolidBrush(sel ? App.SelRow : lv.BackColor)) e.Graphics.FillRectangle(b, e.Bounds);
                if (sel && first) using (var b = new SolidBrush(App.Sel)) e.Graphics.FillRectangle(b, e.Bounds.X, e.Bounds.Y, App.S(3), e.Bounds.Height);
                using (var b = new SolidBrush(App.Line)) e.Graphics.FillRectangle(b, e.Bounds.X, e.Bounds.Bottom - 1, e.Bounds.Width, 1);
                var r = e.Bounds; r.X += App.S(10); r.Width -= App.S(10);
                TextRenderer.DrawText(e.Graphics, e.SubItem.Text, sel && first ? F(9.5f, FontStyle.Bold) : lv.Font, r,
                    sel ? (first ? App.Text : App.Sel) : (first ? e.Item.ForeColor : App.Dim),
                    TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis);
            };
            parent.Controls.Add(lv); return lv;
        }

        public static void Style(Form f, string title, int w, int h)
        {
            f.Text = title; f.BackColor = App.Bg; f.ForeColor = App.Text; f.Font = F(9.5f);
            f.ClientSize = new Size(App.S(w), App.S(h)); f.FormBorderStyle = FormBorderStyle.FixedSingle; f.MaximizeBox = false;
            f.StartPosition = FormStartPosition.CenterScreen;
            try { f.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            f.HandleCreated += (s, e) => DarkTitle(f.Handle);
        }

        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        // тёмная полоса заголовка окна (Windows 10/11); на старых системах просто ничего не меняется
        static void DarkTitle(IntPtr h)
        {
            try
            {
                int on = 1, caption = 0x00140D0D, text = 0x00F5F2F2, border = 0x00382A2A; // 0x00BBGGRR
                DwmSetWindowAttribute(h, 20, ref on, 4);       // тёмный режим окна
                DwmSetWindowAttribute(h, 35, ref caption, 4);  // цвет заголовка = фон программы
                DwmSetWindowAttribute(h, 36, ref text, 4);     // цвет текста заголовка
                DwmSetWindowAttribute(h, 34, ref border, 4);   // рамка окна
            }
            catch { }
        }
    }

    // ---------- список тел на «стекле» ----------
    // Стандартный ListView не умеет быть прозрачным, поэтому список рисуем сами:
    // шапка мелкими заглавными, строки прямо на карточке, выбранная - с бирюзовой полоской слева.
    class BodyList : Control
    {
        public class Row { public string[] Cols; public object Tag; }
        public readonly List<Row> Rows = new List<Row>();
        public string[] Headers = new string[0];
        public float[] Widths = new float[0];   // доли ширины столбцов
        int sel = -1;
        public event EventHandler SelectedIndexChanged;
        public event EventHandler Activated;
        const int HeadH = 36, RowH = 44;

        public BodyList()
        {
            SetStyle(ControlStyles.SupportsTransparentBackColor | ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
            BackColor = Color.Transparent; ForeColor = App.Text; Font = UI.F(9.5f); Cursor = Cursors.Hand;
        }

        public int SelectedIndex
        {
            get { return sel; }
            set { int v = Rows.Count == 0 ? -1 : Math.Max(-1, Math.Min(Rows.Count - 1, value)); if (v == sel) return; sel = v; Invalidate(); if (SelectedIndexChanged != null) SelectedIndexChanged(this, EventArgs.Empty); }
        }
        public object SelectedTag { get { return sel >= 0 && sel < Rows.Count ? Rows[sel].Tag : null; } }
        public void Clear() { Rows.Clear(); sel = -1; Invalidate(); }
        public void Add(string[] cols, object tag) { Rows.Add(new Row { Cols = cols, Tag = tag }); Invalidate(); }

        int RowAt(int y) { int i = (y - App.S(HeadH)) / App.S(RowH); return y >= App.S(HeadH) && i < Rows.Count ? i : -1; }
        protected override void OnMouseDown(MouseEventArgs e) { Focus(); int i = RowAt(e.Y); if (i >= 0) SelectedIndex = i; base.OnMouseDown(e); }
        protected override void OnDoubleClick(EventArgs e) { if (sel >= 0 && Activated != null) Activated(this, e); base.OnDoubleClick(e); }
        protected override bool IsInputKey(Keys k) { return k == Keys.Up || k == Keys.Down || base.IsInputKey(k); }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Down) SelectedIndex = sel + 1;
            else if (e.KeyCode == Keys.Up) SelectedIndex = Math.Max(0, sel - 1);
            else if (e.KeyCode == Keys.Enter && sel >= 0 && Activated != null) Activated(this, e);
            base.OnKeyDown(e);
        }

        int[] ColX(int pad)
        {
            float total = Widths.Sum(); var xs = new int[Widths.Length + 1]; xs[0] = pad; float acc = 0;
            for (int i = 0; i < Widths.Length; i++) { acc += Widths[i]; xs[i + 1] = pad + (int)((Width - 2 * pad) * acc / total); }
            return xs;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics; int pad = App.S(18), hh = App.S(HeadH), rh = App.S(RowH);
            var xs = ColX(pad);
            var flags = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding;
            using (var hf = UI.F(8f, FontStyle.Bold))
                for (int c = 0; c < Headers.Length && c < Widths.Length; c++)
                    TextRenderer.DrawText(g, Headers[c].ToUpper(), hf, new Rectangle(xs[c], 0, xs[c + 1] - xs[c] - App.S(8), hh), App.Dim, flags);
            using (var line = new SolidBrush(Color.FromArgb(40, 255, 255, 255))) g.FillRectangle(line, 0, hh - 1, Width, 1);
            using (var bold = UI.F(9.5f, FontStyle.Bold))
            using (var line = new SolidBrush(Color.FromArgb(22, 255, 255, 255)))
                for (int i = 0; i < Rows.Count; i++)
                {
                    int y = hh + i * rh; bool s = i == sel;
                    if (s)
                    {
                        using (var b = new SolidBrush(Color.FromArgb(46, App.Sel))) g.FillRectangle(b, 0, y, Width, rh);
                        using (var b = new SolidBrush(App.Sel)) g.FillRectangle(b, 0, y, App.S(3), rh);
                    }
                    else if (i < Rows.Count - 1) g.FillRectangle(line, 0, y + rh - 1, Width, 1);
                    for (int c = 0; c < Rows[i].Cols.Length && c < Widths.Length; c++)
                        TextRenderer.DrawText(g, Rows[i].Cols[c], s && c == 0 ? bold : Font, new Rectangle(xs[c], y, xs[c + 1] - xs[c] - App.S(8), rh),
                            c == 0 ? App.Text : (s ? App.Sel : App.Dim), flags);
                }
            if (Rows.Count == 0)
                TextRenderer.DrawText(g, App.T("Тел пока нет - нажми «+ Добавить тело»", "No bodies yet - press \"+ Add body\""), Font,
                    new Rectangle(pad, hh, Width - 2 * pad, rh * 2), App.Dim, flags);
        }
    }

    class GlowPanel : Panel
    {
        public GlowPanel()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        }
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            var f = FindForm() as MainForm;
            if (f == null) { base.OnPaintBackground(e); return; }
            var at = f.PointToClient(PointToScreen(Point.Empty));
            f.PaintGlow(e.Graphics, at);
        }
    }

    // ---------- главное окно ----------
    class MainForm : Form
    {
        Dictionary<string, object> cfg;
        Panel main, setup;
        BodyList bodies;
        Label bodyLabel, status, studioHint;
        Button openStudio, renameBtn, deleteBtn, femBtn, maleBtn;
        // настройки
        Label blStatus, wkStatus, gmStatus;
        TextBox blPath, wkPath, gmPath, outPath;
        ListBox sources;
        Button doneBtn, wkDownload;
        string blenderVer = "";

        public MainForm()
        {
            UI.Style(this, "Refit Studio", 820, 586);
            DoubleBuffered = true;
            cfg = App.LoadConfig();
            // шапка: значок «R», название техно-шрифтом, подзаголовок и кнопка настроек
            var logo = UI.Card(this, 28, 20, 38, 38);
            logo.Controls.Add(new Label { Text = "R", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, Font = UI.Tech(16f), ForeColor = App.Accent, BackColor = Color.Transparent });
            var title = UI.Label(this, "REFIT STUDIO", 78, 17, 260, 28, 9f);
            title.Font = UI.Tech(17f);
            UI.Label(this, App.T("Подгонка одежды Cyberpunk 2077 под твоё тело", "Cyberpunk 2077 clothing refits for your body"), 79, 43, 440, 20, 9f, App.Dim);
            UI.Glass(this, App.T("Настройки", "Settings"), 676, 22, 116, 34, (s, e) => ShowSetup(true));
            status = UI.Label(this, "", 28, 554, 764, 22, 9f, App.Dim);
            BuildMain();
            BuildSetup();
            Shown += (s, e) => Start();
        }

        void Start()
        {
            bool changed = false;
            if (!App.BlenderOk(App.Str(cfg, "blender"))) { var b = App.FindBlender(); if (b != "") { cfg["blender"] = b; changed = true; } }
            if (!App.WkOk(App.Str(cfg, "wolvenkit"))) { var w = App.FindWolvenKit(); if (w != "") { cfg["wolvenkit"] = w; changed = true; } }
            if (!App.GameOk(App.Str(cfg, "game"))) { var g = App.FindGame(); if (g != "") { cfg["game"] = g; changed = true; } }
            if (App.List(cfg, "sources").Count == 0) { cfg["sources"] = App.FindModSources(App.Str(cfg, "game")); changed = true; }
            if (App.Str(cfg, "output") == "") { cfg["output"] = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory); changed = true; }
            if (changed) App.SaveConfig(cfg);
            CheckBlenderVersion();
            RefreshSetup();
            RefreshBodies();
            ShowSetup(!SetupOk());
            if (Environment.GetCommandLineArgs().Contains("--add-body") && SetupOk()) AddBody();
            if (Environment.GetCommandLineArgs().Contains("--setup")) ShowSetup(true);
        }

        bool SetupOk()
        {
            return App.BlenderOk(App.Str(cfg, "blender")) && App.WkOk(App.Str(cfg, "wolvenkit")) && App.GameOk(App.Str(cfg, "game"))
                && App.List(cfg, "sources").Count > 0 && (blenderVer == "" || App.BlenderNewEnough(blenderVer));
        }

        void CheckBlenderVersion()
        {
            string exe = App.Str(cfg, "blender");
            blenderVer = App.BlenderOk(exe) ? App.BlenderVersion(exe) : "";
        }

        void ShowSetup(bool on)
        {
            RefreshSetup();
            setup.Visible = on; main.Visible = !on;
            status.Text = on ? App.T("Укажи, где лежат программы. Обычно всё находится само.", "Point to the programs. Usually everything is found automatically.") : "";
        }

        // ---------- шаги ----------
        // фон окна: почти чёрный с двумя мягкими пятнами света - бирюзовым слева сверху и жёлтым справа снизу
        protected override void OnPaintBackground(PaintEventArgs e) { PaintGlow(e.Graphics, Point.Empty); }

        // origin - где лежит рисующий элемент внутри окна (окно: 0,0; панель: её место)
        public void PaintGlow(Graphics g, Point origin)
        {
            var state = g.Save();
            g.TranslateTransform(-origin.X, -origin.Y);
            using (var b = new SolidBrush(App.Bg)) g.FillRectangle(b, 0, 0, ClientSize.Width, ClientSize.Height);
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            UI.Glow(g, new Rectangle(-App.S(330), -App.S(380), App.S(900), App.S(900)), App.Sel, 105);
            UI.Glow(g, new Rectangle(ClientSize.Width - App.S(470), ClientSize.Height - App.S(430), App.S(820), App.S(820)), App.Accent, 72);
            g.Restore(state);
        }

        void BuildMain()
        {
            main = new GlowPanel { Left = 0, Top = App.S(76), Width = ClientSize.Width, Height = App.S(470), BackColor = App.Bg };
            Controls.Add(main);
            // раздел «Тела» с бирюзовым подчёркиванием, как вкладка
            var tab = UI.Label(main, App.T("Тела", "Bodies"), 28, 0, 70, 26, 10.5f, App.Text, FontStyle.Bold);
            main.Controls.Add(new Panel { Left = App.S(28), Top = App.S(28), Width = Math.Max(App.S(40), tab.PreferredWidth), Height = App.S(2), BackColor = App.Sel });
            // переключатель пола: список тел, «Добавить тело» и мастерская работают с выбранным
            femBtn = UI.Glass(main, App.T("Женский V", "Female V"), 110, 0, 100, 26, (s, e) => SetGender("female"));
            maleBtn = UI.Glass(main, App.T("Мужской V", "Male V"), 214, 0, 100, 26, (s, e) => SetGender("male"));
            PaintGender();
            main.Controls.Add(new Panel { Left = App.S(28), Top = App.S(30), Width = App.S(764), Height = 1, BackColor = App.Line });
            // действия с телами - маленькими стеклянными кнопками справа от «Тела»
            UI.Glass(main, App.T("+ Добавить тело", "+ Add body"), 462, 0, 130, 26, (s, e) => AddBody());
            renameBtn = UI.Glass(main, App.T("Переименовать", "Rename"), 600, 0, 110, 26, (s, e) => RenameBody());
            deleteBtn = UI.Glass(main, App.T("Удалить", "Delete"), 718, 0, 74, 26, (s, e) => DeleteBody());
            UI.Label(main, App.T("Под какое тело делать рефиты. Тело берётся из установленного мода тела.", "Which body to make refits for. The body is taken from an installed body mod."), 28, 40, 740, 20, 9f, App.Dim);

            var c1 = UI.Card(main, 28, 68, 764, 244);
            bodies = new BodyList { Left = 1, Top = App.S(4), Width = App.S(762), Height = App.S(236),
                Headers = new[] { App.T("Тело", "Body"), App.T("Тип", "Type"), App.T("Что меняет", "Changes"), App.T("Создано", "Created") },
                Widths = new[] { 3.2f, 1.2f, 1.5f, 1f } };
            c1.Controls.Add(bodies);
            bodies.SelectedIndexChanged += (s, e) => OnBodySelected();
            bodies.Activated += (s, e) => OpenStudio();

            var c2 = UI.Card(main, 28, 328, 764, 112);
            bodyLabel = UI.Label(c2, "", 20, 22, 470, 24, 11f, App.Text, FontStyle.Bold);
            studioHint = UI.Label(c2, "", 20, 50, 470, 50, 9f, App.Dim);
            openStudio = UI.Button(c2, App.T("Открыть мастерскую", "Open workshop"), 500, 28, 244, 56, (s, e) => OpenStudio(), true);
        }

        List<Dictionary<string, object>> profiles = new List<Dictionary<string, object>>();

        void SetGender(string g)
        {
            if (App.Gender(cfg) == g) return;
            cfg["gender"] = g; App.SaveConfig(cfg);
            PaintGender();
            RefreshBodies();
            status.Text = g == "male" ? App.T("Мужской V: тела и одежда для мужского V.", "Male V: bodies and clothing for male V.")
                                      : App.T("Женский V: тела и одежда для женского V.", "Female V: bodies and clothing for female V.");
        }

        // выбранный пол - сплошная бирюзовая «таблетка», как выбранная вкладка в мастерской
        void PaintGender()
        {
            string g = App.Gender(cfg);
            foreach (var b in new[] { femBtn, maleBtn })
            {
                bool on = (b == maleBtn) == (g == "male");
                b.BackColor = on ? App.Sel : Color.FromArgb(14, 255, 255, 255);
                b.ForeColor = on ? App.Bg : App.Text;
                b.FlatAppearance.MouseOverBackColor = on ? App.Sel : Color.FromArgb(34, 255, 255, 255);
                b.FlatAppearance.MouseDownBackColor = on ? App.Sel : Color.FromArgb(50, 255, 255, 255);
                b.Invalidate();
            }
        }

        void RefreshBodies(string select = null)
        {
            profiles.Clear(); bodies.Clear();
            string gender = App.Gender(cfg);
            if (Directory.Exists(App.Profiles))
                foreach (var d in Directory.GetDirectories(App.Profiles).OrderBy(x => x))
                {
                    string pj = Path.Combine(d, "profile.json");
                    if (!File.Exists(pj) || !File.Exists(Path.Combine(d, "body.npz"))) continue;
                    try
                    {
                        var p = App.Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(pj, Encoding.UTF8));
                        if ((App.Str(p, "gender") == "male" ? "male" : "female") == gender) profiles.Add(p);
                    }
                    catch { }
                }
            string cur = select ?? App.Str(cfg, "profile");
            foreach (var p in profiles)
            {
                var parts = new List<string>();
                object po;
                if (p.TryGetValue("parts", out po) && po is Dictionary<string, object>)
                {
                    var pd = (Dictionary<string, object>)po;
                    if (pd.ContainsKey("torso") && (string)pd["torso"] == "changed") parts.Add(App.T("тело", "body"));
                    if ((pd.ContainsKey("arm_l") && (string)pd["arm_l"] == "changed") || (pd.ContainsKey("arm_r") && (string)pd["arm_r"] == "changed")) parts.Add(App.T("руки", "arms"));
                    if (pd.ContainsKey("feet") && (string)pd["feet"] == "changed") parts.Add(App.T("ступни", "feet"));
                }
                string tag = App.Str(p, "tag");
                string created = App.Str(p, "created");
                bodies.Add(new[] { App.CleanName(App.Str(p, "name")), tag == "" ? App.T("замена обычного", "replaces vanilla") : tag,
                    string.Join(", ", parts), created.Length >= 10 ? created.Substring(8, 2) + "." + created.Substring(5, 2) + "." + created.Substring(0, 4) : "" }, p);
                if (App.Str(p, "id") == cur) bodies.SelectedIndex = bodies.Rows.Count - 1;
            }
            if (bodies.SelectedIndex < 0 && bodies.Rows.Count > 0) bodies.SelectedIndex = 0;
            OnBodySelected();
        }

        Dictionary<string, object> Selected()
        {
            return bodies.SelectedTag as Dictionary<string, object>;
        }

        void OnBodySelected()
        {
            var p = Selected();
            renameBtn.Enabled = deleteBtn.Enabled = openStudio.Enabled = p != null;
            if (p == null)
            {
                bodyLabel.Text = App.T("Тело не выбрано", "No body selected");
                studioHint.Text = profiles.Count == 0 ? App.T("Сначала добавь тело в шаге 1: выбери мод тела из своих модов.", "First add a body in step 1: pick a body mod from your mods.") : App.T("Выбери тело в списке выше.", "Select a body in the list above.");
                return;
            }
            bodyLabel.Text = App.T("Тело: ", "Body: ") + App.CleanName(App.Str(p, "name"));
            string tag = App.Str(p, "tag");
            studioHint.Text = tag != ""
                ? App.T("Рефиты будут для типа тела «" + tag + "»: моды одежды с поддержкой ArchiveXL сами возьмут нужную версию.",
                        "Refits will be for body type \"" + tag + "\": ArchiveXL clothing mods pick the right version automatically.")
                : App.T("Мод тела заменяет обычное тело, поэтому рефит заменит обычную версию вещи.", "The body mod replaces the vanilla body, so the refit replaces the vanilla version of the item.");
            if (App.Str(cfg, "profile") != App.Str(p, "id")) { cfg["profile"] = App.Str(p, "id"); App.SaveConfig(cfg); }
        }

        void AddBody()
        {
            using (var f = new AddBodyForm(cfg))
                if (f.ShowDialog(this) == DialogResult.OK) { RefreshBodies(f.CreatedId); status.Text = App.T("Тело добавлено.", "Body added."); }
        }

        void RenameBody()
        {
            var p = Selected(); if (p == null) return;
            string name = Prompt.Ask(this, App.T("Название тела", "Body name"), App.T("Как назвать это тело в списке:", "Name of this body in the list:"), App.CleanName(App.Str(p, "name")));
            if (string.IsNullOrWhiteSpace(name)) return;
            p["name"] = name.Trim();
            string pj = Path.Combine(App.Profiles, App.Str(p, "id"), "profile.json");
            File.WriteAllText(pj, App.Json.Serialize(p), new UTF8Encoding(false));
            RefreshBodies(App.Str(p, "id"));
        }

        void DeleteBody()
        {
            var p = Selected(); if (p == null) return;
            if (MessageBox.Show(this, App.T("Удалить профиль тела «" + App.CleanName(App.Str(p, "name")) + "» из Refit Studio?\n\n" +
                "Сам мод тела и готовые рефиты не тронутся, удалится только профиль (его можно создать заново).",
                "Delete the body profile \"" + App.CleanName(App.Str(p, "name")) + "\" from Refit Studio?\n\n" +
                "The body mod itself and your refits stay untouched, only the profile is removed (you can create it again)."),
                App.T("Удалить тело", "Delete body"), MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
            try { Directory.Delete(Path.Combine(App.Profiles, App.Str(p, "id")), true); }
            catch (Exception ex) { MessageBox.Show(this, App.T("Не получилось удалить: ", "Could not delete: ") + ex.Message); }
            RefreshBodies();
        }

        void OpenStudio()
        {
            var p = Selected(); if (p == null) return;
            if (!SetupOk()) { ShowSetup(true); return; }
            string studio = Path.Combine(App.Core, "studio.py");
            if (!File.Exists(studio)) { MessageBox.Show(this, App.T("Не найден файл ", "File not found: ") + studio + App.T(". Переустанови Refit Studio.", ". Reinstall Refit Studio.")); return; }
            try
            {
                // пустая сцена из папки программы: с открытым файлом Blender не показывает заставку
                string scene = Path.Combine(App.Core, "studio.blend");
                var psi = new ProcessStartInfo(App.Str(cfg, "blender"),
                    (File.Exists(scene) ? "\"" + scene + "\" " : "") +
                    "--python \"" + studio + "\" -- --profile \"" + App.Str(p, "id") + "\"") { UseShellExecute = false, WorkingDirectory = App.Core };
                Process.Start(psi);
                status.Text = App.T("Мастерская открывается в Blender (пара секунд)...", "The workshop is opening in Blender (a few seconds)...");
                WindowState = FormWindowState.Minimized;
            }
            catch (Exception ex) { MessageBox.Show(this, App.T("Не удалось запустить Blender: ", "Could not start Blender: ") + ex.Message); }
        }

        // ---------- настройки ----------
        void BuildSetup()
        {
            setup = new GlowPanel { Left = 0, Top = App.S(76), Width = ClientSize.Width, Height = App.S(470), BackColor = App.Bg };
            Controls.Add(setup);
            var c = UI.Card(setup, 28, 0, 764, 462);
            UI.Heading(c, App.T("Настройки", "Settings"), 18, 14);
            int y = 50;
            blStatus = Row(c, App.T("Blender 4.2 или новее", "Blender 4.2 or newer"), ref y, out blPath, PickBlender, App.T("Скачать", "Download"), (s, e) => Process.Start("https://www.blender.org/download/"));
            wkStatus = Row(c, "WolvenKit CLI", ref y, out wkPath, PickWk, App.T("Скачать", "Download"), (s, e) => DownloadWk());
            wkDownload = (Button)c.Controls[c.Controls.Count - 1];
            gmStatus = Row(c, "Cyberpunk 2077", ref y, out gmPath, PickGame, null, null);

            UI.Label(c, App.T("Папки с модами (Vortex, MO2, archive\\pc\\mod игры)", "Mod folders (Vortex, MO2, game archive\\pc\\mod)"), 18, y, 500, 20, 9.5f);
            sources = new ListBox { Left = App.S(18), Top = App.S(y + 24), Width = App.S(560), Height = App.S(84), BackColor = App.Field,
                ForeColor = App.Text, BorderStyle = BorderStyle.FixedSingle, Font = UI.F(9f), HorizontalScrollbar = true };
            c.Controls.Add(sources);
            UI.Button(c, App.T("Добавить папку", "Add folder"), 590, y + 24, 156, 30, (s, e) => AddSource());
            UI.Button(c, App.T("Убрать", "Remove"), 590, y + 58, 156, 30, (s, e) => { if (sources.SelectedIndex >= 0) { var l = App.List(cfg, "sources"); l.RemoveAt(sources.SelectedIndex); cfg["sources"] = l; App.SaveConfig(cfg); RefreshSetup(); } });
            y += 120;
            UI.Label(c, App.T("Куда класть готовые рефиты (.zip)", "Where to put finished refits (.zip)"), 18, y, 500, 20, 9.5f);
            outPath = UI.Box(c, 18, y + 24, 560);
            UI.Button(c, App.T("Указать…", "Browse…"), 590, y + 22, 156, 28, (s, e) => PickOutput());
            // язык - в правом верхнем углу карточки, выбранный подсвечен
            UI.Button(c, "English", 518, 10, 110, 28, (s, e) => SetLang("en"), App.Lang == "en");
            UI.Button(c, "Русский", 636, 10, 110, 28, (s, e) => SetLang("ru"), App.Lang == "ru");
            doneBtn = UI.Button(c, App.T("Готово", "Done"), 590, 410, 156, 38, (s, e) => { if (SetupOk()) { ShowSetup(false); RefreshBodies(); } }, true);
        }

        Label Row(Control c, string title, ref int y, out TextBox box, EventHandler pick, string extra, EventHandler extraClick)
        {
            UI.Label(c, title, 18, y, 300, 20, 9.5f);
            var st = UI.Label(c, "", 330, y, 248, 20, 9f, App.Dim);
            st.TextAlign = ContentAlignment.TopRight;
            box = UI.Box(c, 18, y + 24, 560);
            UI.Button(c, App.T("Указать…", "Browse…"), 590, y + 22, extra == null ? 156 : 70, 28, pick);
            if (extra != null) UI.Button(c, extra, 664, y + 22, 82, 28, extraClick);
            y += 62;
            return st;
        }

        void SetStatus(Label l, bool ok, string okText, string badText)
        {
            l.Text = ok ? "✓ " + okText : "✗ " + badText; l.ForeColor = ok ? App.Good : App.Bad;
        }

        void RefreshSetup()
        {
            blPath.Text = App.Str(cfg, "blender"); wkPath.Text = App.Str(cfg, "wolvenkit"); gmPath.Text = App.Str(cfg, "game");
            outPath.Text = App.Str(cfg, "output");
            bool bl = App.BlenderOk(blPath.Text);
            if (bl && blenderVer != "" && !App.BlenderNewEnough(blenderVer)) SetStatus(blStatus, false, "", App.T("версия ", "version ") + blenderVer + App.T(" - нужна 4.2+", " - 4.2+ needed"));
            else SetStatus(blStatus, bl, App.T("найден", "found") + (blenderVer != "" ? " (" + blenderVer + ")" : ""), App.T("не найден", "not found"));
            SetStatus(wkStatus, App.WkOk(wkPath.Text), App.T("найден", "found"), App.T("не найден", "not found"));
            SetStatus(gmStatus, App.GameOk(gmPath.Text), App.T("найдена", "found"), App.T("не найдена", "not found"));
            sources.Items.Clear();
            foreach (var s in App.List(cfg, "sources")) sources.Items.Add(s);
            doneBtn.Enabled = SetupOk();
        }

        string PickFile(string title, string filter, string start)
        {
            using (var d = new OpenFileDialog { Title = title, Filter = filter })
            {
                try { if (start != "" && Directory.Exists(Path.GetDirectoryName(start))) d.InitialDirectory = Path.GetDirectoryName(start); } catch { }
                return d.ShowDialog(this) == DialogResult.OK ? d.FileName : null;
            }
        }

        string PickFolder(string title)
        {
            using (var d = new FolderBrowserDialog { Description = title, ShowNewFolderButton = false })
                return d.ShowDialog(this) == DialogResult.OK ? d.SelectedPath : null;
        }

        void PickBlender(object s, EventArgs e)
        {
            var f = PickFile(App.T("Где лежит blender.exe", "Where is blender.exe"), "Blender|blender.exe", App.Str(cfg, "blender"));
            if (f == null) return;
            cfg["blender"] = f; App.SaveConfig(cfg); CheckBlenderVersion(); RefreshSetup();
        }

        void PickWk(object s, EventArgs e)
        {
            var f = PickFile(App.T("Где лежит WolvenKit.CLI.exe (консольная версия WolvenKit)", "Where is WolvenKit.CLI.exe (the console version of WolvenKit)"), "WolvenKit CLI|WolvenKit.CLI.exe;WolvenKit.Console.exe|" + App.T("Все .exe", "All .exe") + "|*.exe", App.Str(cfg, "wolvenkit"));
            if (f == null) return;
            cfg["wolvenkit"] = f; App.SaveConfig(cfg); RefreshSetup();
        }

        void PickGame(object s, EventArgs e)
        {
            var d = PickFolder(App.T("Папка игры Cyberpunk 2077 (в ней есть bin и archive)", "Cyberpunk 2077 game folder (it contains bin and archive)"));
            if (d == null) return;
            if (!App.GameOk(d)) { MessageBox.Show(this, App.T("В этой папке нет bin\\x64\\Cyberpunk2077.exe. Выбери корневую папку игры.", "This folder has no bin\\x64\\Cyberpunk2077.exe. Choose the root game folder.")); return; }
            cfg["game"] = d;
            var l = App.List(cfg, "sources"); string gm = Path.Combine(d, @"archive\pc\mod");
            if (l.Count == 0 && Directory.Exists(gm)) { l.Add(gm); cfg["sources"] = l; }
            App.SaveConfig(cfg); RefreshSetup();
        }

        void SetLang(string lang)
        {
            if (lang == App.Lang) return;
            cfg["lang"] = lang; App.SaveConfig(cfg);
            Application.Restart(); // все надписи создаются заново на новом языке
            Environment.Exit(0);
        }

        void PickOutput()
        {
            var d = PickFolder(App.T("Куда сохранять готовые рефиты", "Where to save finished refits"));
            if (d == null) return;
            cfg["output"] = d; App.SaveConfig(cfg); RefreshSetup();
        }

        void AddSource()
        {
            var d = PickFolder(App.T("Папка с модами: staging-папка Vortex, папка mods в MO2 или archive\\pc\\mod игры", "Mod folder: the Vortex staging folder, the MO2 mods folder or the game archive\\pc\\mod"));
            if (d == null) return;
            var l = App.List(cfg, "sources");
            if (!l.Contains(d, StringComparer.OrdinalIgnoreCase)) l.Add(d);
            cfg["sources"] = l; App.SaveConfig(cfg); RefreshSetup();
        }

        void DownloadWk()
        {
            if (MessageBox.Show(this, App.T("Скачать WolvenKit CLI с официальной страницы проекта на GitHub (github.com/WolvenKit/WolvenKit, около 60 МБ)?\n\n" +
                "Он распакуется в " + Path.Combine(App.Data, @"tools\wolvenkit") + " и в систему ничего не установит.",
                "Download WolvenKit CLI from the official project page on GitHub (github.com/WolvenKit/WolvenKit, about 60 MB)?\n\n" +
                "It will be unpacked to " + Path.Combine(App.Data, @"tools\wolvenkit") + " and nothing is installed into Windows."),
                "WolvenKit CLI", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
            wkDownload.Enabled = false; wkStatus.Text = App.T("скачиваю...", "downloading..."); wkStatus.ForeColor = App.Dim;
            new Thread(() =>
            {
                string err = null, exe = null;
                try { exe = WkDownloader.Run(p => BeginInvoke((Action)(() => wkStatus.Text = App.T("скачиваю... ", "downloading... ") + p + "%"))); }
                catch (Exception ex) { err = ex.Message; }
                BeginInvoke((Action)(() =>
                {
                    wkDownload.Enabled = true;
                    if (exe != null) { cfg["wolvenkit"] = exe; App.SaveConfig(cfg); }
                    else MessageBox.Show(this, App.T("Не получилось скачать: ", "Download failed: ") + err + App.T("\n\nСкачай WolvenKit Console вручную со страницы релизов WolvenKit на GitHub и укажи WolvenKit.CLI.exe.", "\n\nDownload WolvenKit Console manually from the WolvenKit releases page on GitHub and point to WolvenKit.CLI.exe."));
                    RefreshSetup();
                }));
            }) { IsBackground = true }.Start();
        }
    }

    static class WkDownloader
    {
        public static string Run(Action<int> progress)
        {
            var wc = new WebClient();
            wc.Headers[HttpRequestHeader.UserAgent] = "RefitStudio";
            string json = wc.DownloadString("https://api.github.com/repos/WolvenKit/WolvenKit/releases/latest");
            var rel = App.Json.Deserialize<Dictionary<string, object>>(json);
            string url = null;
            foreach (var a in (System.Collections.ArrayList)rel["assets"])
            {
                var ad = (Dictionary<string, object>)a; string n = ((string)ad["name"]).ToLower();
                if (n.Contains("console") && n.EndsWith(".zip")) { url = (string)ad["browser_download_url"]; break; }
            }
            if (url == null) throw new Exception(App.T("в последнем релизе нет архива WolvenKit.Console", "the latest release has no WolvenKit.Console archive"));
            string dir = Path.Combine(App.Data, @"tools\wolvenkit"), zip = dir + ".zip";
            Directory.CreateDirectory(Path.GetDirectoryName(zip));
            var done = new ManualResetEvent(false); Exception dlErr = null;
            var wc2 = new WebClient(); wc2.Headers[HttpRequestHeader.UserAgent] = "RefitStudio";
            wc2.DownloadProgressChanged += (s, e) => progress(e.ProgressPercentage);
            wc2.DownloadFileCompleted += (s, e) => { dlErr = e.Error; done.Set(); };
            wc2.DownloadFileAsync(new Uri(url), zip);
            done.WaitOne();
            if (dlErr != null) throw dlErr;
            if (Directory.Exists(dir)) Directory.Delete(dir, true);
            System.IO.Compression.ZipFile.ExtractToDirectory(zip, dir);
            File.Delete(zip);
            var exe = Directory.GetFiles(dir, "WolvenKit.CLI.exe", SearchOption.AllDirectories).FirstOrDefault();
            if (exe == null) throw new Exception(App.T("в архиве нет WolvenKit.CLI.exe", "the archive has no WolvenKit.CLI.exe"));
            return exe;
        }
    }

    // ---------- добавление тела ----------
    class AddBodyForm : Form
    {
        readonly Dictionary<string, object> cfg;
        List<Mod> mods = new List<Mod>();
        ListView list;
        TextBox search, nameBox;
        CheckBox showAll;
        Button create, manual;
        ProgressBar bar;
        Label info, prog;
        public string CreatedId;
        Process proc;
        string manualPath;
        readonly string gender;

        public AddBodyForm(Dictionary<string, object> cfg)
        {
            this.cfg = cfg;
            gender = App.Gender(cfg);
            UI.Style(this, App.T("Добавить тело", "Add body"), 720, 560);
            UI.Label(this, gender == "male" ? App.T("Выбери мод тела мужского V", "Choose a male V body mod") : App.T("Выбери мод тела женского V", "Choose a female V body mod"), 22, 16, 500, 26, 11f, App.Text, FontStyle.Bold);
            UI.Label(this, App.T("Моды, которые меняют тело V, отмечены звёздочкой и стоят сверху.", "Mods that change V's body are marked with a star and listed first."), 22, 44, 660, 20, 9.5f, App.Dim);
            search = UI.Box(this, 22, 72, 420, false);
            search.TextChanged += (s, e) => Fill();
            showAll = new CheckBox { Text = App.T("Показать все моды", "Show all mods"), Left = App.S(460), Top = App.S(72), Width = App.S(240), ForeColor = App.Text, Font = UI.F(9.5f) };
            showAll.CheckedChanged += (s, e) => Fill();
            Controls.Add(showAll);
            list = UI.List(this, 22, 104, 676, 270, App.T("Мод", "Mod"), 450, App.T("Что меняет", "Changes"), 222);
            list.SelectedIndexChanged += (s, e) => OnPick();
            list.DoubleClick += (s, e) => Build();
            manual = UI.Button(this, App.T("Указать мод вручную…", "Choose mod manually…"), 22, 384, 200, 30, (s, e) => PickManual());
            info = UI.Label(this, "", 232, 390, 466, 20, 9f, App.Dim);
            UI.Label(this, App.T("Название в списке тел", "Name in the body list"), 22, 428, 300, 20, 9.5f);
            nameBox = UI.Box(this, 22, 452, 420, false);
            create = UI.Button(this, App.T("Создать профиль тела", "Create body profile"), 458, 444, 240, 40, (s, e) => Build(), true);
            bar = new ProgressBar { Left = App.S(22), Top = App.S(500), Width = App.S(676), Height = App.S(10), Visible = false };
            Controls.Add(bar);
            prog = UI.Label(this, "", 22, 516, 676, 36, 9f, App.Dim);
            create.Enabled = false;
            FormClosing += (s, e) => { if (proc != null && !proc.HasExited) { e.Cancel = true; prog.Text = App.T("Подожди, профиль ещё собирается...", "Please wait, the profile is still being built..."); } };
            Shown += (s, e) => Scan();
        }

        void Scan()
        {
            prog.Text = App.T("Ищу моды...", "Looking for mods...");
            var src = App.List(cfg, "sources");
            new Thread(() =>
            {
                var found = Mod.Scan(src);
                foreach (var m in found) m.Detect(gender);
                BeginInvoke((Action)(() =>
                {
                    mods = found;
                    int n = mods.Count(m => m.IsBody);
                    prog.Text = App.T("Модов: ", "Mods: ") + mods.Count + App.T(", из них меняют тело: ", ", body mods among them: ") + n + "." +
                        (n == 0 ? App.T(" Модов тела не нашлось - проверь папки с модами в настройках или укажи мод вручную.",
                                        " No body mods found - check the mod folders in Settings or choose a mod manually.") : "");
                    Fill();
                }));
            }) { IsBackground = true }.Start();
        }

        void Fill()
        {
            list.BeginUpdate(); list.Items.Clear();
            string q = search.Text.Trim().ToLower();
            foreach (var m in mods.OrderBy(m => m.Parts.Contains(App.PartBody) ? 0 : m.IsBody ? 1 : 2).ThenBy(m => m.Name, StringComparer.OrdinalIgnoreCase))
            {
                if (!m.IsBody && !showAll.Checked) continue;
                if (q != "" && !m.Name.ToLower().Contains(q)) continue;
                var it = new ListViewItem(new[] { (m.IsBody ? "★  " : "     ") + App.CleanName(m.Name), m.IsBody ? string.Join(", ", m.Parts) : "—" });
                it.Tag = m; if (!m.IsBody) it.ForeColor = App.Dim;
                list.Items.Add(it);
            }
            list.EndUpdate();
        }

        void OnPick()
        {
            if (list.SelectedItems.Count == 0) return;
            var m = (Mod)list.SelectedItems[0].Tag;
            manualPath = null;
            nameBox.Text = App.CleanName(m.Name);
            info.Text = m.IsBody ? "" : App.T("В этом моде нет моделей тела - профиль не соберётся.", "This mod has no body models - a profile cannot be built.");
            create.Enabled = proc == null;
        }

        void PickManual()
        {
            using (var d = new OpenFileDialog { Title = App.T("Архив мода тела (.archive)", "Body mod archive (.archive)"), Filter = App.T("Архив мода", "Mod archive") + "|*.archive" })
            {
                if (d.ShowDialog(this) != DialogResult.OK) return;
                manualPath = d.FileName;
                var m = new Mod { Name = Path.GetFileNameWithoutExtension(d.FileName), Path = d.FileName };
                m.Archives.Add(d.FileName); m.Detect(gender);
                list.SelectedItems.Clear();
                nameBox.Text = App.CleanName(m.Name);
                info.Text = m.IsBody ? App.T("Меняет: ", "Changes: ") + string.Join(", ", m.Parts) : App.T("В этом архиве нет моделей тела.", "This archive has no body models.");
                create.Enabled = proc == null;
            }
        }

        void Build()
        {
            string path = manualPath;
            if (path == null && list.SelectedItems.Count > 0) path = ((Mod)list.SelectedItems[0].Tag).Path;
            if (path == null || proc != null) return;
            string blender = App.Str(cfg, "blender"), script = Path.Combine(App.Core, "build_profile.py");
            create.Enabled = manual.Enabled = false; // таблицу не блокируем: заблокированная рисуется белой
            bar.Visible = true; bar.Value = 0; prog.ForeColor = App.Dim; prog.Text = App.T("Запускаю...", "Starting...");
            var psi = new ProcessStartInfo(blender, "-b --factory-startup --python \"" + script + "\" -- --mod \"" + path.TrimEnd('\\') + "\" --name \"" + nameBox.Text.Replace("\"", "'") + "\" --gender " + gender)
            { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true,
              StandardOutputEncoding = Encoding.UTF8, WorkingDirectory = App.Core };
            string error = null, ok = null;
            try
            {
                proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
                proc.OutputDataReceived += (s, e) =>
                {
                    if (e.Data == null) return;
                    string line = e.Data;
                    if (line.StartsWith("@@P "))
                    {
                        var m = Regex.Match(line, @"^@@P (\d+) (.*)$");
                        if (m.Success) BeginInvoke((Action)(() => { bar.Value = Math.Min(100, int.Parse(m.Groups[1].Value)); prog.Text = m.Groups[2].Value; }));
                    }
                    else if (line.StartsWith("@@OK ")) ok = line.Substring(5).Trim();
                    else if (line.StartsWith("@@E ")) error = line.Substring(4).Trim();
                };
                proc.ErrorDataReceived += (s, e) => { };
                proc.Exited += (s, e) => { try { proc.WaitForExit(); } catch { } BeginInvoke((Action)(() =>
                {
                    proc = null; bar.Visible = false;
                    if (ok != null) { CreatedId = ok; DialogResult = DialogResult.OK; Close(); return; }
                    prog.ForeColor = App.Bad;
                    prog.Text = error ?? App.T("Сборка профиля прервалась. Подробности в ", "Profile build stopped. Details in ") + Path.Combine(App.Data, "log.txt");
                    create.Enabled = manual.Enabled = true;
                })); };
                proc.Start(); proc.BeginOutputReadLine(); proc.BeginErrorReadLine();
            }
            catch (Exception ex)
            {
                proc = null; bar.Visible = false; prog.ForeColor = App.Bad; prog.Text = App.T("Не удалось запустить Blender: ", "Could not start Blender: ") + ex.Message;
                create.Enabled = manual.Enabled = true;
            }
        }
    }

    static class Prompt
    {
        public static string Ask(IWin32Window owner, string title, string text, string value)
        {
            using (var f = new Form())
            {
                UI.Style(f, title, 440, 150);
                f.StartPosition = FormStartPosition.CenterParent;
                UI.Label(f, text, 18, 16, 400, 20);
                var box = UI.Box(f, 18, 44, 404, false); box.Text = value;
                var ok = UI.Button(f, "OK", 302, 96, 120, 34, (s, e) => f.DialogResult = DialogResult.OK, true);
                f.AcceptButton = ok;
                return f.ShowDialog(owner) == DialogResult.OK ? box.Text : null;
            }
        }
    }
}
