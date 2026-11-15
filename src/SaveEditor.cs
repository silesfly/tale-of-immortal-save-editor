// FILE: src/SaveEditor.cs
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("Tale of Immortal Save Editor")]
[assembly: AssemblyProduct("Tale of Immortal Save Editor")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

internal static class Program
{
    internal static string RuntimeFolder;
    internal static int ExitCode;
    internal static string TestRoot;
    internal static string SeedSlotDir;
    internal static bool TestRootOwned;

    internal static readonly JavaScriptSerializer Json =
        new JavaScriptSerializer { MaxJsonLength = 134217728, RecursionLimit = 32 };

    internal static byte[] Resource(string name)
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        Stream stream = assembly.GetManifestResourceStream(name);
        if (stream == null)
        {
            string[] names = assembly.GetManifestResourceNames();
            for (int i = 0; i < names.Length; i++)
            {
                if (String.Equals(names[i], name, StringComparison.Ordinal) ||
                    names[i].EndsWith("." + name, StringComparison.Ordinal))
                {
                    stream = assembly.GetManifestResourceStream(names[i]);
                    break;
                }
            }
        }
        if (stream == null)
            throw new IOException("Missing embedded resource: " + name);

        using (stream)
        using (MemoryStream memory = new MemoryStream())
        {
            stream.CopyTo(memory);
            return memory.ToArray();
        }
    }

    internal static void WriteNewRaw(string path, byte[] bytes)
    {
        if (bytes == null)
            throw new ArgumentNullException("bytes");

        SaveStore.NoLinks(path);
        string dir = Path.GetDirectoryName(path);
        if (!String.IsNullOrEmpty(dir) && !Directory.Exists(dir))
            Directory.CreateDirectory(dir);

        using (FileStream stream = new FileStream(path, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None))
        {
            SaveStore.VerifyOpenedHandle(stream, Path.GetFullPath(path));
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush(true);

            byte[] expected;
            using (SHA256 sha = SHA256.Create())
                expected = sha.ComputeHash(bytes);

            stream.Position = 0;
            byte[] actual;
            using (SHA256 sha = SHA256.Create())
                actual = sha.ComputeHash(stream);

            if (!actual.SequenceEqual(expected))
                throw new IOException("SHA-256 verification failed: " + path);
        }
    }

    internal static string GetDefaultToiSaveDir()
    {
        string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        string steamCandidate = Path.Combine(userProfile, "AppData", "LocalLow", "guigugame", "guigubahuang", "Steam", "CacheData");
        if (Directory.Exists(steamCandidate))
            return steamCandidate;

        string winCandidate = Path.Combine(userProfile, "AppData", "LocalLow", "guigugame", "guigubahuang", "Win", "CacheData");
        if (Directory.Exists(winCandidate))
            return winCandidate;

        string current = steamCandidate;
        while (!String.IsNullOrEmpty(current))
        {
            DirectoryInfo parent = Directory.GetParent(current);
            if (parent == null)
                break;

            current = parent.FullName;
            if (Directory.Exists(current))
                return current;
        }

        return userProfile;
    }

    internal static bool IsGameRunning()
    {
        string simulated = Environment.GetEnvironmentVariable("TOISE_SIMULATE_GAME_RUNNING");
        if (String.Equals(simulated, "1", StringComparison.Ordinal))
            return true;

        if (TestRoot != null)
            return false;

        try
        {
            return Process.GetProcessesByName("guigubahuang").Length > 0;
        }
        catch
        {
            return false;
        }
    }

    private static Assembly Resolve(object sender, ResolveEventArgs e)
    {
        AssemblyName requested = new AssemblyName(e.Name);
        string name = requested.Name;
        byte[] bytes = null;

        if (String.Equals(name, "Microsoft.Web.WebView2.Core", StringComparison.Ordinal))
            bytes = Resource("Microsoft.Web.WebView2.Core.dll");
        else if (String.Equals(name, "Microsoft.Web.WebView2.WinForms", StringComparison.Ordinal))
            bytes = Resource("Microsoft.Web.WebView2.WinForms.dll");

        return bytes == null ? null : Assembly.Load(bytes);
    }

    [STAThread]
    private static void Main(string[] args)
    {
        try
        {
            AppDomain.CurrentDomain.AssemblyResolve += new ResolveEventHandler(Resolve);

            if (args.Length == 0)
            {
                string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                RuntimeFolder = Path.Combine(localAppData, "TaleOfImmortalSaveEditor", "runtime-1.0.0");
                SaveStore.NoLinks(RuntimeFolder);

                if (!Directory.Exists(RuntimeFolder))
                    Directory.CreateDirectory(RuntimeFolder);
            }
            else if ((args.Length == 2 || args.Length == 3) && String.Equals(args[0], "--self-test", StringComparison.Ordinal))
            {
                TestRoot = Path.GetFullPath(args[1]);
                if (Directory.Exists(TestRoot) || File.Exists(TestRoot))
                    throw new IOException("검증 폴더는 새 경로여야 합니다: " + TestRoot);

                SaveStore.NoLinks(TestRoot);
                Directory.CreateDirectory(TestRoot);
                TestRootOwned = true;
                RuntimeFolder = TestRoot;

                if (args.Length == 3)
                {
                    SeedSlotDir = Path.GetFullPath(args[2]);
                    if (!Directory.Exists(SeedSlotDir))
                        throw new IOException("시드 슬롯 폴더를 찾을 수 없습니다: " + SeedSlotDir);
                    SaveStore.NoLinks(SeedSlotDir);
                }
            }
            else
            {
                throw new ArgumentException("지원하지 않는 실행 인수입니다.");
            }

            string loaderPath = Path.Combine(RuntimeFolder, "WebView2Loader.dll");
            byte[] loaderBytes = Resource("WebView2Loader.dll");
            bool writeLoader = true;

            if (File.Exists(loaderPath))
            {
                SaveStore.NoLinks(loaderPath);
                byte[] existing = File.ReadAllBytes(loaderPath);
                if (String.Equals(SaveStore.Hash(existing), SaveStore.Hash(loaderBytes), StringComparison.OrdinalIgnoreCase))
                    writeLoader = false;
                else
                    File.Delete(loaderPath);
            }

            if (writeLoader)
                WriteNewRaw(loaderPath, loaderBytes);

            Run();
        }
        catch (Exception ex)
        {
            ExitCode = 1;
            if (TestRoot != null)
            {
                try
                {
                    string failPath = Path.Combine(TestRoot, "failure.txt");
                    if (TestRootOwned && !File.Exists(failPath))
                        WriteNewRaw(failPath, Encoding.UTF8.GetBytes(ex.ToString()));
                }
                catch
                {
                }
            }
            else
            {
                MessageBox.Show("편집기를 시작하지 못했습니다.\n" + ex.Message, "귀곡팔황 세이브 에디터");
            }
        }
        Environment.ExitCode = ExitCode;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void Run()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        CoreWebView2Environment.SetLoaderDllFolderPath(RuntimeFolder);
        Application.Run(new EditorForm());
    }
}

internal sealed class EditorForm : Form
{
    private readonly WebView2 web = new WebView2();
    private bool closingAllowed;
    private string lastFolder = Program.GetDefaultToiSaveDir();
    private string activeSession = null;
    private readonly Dictionary<string, string> activePathsByKey = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, string> activeHashesByPath = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    private bool working = false;
    private bool initialLoaded = false;
    private bool selfTestStarted = false;
    private string pendingSession = null;
    private string pendingFolder = null;
    private Dictionary<string, string> pendingPathsByKey = null;
    private Dictionary<string, string> pendingHashesByPath = null;
    private string lastCompletedSaveId = null;
    private string lastCompletedSaveSession = null;
    private List<string> lastCompletedSaveBackups = null;
    private int testDelayNextSaveReplyMs = 0;

    public EditorForm()
    {
        Text = "귀곡팔황 (Tale of Immortal) 세이브 에디터 v1.0 · 자동 백업 저장";
        ClientSize = new Size(1380, 900);
        MinimumSize = new Size(960, 680);
        StartPosition = FormStartPosition.CenterScreen;
        web.Dock = DockStyle.Fill;
        Controls.Add(web);
        Shown += EditorForm_Shown;
        FormClosing += EditorForm_FormClosing;
        if (Program.TestRoot != null)
        {
            WindowState = FormWindowState.Minimized;
            ShowInTaskbar = false;
        }
        FormClosed += delegate { web.Dispose(); };
    }

    private async void EditorForm_Shown(object sender, EventArgs e)
    {
        await Initialize();
    }

    private async Task Initialize()
    {
        try
        {
            string profile = Path.Combine(Program.RuntimeFolder, "Profile");
            SaveStore.NoLinks(profile);
            CoreWebView2Environment env = await CoreWebView2Environment.CreateAsync(
                null,
                profile,
                new CoreWebView2EnvironmentOptions("--disable-background-networking"));
            await web.EnsureCoreWebView2Async(env);

            CoreWebView2Settings settings = web.CoreWebView2.Settings;
            settings.AreDevToolsEnabled = false;
            settings.AreDefaultContextMenusEnabled = false;
            settings.AreBrowserAcceleratorKeysEnabled = false;
            settings.IsPasswordAutosaveEnabled = false;
            settings.IsGeneralAutofillEnabled = false;
            settings.AreHostObjectsAllowed = false;
            settings.IsWebMessageEnabled = true;

            web.CoreWebView2.NewWindowRequested += delegate(object s, CoreWebView2NewWindowRequestedEventArgs e)
            {
                e.Handled = true;
            };
            web.CoreWebView2.PermissionRequested += delegate(object s, CoreWebView2PermissionRequestedEventArgs e)
            {
                e.State = CoreWebView2PermissionState.Deny;
            };

            bool firstNavigation = true;
            web.CoreWebView2.NavigationStarting += delegate(object s, CoreWebView2NavigationStartingEventArgs e)
            {
                if (firstNavigation &&
                    (String.Equals(e.Uri, "about:blank", StringComparison.OrdinalIgnoreCase) ||
                     e.Uri.StartsWith("data:text/html", StringComparison.OrdinalIgnoreCase)))
                {
                    firstNavigation = false;
                    return;
                }
                e.Cancel = true;
            };

            web.CoreWebView2.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            web.CoreWebView2.WebResourceRequested += delegate(object s, CoreWebView2WebResourceRequestedEventArgs e)
            {
                string uri = e.Request.Uri;
                if (uri.StartsWith("http:", StringComparison.OrdinalIgnoreCase) ||
                    uri.StartsWith("https:", StringComparison.OrdinalIgnoreCase))
                {
                    e.Response = env.CreateWebResourceResponse(new MemoryStream(new byte[0]), 403, "Offline", "");
                }
            };

            web.CoreWebView2.WebMessageReceived += delegate(object s, CoreWebView2WebMessageReceivedEventArgs e)
            {
                string raw = e.WebMessageAsJson;
                if (String.Equals(e.Source, "about:blank", StringComparison.OrdinalIgnoreCase) && raw != null)
                {
                    if (raw.Length > 96 * 1024 * 1024)
                    {
                        string errId = null;
                        object errSeq = null;
                        try
                        {
                            ExtractOversizeEnvelope(raw, out errId, out errSeq);
                        }
                        catch
                        {
                            errId = null;
                            errSeq = null;
                        }

                        Dictionary<string, object> errDict = new Dictionary<string, object>();
                        errDict["ok"] = false;
                        errDict["error"] = "전송 데이터가 허용 한도(96 MiB)를 초과했습니다.";
                        BeginInvoke(new Action(delegate { Reply(errId, errSeq, errDict); }));
                    }
                    else
                    {
                        BeginInvoke(new Action(delegate { HandleRequest(raw); }));
                    }
                }
            };

            web.CoreWebView2.NavigationCompleted += delegate(object s, CoreWebView2NavigationCompletedEventArgs e)
            {
                if (initialLoaded) return;
                if (!e.IsSuccess)
                {
                    Fail(new IOException("화면 로드 실패: " + e.WebErrorStatus));
                    return;
                }
                initialLoaded = true;
                if (Program.TestRoot != null && !selfTestStarted)
                {
                    selfTestStarted = true;
                    BeginInvoke(new Action(async delegate { await SelfTest(); }));
                }
            };

            web.CoreWebView2.NavigateToString(Encoding.UTF8.GetString(Program.Resource("editor.html")));
        }
        catch (Exception ex)
        {
            Fail(ex);
        }
    }

    private void Fail(Exception ex)
    {
        Program.ExitCode = 1;
        if (Program.TestRoot != null)
        {
            try
            {
                string path = Path.Combine(Program.TestRoot, "failure.txt");
                if (Program.TestRootOwned && !File.Exists(path))
                    Program.WriteNewRaw(path, Encoding.UTF8.GetBytes(ex.ToString()));
            }
            catch
            {
            }
        }
        else
        {
            MessageBox.Show(this, ex.Message, "오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        closingAllowed = true;
        Close();
    }

    private async void EditorForm_FormClosing(object sender, FormClosingEventArgs e)
    {
        if (closingAllowed || web.CoreWebView2 == null)
            return;

        e.Cancel = true;
        if (working) return;
        try
        {
            string result = await web.CoreWebView2.ExecuteScriptAsync("typeof window.hasUnsavedChanges === 'function' && window.hasUnsavedChanges()");
            if (result == "true")
            {
                if (MessageBox.Show(this, "저장하지 않은 변경 사항이 있습니다. 종료할까요?", "종료 확인", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
                    return;
            }
            closingAllowed = true;
            Close();
        }
        catch
        {
            closingAllowed = true;
            Close();
        }
    }

    private void Reply(string id, object seq, Dictionary<string, object> result)
    {
        result["id"] = id;
        if (seq != null)
            result["seq"] = seq;
        web.CoreWebView2.PostWebMessageAsJson(Program.Json.Serialize(result));
    }

    private static string GetString(IDictionary<string, object> obj, string key)
    {
        object value;
        if (obj != null && obj.TryGetValue(key, out value) && value != null)
            return Convert.ToString(value);
        return null;
    }

    private static IDictionary<string, object> AsDictionary(object value)
    {
        string asString = value as string;
        if (asString != null)
        {
            try
            {
                value = Program.Json.DeserializeObject(asString);
            }
            catch
            {
                return null;
            }
        }

        IDictionary<string, object> dict = value as IDictionary<string, object>;
        if (dict != null)
            return dict;

        return null;
    }

    private static string ExtractJsonStringField(string head, string quotedKey)
    {
        if (head == null || quotedKey == null)
            return null;

        int keyIndex = head.IndexOf(quotedKey, StringComparison.Ordinal);
        if (keyIndex < 0)
            return null;

        int pos = keyIndex + quotedKey.Length;
        while (pos < head.Length && Char.IsWhiteSpace(head[pos]))
            pos++;
        if (pos >= head.Length || head[pos] != ':')
            return null;
        pos++;
        while (pos < head.Length && Char.IsWhiteSpace(head[pos]))
            pos++;
        if (pos >= head.Length || head[pos] != '"')
            return null;
        pos++;

        StringBuilder sb = new StringBuilder();
        while (pos < head.Length)
        {
            char c = head[pos++];
            if (c == '"')
                return sb.ToString();
            if (c == '\\')
            {
                if (pos >= head.Length)
                    return null;
                char e = head[pos++];
                if (e == '"') sb.Append('"');
                else if (e == '\\') sb.Append('\\');
                else if (e == '/') sb.Append('/');
                else if (e == 'b') sb.Append('\b');
                else if (e == 'f') sb.Append('\f');
                else if (e == 'n') sb.Append('\n');
                else if (e == 'r') sb.Append('\r');
                else if (e == 't') sb.Append('\t');
                else if (e == 'u')
                {
                    if (pos + 4 > head.Length)
                        return null;
                    int value = 0;
                    for (int i = 0; i < 4; i++)
                    {
                        char h = head[pos++];
                        int digit;
                        if (h >= '0' && h <= '9') digit = h - '0';
                        else if (h >= 'a' && h <= 'f') digit = h - 'a' + 10;
                        else if (h >= 'A' && h <= 'F') digit = h - 'A' + 10;
                        else return null;
                        value = (value << 4) | digit;
                    }
                    sb.Append((char)value);
                }
                else
                {
                    sb.Append(e);
                }
            }
            else
            {
                sb.Append(c);
            }
        }
        return null;
    }

    private static void ExtractOversizeEnvelope(string raw, out string id, out object seq)
    {
        id = null;
        seq = null;
        if (raw == null)
            raw = String.Empty;

        string head = raw.Substring(0, Math.Min(raw.Length, 1024));
        if (head.Length > 0 && head[0] == '"')
        {
            try
            {
                head = head.Replace("\\\"", "\"");
            }
            catch
            {
            }
        }

        id = ExtractJsonStringField(head, "\"id\"");

        string seqText = ExtractJsonStringField(head, "\"seq\"");
        if (seqText != null)
        {
            long parsed;
            if (Int64.TryParse(seqText, out parsed))
                seq = parsed;
            else
                seq = seqText;
            return;
        }

        int keyIndex = head.IndexOf("\"seq\"", StringComparison.Ordinal);
        if (keyIndex < 0)
            return;

        int pos = keyIndex + "\"seq\"".Length;
        while (pos < head.Length && Char.IsWhiteSpace(head[pos]))
            pos++;
        if (pos >= head.Length || head[pos] != ':')
            return;
        pos++;
        while (pos < head.Length && Char.IsWhiteSpace(head[pos]))
            pos++;

        int start = pos;
        if (pos < head.Length && head[pos] == '-')
            pos++;
        int digitStart = pos;
        while (pos < head.Length && head[pos] >= '0' && head[pos] <= '9')
            pos++;
        if (pos == digitStart)
            return;

        string numStr = head.Substring(start, pos - start);
        long num;
        if (Int64.TryParse(numStr, out num))
            seq = num;
    }

    private static Dictionary<string, object> BuildLoadedFileEntry(string name, string relativePath, byte[] bytes)
    {
        Dictionary<string, object> entry = new Dictionary<string, object>();
        entry["name"] = name;
        entry["relativePath"] = relativePath;
        entry["base64"] = Convert.ToBase64String(bytes == null ? new byte[0] : bytes);
        return entry;
    }

    private void StagePendingSession(string folder, string session, Dictionary<string, string> nextPaths, Dictionary<string, string> nextHashes)
    {
        pendingFolder = folder;
        pendingSession = session;
        pendingPathsByKey = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (nextPaths != null)
        {
            foreach (KeyValuePair<string, string> pair in nextPaths)
                pendingPathsByKey[pair.Key] = pair.Value;
        }
        pendingHashesByPath = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (nextHashes != null)
        {
            foreach (KeyValuePair<string, string> pair in nextHashes)
                pendingHashesByPath[pair.Key] = pair.Value;
        }
    }

    private void ClearPendingSession()
    {
        pendingSession = null;
        pendingFolder = null;
        pendingPathsByKey = null;
        pendingHashesByPath = null;
    }

    private void CommitActiveSession(string folder, string session, Dictionary<string, string> nextPaths, Dictionary<string, string> nextHashes)
    {
        activePathsByKey.Clear();
        if (nextPaths != null)
        {
            foreach (KeyValuePair<string, string> pair in nextPaths)
                activePathsByKey[pair.Key] = pair.Value;
        }

        activeHashesByPath.Clear();
        if (nextHashes != null)
        {
            foreach (KeyValuePair<string, string> pair in nextHashes)
                activeHashesByPath[pair.Key] = pair.Value;
        }

        activeSession = session;
        if (!String.IsNullOrEmpty(folder))
            lastFolder = folder;
        lastCompletedSaveId = null;
        lastCompletedSaveSession = null;
        lastCompletedSaveBackups = null;
    }

    private void HandleRequest(string raw)
    {
        string id = null;
        object seq = null;
        bool acquired = false;
        try
        {
            IDictionary<string, object> root = AsDictionary(Program.Json.DeserializeObject(raw));
            if (root == null)
                throw new IOException("잘못된 요청입니다.");

            id = GetString(root, "id");
            object seqValue;
            if (root.TryGetValue("seq", out seqValue))
                seq = seqValue;

            string kind = GetString(root, "kind");
            if (String.IsNullOrEmpty(kind))
                kind = GetString(root, "cmd");

            if (kind == "session-status")
            {
                Dictionary<string, object> status = new Dictionary<string, object>();
                status["ok"] = true;
                status["working"] = working;
                status["activeSession"] = activeSession;
                status["lastCompletedSaveId"] = lastCompletedSaveId;
                status["lastCompletedSaveSession"] = lastCompletedSaveSession;
                status["lastCompletedSaveBackups"] = lastCompletedSaveBackups;
                Reply(id, seq, status);
                return;
            }

            if (working)
                throw new IOException("다른 파일 작업이 진행 중입니다.");
            working = true;
            acquired = true;

            if (kind == "open-slot")
            {
                string folder;
                if (Program.TestRoot != null)
                {
                    folder = Path.Combine(Program.TestRoot, "Slot1");
                }
                else
                {
                    using (FolderBrowserDialog dialog = new FolderBrowserDialog())
                    {
                        dialog.Description = "게임을 종료한 뒤 귀곡팔황 세이브 슬롯 폴더(예: 1_xxxxxx)를 선택하세요";
                        dialog.SelectedPath = lastFolder;
                        dialog.ShowNewFolderButton = false;
                        if (dialog.ShowDialog(this) != DialogResult.OK)
                        {
                            Dictionary<string, object> cancelled = new Dictionary<string, object>();
                            cancelled["ok"] = true;
                            cancelled["cancelled"] = true;
                            Reply(id, seq, cancelled);
                            return;
                        }
                        folder = dialog.SelectedPath;
                    }
                }

                folder = Path.GetFullPath(folder);
                SaveStore.NoLinks(folder);
                if (!Directory.Exists(folder))
                    throw new IOException("선택한 슬롯 폴더가 존재하지 않습니다: " + folder);

                string[] paths = Directory.GetFiles(folder);
                List<string> saves = new List<string>();
                for (int i = 0; i < paths.Length; i++)
                {
                    if (SaveStore.IsSaveFile(paths[i]))
                        saves.Add(paths[i]);
                }
                saves.Sort(StringComparer.OrdinalIgnoreCase);
                if (saves.Count == 0)
                    throw new IOException("선택한 폴더에 귀곡팔황 세이브 파일(CacheData/*.cache)이 없습니다.");

                Dictionary<string, string> nextPaths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                Dictionary<string, string> nextHashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                List<Dictionary<string, object>> files = new List<Dictionary<string, object>>();
                bool hasGlobal = false;

                for (int i = 0; i < saves.Count; i++)
                {
                    string fullPath = Path.GetFullPath(saves[i]);
                    string name = Path.GetFileName(fullPath);
                    byte[] bytes = SaveStore.Read(fullPath);
                    files.Add(BuildLoadedFileEntry(name, name, bytes));
                    nextPaths[name] = fullPath;
                    nextHashes[fullPath] = SaveStore.Hash(bytes);
                    if (String.Equals(name, "DataGloble.cache", StringComparison.OrdinalIgnoreCase))
                        hasGlobal = true;
                }

                if (!hasGlobal)
                {
                    DirectoryInfo parent = Directory.GetParent(folder);
                    if (parent != null)
                    {
                        string candidate = Path.Combine(parent.FullName, "DataGloble.cache");
                        if (File.Exists(candidate))
                        {
                            try
                            {
                                string gFull = Path.GetFullPath(candidate);
                                SaveStore.NoLinks(gFull);
                                byte[] gBytes = SaveStore.Read(gFull);
                                files.Add(BuildLoadedFileEntry("DataGloble.cache", "parent/DataGloble.cache", gBytes));
                                nextPaths["parent/DataGloble.cache"] = gFull;
                                nextPaths["DataGloble.cache"] = gFull;
                                nextHashes[gFull] = SaveStore.Hash(gBytes);
                            }
                            catch (IOException)
                            {
                            }
                        }
                    }
                }

                string session = Guid.NewGuid().ToString("N");
                StagePendingSession(folder, session, nextPaths, nextHashes);
                Dictionary<string, object> result = new Dictionary<string, object>();
                result["ok"] = true;
                result["session"] = session;
                result["folder"] = folder;
                result["files"] = files;
                Reply(id, seq, result);
                return;
            }

            if (kind == "open-files")
            {
                using (OpenFileDialog dialog = new OpenFileDialog())
                {
                    dialog.Title = "게임을 종료한 뒤 귀곡팔황 세이브 파일(CacheData/*.cache)을 선택하세요";
                    dialog.Filter = "귀곡팔황 세이브 (CacheData;CacheFixVer;*.cache)|CacheData;CacheFixVer;*.cache";
                    dialog.Multiselect = true;
                    dialog.CheckFileExists = true;
                    dialog.InitialDirectory = lastFolder;
                    if (dialog.ShowDialog(this) != DialogResult.OK)
                    {
                        Dictionary<string, object> cancelled = new Dictionary<string, object>();
                        cancelled["ok"] = true;
                        cancelled["cancelled"] = true;
                        Reply(id, seq, cancelled);
                        return;
                    }

                    Dictionary<string, string> nextPaths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    Dictionary<string, string> nextHashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    List<Dictionary<string, object>> files = new List<Dictionary<string, object>>();
                    for (int i = 0; i < dialog.FileNames.Length; i++)
                    {
                        string path = Path.GetFullPath(dialog.FileNames[i]);
                        string name = Path.GetFileName(path);
                        if (nextPaths.ContainsKey(name))
                            throw new IOException("같은 이름의 세이브 파일을 두 번 선택할 수 없습니다: " + name);

                        byte[] bytes = SaveStore.Read(path);
                        files.Add(BuildLoadedFileEntry(name, name, bytes));
                        nextPaths[name] = path;
                        nextHashes[path] = SaveStore.Hash(bytes);
                    }

                    if (files.Count == 0)
                        throw new IOException("선택한 세이브 파일이 없습니다.");

                    string folder = Path.GetDirectoryName(Path.GetFullPath(dialog.FileNames[0]));
                    string session = Guid.NewGuid().ToString("N");
                    StagePendingSession(folder, session, nextPaths, nextHashes);
                    Dictionary<string, object> result = new Dictionary<string, object>();
                    result["ok"] = true;
                    result["session"] = session;
                    result["folder"] = folder;
                    result["files"] = files;
                    Reply(id, seq, result);
                    return;
                }
            }

            if (kind == "confirm-session")
            {
                string reqSession = GetString(root, "session");
                if (String.IsNullOrEmpty(reqSession) || pendingSession == null || !String.Equals(reqSession, pendingSession, StringComparison.Ordinal))
                    throw new IOException("확정할 세션이 없습니다.");

                CommitActiveSession(pendingFolder, pendingSession, pendingPathsByKey, pendingHashesByPath);
                ClearPendingSession();

                Dictionary<string, object> result = new Dictionary<string, object>();
                result["ok"] = true;
                result["session"] = activeSession;
                Reply(id, seq, result);
                return;
            }

            if (kind == "discard-pending-session")
            {
                string reqSession = GetString(root, "session");
                if (pendingSession != null && (String.IsNullOrEmpty(reqSession) || String.Equals(reqSession, pendingSession, StringComparison.Ordinal)))
                    ClearPendingSession();

                Dictionary<string, object> result = new Dictionary<string, object>();
                result["ok"] = true;
                result["session"] = activeSession;
                Reply(id, seq, result);
                return;
            }

            if (kind == "save-files")
            {
                if (Program.IsGameRunning())
                    throw new IOException("귀곡팔황(guigubahuang.exe)이 실행 중입니다. 게임을 종료한 뒤 저장하세요.");

                string session = GetString(root, "session");
                if (activeSession == null || !String.Equals(session, activeSession, StringComparison.Ordinal))
                    throw new IOException("열었던 세이브 세션이 변경되었습니다. 슬롯을 다시 열어 주세요.");

                object filesValue;
                if (!root.TryGetValue("files", out filesValue))
                    throw new IOException("저장할 파일 목록이 없습니다.");
                IEnumerable files = filesValue as IEnumerable;
                if (files == null)
                    throw new IOException("저장할 파일 목록 형식이 잘못되었습니다.");

                List<SaveStore.BatchItem> batchItems = new List<SaveStore.BatchItem>();
                HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (object fileValue in files)
                {
                    IDictionary<string, object> file = AsDictionary(fileValue);
                    if (file == null)
                        throw new IOException("저장할 파일 형식이 잘못되었습니다.");

                    string key = GetString(file, "relativePath");
                    if (String.IsNullOrEmpty(key))
                        key = GetString(file, "name");
                    string targetPath;
                    if (String.IsNullOrEmpty(key) || !activePathsByKey.TryGetValue(key, out targetPath))
                        throw new IOException("열려 있지 않은 세이브 파일입니다: " + key);

                    if (!SaveStore.IsEditableSaveFile(targetPath))
                        throw new IOException("읽기 전용 세이브 파일은 수정할 수 없습니다: " + key);

                    if (!seen.Add(targetPath))
                        continue;

                    string base64 = GetString(file, "base64");
                    if (String.IsNullOrEmpty(base64))
                        base64 = GetString(file, "data");
                    if (String.IsNullOrEmpty(base64))
                        throw new IOException("저장할 데이터가 없습니다: " + key);

                    byte[] bytes = Convert.FromBase64String(base64);
                    string oldHash;
                    if (!activeHashesByPath.TryGetValue(targetPath, out oldHash))
                        throw new IOException("세이브 파일 해시 정보가 없습니다: " + key);

                    SaveStore.BatchItem item = new SaveStore.BatchItem();
                    item.Path = targetPath;
                    item.ExpectedHash = oldHash;
                    item.Data = bytes;
                    batchItems.Add(item);
                }

                List<string> backups = SaveStore.ReplaceBatch(batchItems, null);
                for (int i = 0; i < batchItems.Count; i++)
                    activeHashesByPath[batchItems[i].Path] = SaveStore.Hash(batchItems[i].Data);
                activeSession = Guid.NewGuid().ToString("N");

                lastCompletedSaveId = id;
                lastCompletedSaveSession = activeSession;
                lastCompletedSaveBackups = backups;

                if (Program.TestRoot != null && testDelayNextSaveReplyMs > 0)
                {
                    int delayMs = testDelayNextSaveReplyMs;
                    testDelayNextSaveReplyMs = 0;
                    System.Threading.Thread.Sleep(delayMs);
                }

                Dictionary<string, object> result = new Dictionary<string, object>();
                result["ok"] = true;
                result["session"] = activeSession;
                result["backups"] = backups;
                Reply(id, seq, result);
                return;
            }

            throw new IOException("알 수 없는 요청입니다: " + kind);
        }
        catch (Exception ex)
        {
            Dictionary<string, object> result = new Dictionary<string, object>();
            result["ok"] = false;
            result["error"] = ex.Message;
            Reply(id, seq, result);
        }
        finally
        {
            if (acquired)
                working = false;
        }
    }

    private async Task Until(string expression)
    {
        for (int i = 0; i < 300; i++)
        {
            string result = await web.CoreWebView2.ExecuteScriptAsync(expression);
            if (result == "true") return;
            await Task.Delay(100);
        }
        throw new IOException("검증 시간 초과: " + expression);
    }

    private async Task SelfTest()
    {
        try
        {
            await Until("typeof window.TaleOfImmortalCore === 'object' && typeof window.TaleOfImmortalCodec === 'object' && typeof window.TaleOfImmortalUI === 'object' && document.getElementById('btn-native-open-slot') !== null");

            string slotDir = Path.Combine(Program.TestRoot, "Slot1");
            Directory.CreateDirectory(slotDir);

            string headerFile = Path.Combine(slotDir, "CacheData");
            string fixVerFile = Path.Combine(slotDir, "CacheFixVer");
            string worldFile = Path.Combine(slotDir, "eMZk7avfjaaSiFBwLwtZHg==.cache");
            string unitFile = Path.Combine(slotDir, "O33a@9fkh++YwffVNeV1RA==.cache");
            string parentGlobalFile = Path.Combine(Program.TestRoot, "DataGloble.cache");

            if (Program.SeedSlotDir != null)
            {
                string[] srcFiles = Directory.GetFiles(Program.SeedSlotDir);
                Array.Sort(srcFiles, StringComparer.OrdinalIgnoreCase);
                bool copiedGlobalInSlot = false;
                for (int i = 0; i < srcFiles.Length; i++)
                {
                    if (!SaveStore.IsSaveFile(srcFiles[i]))
                        continue;
                    string fn = Path.GetFileName(srcFiles[i]);
                    byte[] raw = SaveStore.Read(srcFiles[i]);
                    SaveStore.WriteNew(Path.Combine(slotDir, fn), raw, null);
                    if (String.Equals(fn, "DataGloble.cache", StringComparison.OrdinalIgnoreCase))
                        copiedGlobalInSlot = true;
                }
                if (!copiedGlobalInSlot)
                {
                    DirectoryInfo seedParent = Directory.GetParent(Program.SeedSlotDir);
                    if (seedParent != null)
                    {
                        string srcGlobal = Path.Combine(seedParent.FullName, "DataGloble.cache");
                        if (File.Exists(srcGlobal) && SaveStore.IsSaveFile(srcGlobal))
                        {
                            byte[] gRaw = SaveStore.Read(srcGlobal);
                            SaveStore.WriteNew(parentGlobalFile, gRaw, null);
                        }
                    }
                }
            }
            else
            {
                string seedScript =
                    "(function(){window.__seedDone=false;window.__seedError=null;window.__seedFiles=null;" +
                    "window.TaleOfImmortalCore.createDemoSlotFiles().then(function(map){" +
                    "var keys=Object.keys(map);var arr=[];" +
                    "for(var i=0;i<keys.length;i++){var k=keys[i];arr.push({name:k,base64:window.TaleOfImmortalCodec.bytesToBase64(map[k])});}" +
                    "window.__seedFiles=arr;window.__seedDone=true;" +
                    "}).catch(function(e){window.__seedError=String(e&&e.message||e);window.__seedDone=true;});})();";
                await web.CoreWebView2.ExecuteScriptAsync(seedScript);
                await Until("window.__seedDone === true");
                string seedError = Program.Json.Deserialize<string>(await web.CoreWebView2.ExecuteScriptAsync("window.__seedError"));
                if (seedError != null)
                    throw new IOException("Seed generation failed: " + seedError);

                string filesJson = Program.Json.Deserialize<string>(await web.CoreWebView2.ExecuteScriptAsync("JSON.stringify(window.__seedFiles)"));
                object[] seedFiles = Program.Json.Deserialize<object[]>(filesJson);
                for (int i = 0; i < seedFiles.Length; i++)
                {
                    IDictionary<string, object> sf = AsDictionary(seedFiles[i]);
                    string name = GetString(sf, "name");
                    byte[] data = Convert.FromBase64String(GetString(sf, "base64"));
                    string target = String.Equals(name, "DataGloble.cache", StringComparison.OrdinalIgnoreCase)
                        ? parentGlobalFile
                        : Path.Combine(slotDir, name);
                    SaveStore.WriteNew(target, data, null);
                }
            }

            byte[] headerOriginal = File.ReadAllBytes(headerFile);
            byte[] unitOriginal = File.ReadAllBytes(unitFile);
            string headerOrigHash = SaveStore.Hash(headerOriginal);
            string unitOrigHash = SaveStore.Hash(unitOriginal);

            bool hasFixVer = File.Exists(fixVerFile);
            byte[] fixVerOriginal = hasFixVer ? File.ReadAllBytes(fixVerFile) : null;
            string fixVerOrigHash = hasFixVer ? SaveStore.Hash(fixVerOriginal) : null;

            bool hasParentGlobal = File.Exists(parentGlobalFile);
            byte[] globalOriginal = hasParentGlobal ? File.ReadAllBytes(parentGlobalFile) : null;
            string globalOrigHash = hasParentGlobal ? SaveStore.Hash(globalOriginal) : null;

            await web.CoreWebView2.ExecuteScriptAsync("document.getElementById('btn-native-open-slot').click();");
            await Until("!window.TaleOfImmortalUI.isBusy() && window.TaleOfImmortalUI.getNativeSession() !== null && window.TaleOfImmortalUI.getSession() !== null");

            int filesLoaded = Convert.ToInt32(await web.CoreWebView2.ExecuteScriptAsync("window.TaleOfImmortalUI.getSession().files.length"));
            string initialTicks = Program.Json.Deserialize<string>(
                await web.CoreWebView2.ExecuteScriptAsync("window.TaleOfImmortalCore.getSummary(window.TaleOfImmortalUI.getSession()).createTicks"));
            int initialWorldDay = Convert.ToInt32(
                await web.CoreWebView2.ExecuteScriptAsync("window.TaleOfImmortalCore.getSummary(window.TaleOfImmortalUI.getSession()).worldDay"));

            await web.CoreWebView2.ExecuteScriptAsync("document.querySelector('[data-preset=\"rich-cultivator\"]').click();");
            await web.CoreWebView2.ExecuteScriptAsync("document.querySelector('[data-preset=\"sect-prosperity\"]').click();");
            await web.CoreWebView2.ExecuteScriptAsync(
                "(function(){var s=window.TaleOfImmortalUI.getSession();" +
                "var sum=window.TaleOfImmortalCore.getSummary(s);" +
                "window.TaleOfImmortalCore.setPlayerIdentity(s,{worldDay:sum.worldDay+1});" +
                "window.TaleOfImmortalCore.unlockAllAchievements(s);" +
                "window.TaleOfImmortalUI.refresh();})();");
            await Until("window.hasUnsavedChanges() === true");

            try
            {
                Environment.SetEnvironmentVariable("TOISE_SIMULATE_GAME_RUNNING", "1");
                await web.CoreWebView2.ExecuteScriptAsync("window.__prevSession = window.TaleOfImmortalUI.getNativeSession();");
                await web.CoreWebView2.ExecuteScriptAsync("document.getElementById('btn-native-save').click();");
                await Until("!window.TaleOfImmortalUI.isBusy()");

                string guardCheck = Program.Json.Deserialize<string>(await web.CoreWebView2.ExecuteScriptAsync(
                    "(function(){return (window.hasUnsavedChanges()===true && window.TaleOfImmortalUI.getNativeSession()===window.__prevSession)?'OK':'FAIL';})()"));
                if (guardCheck != "OK")
                    throw new IOException("process guard verification failed");
                if (Directory.GetFiles(slotDir, "*.bak").Length != 0)
                    throw new IOException("process guard wrote unexpected backup");
            }
            finally
            {
                Environment.SetEnvironmentVariable("TOISE_SIMULATE_GAME_RUNNING", null);
            }

            await web.CoreWebView2.ExecuteScriptAsync("window.__prevSession = window.TaleOfImmortalUI.getNativeSession();");
            await web.CoreWebView2.ExecuteScriptAsync("document.getElementById('btn-native-save').click();");
            await Until("!window.TaleOfImmortalUI.isBusy() && window.hasUnsavedChanges() === false && window.TaleOfImmortalUI.getNativeSession() !== window.__prevSession");

            string[] headerBaks = Directory.GetFiles(slotDir, "CacheData.backup-*.bak");
            string[] unitBaks = Directory.GetFiles(slotDir, "O33a@9fkh++YwffVNeV1RA==.cache.backup-*.bak");
            if (headerBaks.Length != 1 || SaveStore.Hash(File.ReadAllBytes(headerBaks[0])) != headerOrigHash)
                throw new IOException("header backup verification failed");
            if (unitBaks.Length != 1 || SaveStore.Hash(File.ReadAllBytes(unitBaks[0])) != unitOrigHash)
                throw new IOException("unit backup verification failed");

            if (hasFixVer)
            {
                string[] fixVerBaks = Directory.GetFiles(slotDir, "CacheFixVer.backup-*.bak");
                if (fixVerBaks.Length != 0 || SaveStore.Hash(File.ReadAllBytes(fixVerFile)) != fixVerOrigHash)
                    throw new IOException("CacheFixVer immutability verification failed");
            }

            if (hasParentGlobal)
            {
                string[] globalBaks = Directory.GetFiles(Program.TestRoot, "DataGloble.cache.backup-*.bak");
                if (globalBaks.Length == 1 && SaveStore.Hash(File.ReadAllBytes(globalBaks[0])) != globalOrigHash)
                    throw new IOException("DataGloble backup hash mismatch");
            }

            await web.CoreWebView2.ExecuteScriptAsync("window.__prevSession = window.TaleOfImmortalUI.getNativeSession();");
            await web.CoreWebView2.ExecuteScriptAsync("document.getElementById('btn-native-open-slot').click();");
            await Until("!window.TaleOfImmortalUI.isBusy() && window.TaleOfImmortalUI.getNativeSession() !== window.__prevSession");

            string reloadVerify = Program.Json.Deserialize<string>(await web.CoreWebView2.ExecuteScriptAsync(
                "(function(){var sum=window.TaleOfImmortalCore.getSummary(window.TaleOfImmortalUI.getSession());" +
                "return JSON.stringify({stones:sum.spiritStones,ticks:sum.createTicks,day:sum.worldDay});})()"));
            IDictionary<string, object> reloadObj = AsDictionary(Program.Json.DeserializeObject(reloadVerify));
            int stonesAfter = Convert.ToInt32(reloadObj["stones"]);
            string ticksAfter = GetString(reloadObj, "ticks");
            int dayAfter = Convert.ToInt32(reloadObj["day"]);
            if (stonesAfter != 9999999)
                throw new IOException("spiritStones after reload mismatch: " + stonesAfter);
            if (!String.Equals(ticksAfter, initialTicks, StringComparison.Ordinal))
                throw new IOException("createTicks precision lost: " + ticksAfter + " != " + initialTicks);
            if (dayAfter != initialWorldDay + 1)
                throw new IOException("worldDay sync mismatch: " + dayAfter);

            byte[] headerBefore = File.ReadAllBytes(headerFile);
            byte[] worldBefore = File.ReadAllBytes(worldFile);
            byte[] unitBefore = File.ReadAllBytes(unitFile);
            int headerBaksBefore = Directory.GetFiles(slotDir, "CacheData.backup-*.bak").Length;

            await web.CoreWebView2.ExecuteScriptAsync(
                "(function(){var s=window.TaleOfImmortalUI.getSession();" +
                "var sum=window.TaleOfImmortalCore.getSummary(s);" +
                "window.TaleOfImmortalCore.setCurrencyCount(s,10001,7777777);" +
                "window.TaleOfImmortalCore.setPlayerIdentity(s,{worldDay:sum.worldDay+1});" +
                "window.TaleOfImmortalUI.refresh();})();");
            await Until("window.hasUnsavedChanges() === true");

            try
            {
                byte[] badUnit = (byte[])unitBefore.Clone();
                badUnit[badUnit.Length - 1] ^= 0xFF;
                File.WriteAllBytes(unitFile, badUnit);

                await web.CoreWebView2.ExecuteScriptAsync("window.__prevSession = window.TaleOfImmortalUI.getNativeSession();");
                await web.CoreWebView2.ExecuteScriptAsync("document.getElementById('btn-native-save').click();");
                await Until("!window.TaleOfImmortalUI.isBusy()");

                string prewriteVerify = Program.Json.Deserialize<string>(await web.CoreWebView2.ExecuteScriptAsync(
                    "(function(){return (window.hasUnsavedChanges()===true && window.TaleOfImmortalUI.getNativeSession()===window.__prevSession)?'OK':'FAIL';})()"));
                if (prewriteVerify != "OK")
                    throw new IOException("prewrite conflict verification failed");
                if (!File.ReadAllBytes(headerFile).SequenceEqual(headerBefore))
                    throw new IOException("prewrite conflict header file modified");
                if (!File.ReadAllBytes(worldFile).SequenceEqual(worldBefore))
                    throw new IOException("prewrite conflict world file modified");
                if (Directory.GetFiles(slotDir, "CacheData.backup-*.bak").Length != headerBaksBefore)
                    throw new IOException("prewrite conflict unexpected backup created");
            }
            finally
            {
                File.WriteAllBytes(unitFile, unitBefore);
            }

            try
            {
                SaveStore.TestReplaceBatchFailAtCommitIndex = 1;
                await web.CoreWebView2.ExecuteScriptAsync("window.__prevSession = window.TaleOfImmortalUI.getNativeSession();");
                await web.CoreWebView2.ExecuteScriptAsync("document.getElementById('btn-native-save').click();");
                await Until("!window.TaleOfImmortalUI.isBusy()");

                string rollbackVerify = Program.Json.Deserialize<string>(await web.CoreWebView2.ExecuteScriptAsync(
                    "(function(){return (window.hasUnsavedChanges()===true && window.TaleOfImmortalUI.getNativeSession()===window.__prevSession)?'OK':'FAIL';})()"));
                if (rollbackVerify != "OK")
                    throw new IOException("batch rollback verification failed");
                if (!File.ReadAllBytes(headerFile).SequenceEqual(headerBefore))
                    throw new IOException("batch rollback header file mismatch");
                if (!File.ReadAllBytes(worldFile).SequenceEqual(worldBefore))
                    throw new IOException("batch rollback world file mismatch");
                if (!File.ReadAllBytes(unitFile).SequenceEqual(unitBefore))
                    throw new IOException("batch rollback unit file mismatch");
            }
            finally
            {
                SaveStore.TestReplaceBatchFailAtCommitIndex = -1;
            }

            testDelayNextSaveReplyMs = 240;
            await web.CoreWebView2.ExecuteScriptAsync("window.__prevTimeoutSession = window.TaleOfImmortalUI.getNativeSession(); window.__TOI_RPC_TIMEOUT_MS__ = 60; window.__TOI_RPC_POLL_MS__ = 25; document.getElementById('btn-native-save').click(); setTimeout(function(){ var s = window.TaleOfImmortalUI.getSession(); window.TaleOfImmortalCore.setCurrencyCount(s, 10041, 321); }, 20);");
            await Until("!window.TaleOfImmortalUI.isBusy() && !window.TaleOfImmortalUI.hasPendingSaveRecovery()");
            await web.CoreWebView2.ExecuteScriptAsync("window.__TOI_RPC_TIMEOUT_MS__ = 30000;");
            string timeoutRecoveryOk = await web.CoreWebView2.ExecuteScriptAsync("(window.TaleOfImmortalUI.getTimedOutSaveCount() >= 1 && window.TaleOfImmortalUI.getNativeSession() !== window.__prevTimeoutSession && window.hasUnsavedChanges() === true)");
            if (timeoutRecoveryOk != "true")
                throw new IOException("timeout session recovery verification failed");
            await web.CoreWebView2.ExecuteScriptAsync("document.getElementById('btn-native-save').click();");
            await Until("!window.TaleOfImmortalUI.isBusy() && window.hasUnsavedChanges() === false");
            if (Convert.ToInt32(await web.CoreWebView2.ExecuteScriptAsync("window.TaleOfImmortalCore.getCurrencyCount(window.TaleOfImmortalUI.getSession(), 10041)")) != 321)
                throw new IOException("timeout recovery currency verification failed");

            Dictionary<string, object> receipt = new Dictionary<string, object>();
            receipt["status"] = "PASS";
            receipt["timeoutRecoveryVerified"] = true;
            receipt["seededFromDir"] = Program.SeedSlotDir != null;
            receipt["filesLoaded"] = filesLoaded;
            receipt["spiritStonesAfterReload"] = stonesAfter;
            receipt["createTicksPreserved"] = true;
            receipt["fixVerUntouched"] = true;
            receipt["processGuardVerified"] = true;
            receipt["backupsVerified"] = true;
            receipt["prewriteConflictVerified"] = true;
            receipt["batchRollbackVerified"] = true;
            receipt["htmlHash"] = SaveStore.Hash(Program.Resource("editor.html"));
            byte[] receiptBytes = Encoding.UTF8.GetBytes(Program.Json.Serialize(receipt));
            Program.WriteNewRaw(Path.Combine(Program.TestRoot, "receipt.json"), receiptBytes);

            closingAllowed = true;
            Close();
        }
        catch (Exception ex)
        {
            Fail(ex);
        }
    }
}
