// Windows 10/11 x64 bootstrap. The release manifest is embedded at build time.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Reflection;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Drawing;

[DataContract] public sealed class Release {
    [DataMember] public int schema;
    [DataMember] public string version;
    [DataMember] public string platform;
    [DataMember] public string entrypoint;
    [DataMember] public string archive;
    [DataMember] public long size;
    [DataMember] public string sha256;
    [DataMember] public string[] urls;
    [DataMember] public FileRecord[] files;
    [DataMember] public Dictionary<string, string> certificate_pins;
}
[DataContract] public sealed class FileRecord {
    [DataMember] public string path;
    [DataMember] public long size;
    [DataMember] public string sha256;
}

internal static class Program {
    internal static string SelectRuntimeRoot(string requested) {
        if (requested != null) return Path.GetFullPath(requested);
        string portable = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Buggcraft-runtime");
        try {
            Directory.CreateDirectory(portable);
            string probe = Path.Combine(portable, ".write-test-" + Guid.NewGuid().ToString("N"));
            using (var stream = new FileStream(probe, FileMode.CreateNew, FileAccess.Write,
                                               FileShare.None, 1, FileOptions.DeleteOnClose)) { }
            return portable;
        } catch (UnauthorizedAccessException error) { Log.Exception("portable runtime directory is not writable", error); }
        catch (IOException error) { Log.Exception("portable runtime directory is unavailable", error); }
        string fallback = Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData), "Buggcraft", "runtime");
        Log.Write("runtime directory fallback", fallback);
        return fallback;
    }
    static string Option(string[] args, string name) {
        int index = Array.IndexOf(args, name);
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
    }
    [STAThread] static int Main(string[] args) {
        Log.Initialize(AppDomain.CurrentDomain.BaseDirectory);
        Log.Write("installer started", Log.SystemInformation());
        try {
            Release release;
            using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream("release.json"))
                release = (Release)new DataContractJsonSerializer(typeof(Release),
                    new DataContractJsonSerializerSettings { UseSimpleDictionaryFormat = true }).ReadObject(source);
            var installer = new RuntimeInstaller(release, SelectRuntimeRoot(Option(args, "--runtime-root")));
            if (args.Contains("--headless")) {
                string result;
                try {
                    string exe = installer.EnsureAsync(delegate { }, CancellationToken.None).GetAwaiter().GetResult();
                    result = "verified";
                    if (!args.Contains("--no-launch")) LaunchAsync(exe).GetAwaiter().GetResult();
                } catch (Exception error) {
                    Log.Exception("headless installation failed", error);
                    Log.SnapshotFailure(); result = "failed: " + error.Message;
                }
                string report = Option(args, "--report");
                if (report != null) File.WriteAllText(report, result, Encoding.UTF8);
                return result == "verified" ? 0 : 1;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallWindow(installer));
            return 0;
        } catch (Exception error) {
            Log.Exception("installer startup failed", error);
            Log.SnapshotFailure();
            if (args.Contains("--headless") && Option(args, "--report") != null)
                File.WriteAllText(Option(args, "--report"), "failed: " + error.Message, Encoding.UTF8);
            if (!args.Contains("--headless"))
                MessageBox.Show(error.Message, "Buggcraft", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
    internal static async Task LaunchAsync(string exe) {
        Log.Write("launching application", "entrypoint=" + exe);
        var start = new ProcessStartInfo(exe) {
            WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false,
            RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true
        };
        start.EnvironmentVariables["BUGGCRAFT_LOG_DIR"] = Log.DirectoryPath;
        // Game data must survive changes to the versioned runtime directory.
        start.EnvironmentVariables["BUGGCRAFT_LAUNCHER_DIR"] = AppDomain.CurrentDomain.BaseDirectory;
        using (var process = new Process { StartInfo = start }) {
            process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs output) {
                if (output.Data != null) Log.Native("stdout", output.Data);
            };
            process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs output) {
                if (output.Data != null) Log.Native("stderr", output.Data);
            };
            if (!process.Start()) throw new IOException("Windows did not start the launcher process.");
            Log.Write("application process started", "pid=" + process.Id);
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            // Keep the supervisor alive until Windows reports the child's exit,
            // including failures before Python or Qt can initialize logging.
            await Task.Run(delegate { process.WaitForExit(); });
            string code = process.ExitCode + " (0x" + unchecked((uint)process.ExitCode).ToString("X8") + ")";
            Log.Write("application exited", "exit_code=" + code);
            if (process.ExitCode != 0) {
                Log.SnapshotFailure(process.ExitCode);
                throw new IOException("启动器未能正常运行，退出码 " + code + "。日志：" + Log.DirectoryPath);
            }
        }
    }
}

internal static class Log {
    static readonly object Gate = new object();
    static string path;
    static string failureCode;
    public static string DirectoryPath { get { return Path.GetDirectoryName(path); } }
    public static string FailureDirectory { get; private set; }
    public static string PathFor(string directory, string name) { return Path.Combine(directory, name); }
    public static void Initialize(string directory) {
        try {
            Directory.CreateDirectory(directory); path = PathFor(directory, "Buggcraft-install.log");
            using (File.Open(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite)) { }
            Write("log file", path);
        }
        catch {
            string fallback = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Buggcraft", "logs");
            Directory.CreateDirectory(fallback); path = PathFor(fallback, "Buggcraft-install.log"); Write("log file (fallback)", path);
        }
    }
    public static void Write(string message, string details = "") {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff zzz") + " [" + message + "]" +
            (String.IsNullOrEmpty(details) ? "" : Environment.NewLine + details) + Environment.NewLine;
        lock (Gate) { try { File.AppendAllText(path, line, new UTF8Encoding(false)); } catch { } }
    }
    public static void Exception(string message, Exception error) { Write(message, error.ToString()); }
    public static void SnapshotFailure(int? exitCode = null) {
        if (exitCode.HasValue) failureCode = exitCode.Value.ToString(System.Globalization.CultureInfo.InvariantCulture);
        try {
            string directory = Path.Combine(DirectoryPath, "error", failureCode ?? "installer");
            Directory.CreateDirectory(directory);
            Write("failure diagnostics", directory);
            lock (Gate) {
                foreach (string file in Directory.GetFiles(DirectoryPath)) {
                    string name = Path.GetFileName(file);
                    if (name.Equals("Buggcraft-install.log", StringComparison.OrdinalIgnoreCase) ||
                        (name.StartsWith("buggcraft", StringComparison.OrdinalIgnoreCase) && name.Contains(".log")))
                        File.Copy(file, Path.Combine(directory, name), true);
                }
            }
            FailureDirectory = directory;
        } catch (Exception error) { Exception("could not archive failure diagnostics", error); }
    }
    public static void Native(string channel, string message) {
        lock (Gate) {
            try { File.AppendAllText(PathFor(DirectoryPath, "buggcraft-native.log"),
                DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff zzz") + " [" + channel + "] " + message + Environment.NewLine, new UTF8Encoding(false)); }
            catch { }
        }
    }
    public static string SystemInformation() {
        var memory = new MemoryStatus { Length = (uint)Marshal.SizeOf(typeof(MemoryStatus)) };
        string ram = GlobalMemoryStatusEx(ref memory) ? String.Format("{0} MB physical RAM", memory.TotalPhysical / (1024 * 1024)) : "RAM unavailable";
        string windows = Environment.OSVersion.ToString();
        string cpu = "unavailable";
        try {
            using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion"))
                if (key != null) windows += "; ProductName=" + key.GetValue("ProductName", "") +
                    "; DisplayVersion=" + key.GetValue("DisplayVersion", "") + "; Build=" + key.GetValue("CurrentBuildNumber", "") + "." + key.GetValue("UBR", "");
            using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"HARDWARE\DESCRIPTION\System\CentralProcessor\0"))
                if (key != null) cpu = Convert.ToString(key.GetValue("ProcessorNameString", "unavailable"));
        } catch (Exception error) { Write("optional system information unavailable", error.GetType().Name); }
        return "OS=" + windows + Environment.NewLine + "CPU=" + cpu + Environment.NewLine +
            "OS_64bit=" + Environment.Is64BitOperatingSystem + Environment.NewLine +
            "Process_64bit=" + Environment.Is64BitProcess + Environment.NewLine +
            ".NET=" + Environment.Version + Environment.NewLine +
            "CPU_count=" + Environment.ProcessorCount + Environment.NewLine + ram + Environment.NewLine +
            "Culture=" + System.Globalization.CultureInfo.CurrentCulture.Name + Environment.NewLine +
            "Installer_directory=" + AppDomain.CurrentDomain.BaseDirectory + Environment.NewLine +
            "Working_directory=" + Environment.CurrentDirectory;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)] struct MemoryStatus {
        public uint Length, MemoryLoad;
        public ulong TotalPhysical, AvailablePhysical, TotalPageFile, AvailablePageFile, TotalVirtual, AvailableVirtual, AvailableExtendedVirtual;
    }
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
}

internal sealed class RuntimeInstaller {
    readonly Release release;
    readonly string root;
    public RuntimeInstaller(Release manifest, string directory) {
        release = manifest;
        root = Path.GetFullPath(directory);
        if (release.schema != 1 || release.platform != "windows-x64" || !Environment.Is64BitOperatingSystem ||
            release.sha256 == null || release.sha256.Length != 64 || release.version != release.sha256.Substring(0, 16) ||
            release.size <= 0 || release.size > 2147483648L || release.files == null || release.files.Length == 0 ||
            release.files.Length > 20000 || Path.GetFileName(release.archive) != release.archive)
            throw new InvalidDataException("运行包清单无效，或当前系统不是 Windows x64。");
        if (release.files.Select(f => f.path).Distinct(StringComparer.OrdinalIgnoreCase).Count() != release.files.Length ||
            !release.files.Any(f => f.path == release.entrypoint))
            throw new InvalidDataException("运行包文件目录无效。");
        foreach (var file in release.files) {
            SafePath(root, file.path);
            if (file.size < 0 || file.sha256 == null || file.sha256.Length != 64)
                throw new InvalidDataException("运行包文件校验信息无效。");
        }
        // This callback lives only in the bootstrap process. Pins are embedded
        // in the release, never accepted from a downloaded manifest or UI.
        ServicePointManager.ServerCertificateValidationCallback = delegate(object sender,
            System.Security.Cryptography.X509Certificates.X509Certificate cert,
            System.Security.Cryptography.X509Certificates.X509Chain chain, SslPolicyErrors errors) {
            var request = sender as HttpWebRequest;
            string pin;
            if (request != null && release.certificate_pins != null &&
                release.certificate_pins.TryGetValue(request.RequestUri.Authority.ToLowerInvariant(), out pin)) {
                if (cert == null) return false;
                using (var sha = SHA256.Create())
                    return String.Equals(BitConverter.ToString(sha.ComputeHash(cert.GetRawCertData())).Replace("-", ""),
                                         pin, StringComparison.OrdinalIgnoreCase);
            }
            return errors == SslPolicyErrors.None;
        };
    }
    static string SafePath(string directory, string name) {
        if (String.IsNullOrEmpty(name) || name.Contains(":") || name.Contains("\\") || name.StartsWith("/") ||
            name.Split('/').Any(p => p == ".." || p == "." || p.EndsWith(" ") || p.EndsWith(".")))
            throw new InvalidDataException("运行包包含不安全路径。");
        string path = Path.GetFullPath(Path.Combine(directory, name));
        if (!path.StartsWith(Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar) +
                             Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("运行包路径超出安装目录。");
        return path;
    }
    static string HashFile(string path) {
        using (var hash = SHA256.Create())
        using (var stream = File.OpenRead(path))
            return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }
    void Verify(string directory, CancellationToken cancel) {
        foreach (var file in release.files) {
            cancel.ThrowIfCancellationRequested();
            string path = SafePath(directory, file.path);
            if (!File.Exists(path) || new FileInfo(path).Length != file.size || HashFile(path) != file.sha256)
                throw new InvalidDataException("运行文件缺失或损坏：" + file.path);
        }
    }
    static void RejectReparsePoints(string directory) {
        var current = new DirectoryInfo(directory);
        while (current != null) {
            if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("运行包目录不能使用符号链接或目录联接。");
            current = current.Parent;
        }
    }
    public Task<string> EnsureAsync(Action<string, int> progress, CancellationToken cancel) {
        return Task.Run(async delegate {
            Log.Write("checking runtime", "version=" + release.version + "; cache=" + root + Environment.NewLine + Log.SystemInformation());
            RejectReparsePoints(root);
            Directory.CreateDirectory(root);
            string lockPath = Path.Combine(root, "install.lock");
            FileStream installationLock = null;
            for (int i = 0; i < 60 && installationLock == null; i++) {
                cancel.ThrowIfCancellationRequested();
                try { installationLock = new FileStream(lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
                catch (IOException) { progress("正在等待另一个启动器完成准备…", 0); }
                if (installationLock == null) await Task.Delay(1000, cancel);
            }
            if (installationLock == null) throw new IOException("另一个启动器仍在准备，请稍后重试。");
            using (installationLock) {
                string installed = Path.Combine(root, release.version);
                progress("检查运行文件…", 0);
                if (Directory.Exists(installed)) {
                    RejectReparsePoints(installed);
                    try { Verify(installed, cancel); return SafePath(installed, release.entrypoint); }
                    catch (InvalidDataException error) { Log.Exception("cached runtime failed verification; reinstalling", error); }
                }
                string source = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, release.archive);
                string downloaded = Path.Combine(root, release.version + ".download");
                if (!File.Exists(source) || new FileInfo(source).Length != release.size || HashFile(source) != release.sha256) {
                    source = downloaded;
                    bool success = false;
                    foreach (string address in release.urls ?? new string[0]) {
                        Uri uri;
                        if (!Uri.TryCreate(address, UriKind.Absolute, out uri) || uri.Scheme != "https")
                            throw new InvalidDataException("下载地址必须使用 HTTPS。");
                        try {
                            Log.Write("downloading runtime", "host=" + uri.Authority + "; expected_bytes=" + release.size);
                            progress("下载启动器运行包…", 0);
                            using (var handler = new HttpClientHandler { AllowAutoRedirect = true })
                            using (var client = new HttpClient(handler) { Timeout = TimeSpan.FromMinutes(15) }) {
                                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
                                using (var response = await client.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, cancel)) {
                                    response.EnsureSuccessStatusCode();
                                    if (response.RequestMessage.RequestUri.Scheme != "https")
                                        throw new IOException("下载被重定向到不安全地址。");
                                    if (response.Content.Headers.ContentLength.HasValue && response.Content.Headers.ContentLength.Value != release.size)
                                        throw new InvalidDataException("运行包大小与清单不符。");
                                    using (var input = await response.Content.ReadAsStreamAsync())
                                    using (var output = new FileStream(downloaded, FileMode.Create, FileAccess.Write, FileShare.None)) {
                                        byte[] buffer = new byte[131072];
                                        long total = 0;
                                        int count;
                                        while ((count = await input.ReadAsync(buffer, 0, buffer.Length, cancel)) > 0) {
                                            total += count;
                                            if (total > release.size) throw new InvalidDataException("下载大小超过清单限制。");
                                            await output.WriteAsync(buffer, 0, count, cancel);
                                            progress("下载启动器运行包…", (int)(total * 70 / release.size));
                                        }
                                    }
                                }
                            }
                            if (new FileInfo(downloaded).Length != release.size || HashFile(downloaded) != release.sha256)
                                throw new InvalidDataException("运行包校验失败。");
                            success = true;
                            Log.Write("runtime download verified", "bytes=" + new FileInfo(downloaded).Length + "; sha256=" + release.sha256);
                            break;
                        } catch (OperationCanceledException error) {
                            if (cancel.IsCancellationRequested) throw;
                            Log.Exception("runtime download timed out", error);
                        }
                        catch (InvalidDataException error) { Log.Exception("download or runtime verification failed", error); }
                        catch (IOException error) { Log.Exception("runtime download failed", error); }
                        catch (HttpRequestException error) { Log.Exception("HTTPS request failed", error); }
                    }
                    if (!success) throw new IOException("无法取得运行包。请检查网络，或把配套的 " + release.archive + " 放在本程序旁边后重试。");
                }
                string staging = Path.Combine(root, ".staging-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(staging);
                try {
                    progress("校验并安装运行文件…", 75);
                    var expected = release.files.ToDictionary(f => f.path, StringComparer.OrdinalIgnoreCase);
                    using (var archive = ZipFile.OpenRead(source)) {
                        if (archive.Entries.Count != expected.Count) throw new InvalidDataException("运行包文件数量不符。");
                        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                        foreach (var entry in archive.Entries) {
                            cancel.ThrowIfCancellationRequested();
                            FileRecord record;
                            if (!expected.TryGetValue(entry.FullName, out record) || !seen.Add(entry.FullName) || entry.Length != record.size)
                                throw new InvalidDataException("运行包包含未知、重复或大小异常的文件。");
                            string path = SafePath(staging, entry.FullName);
                            Directory.CreateDirectory(Path.GetDirectoryName(path));
                            using (var input = entry.Open())
                            using (var output = new FileStream(path, FileMode.CreateNew)) {
                                byte[] buffer = new byte[131072];
                                long total = 0;
                                int count;
                                while ((count = input.Read(buffer, 0, buffer.Length)) > 0) {
                                    cancel.ThrowIfCancellationRequested();
                                    total += count;
                                    if (total > record.size) throw new InvalidDataException("解压大小超出限制。");
                                    output.Write(buffer, 0, count);
                                }
                            }
                        }
                    }
                    Verify(staging, cancel);
                    if (Directory.Exists(installed)) {
                        string old = installed + ".damaged-" + Guid.NewGuid().ToString("N");
                        Directory.Move(installed, old);
                    }
                    Directory.Move(staging, installed);
                    if (File.Exists(downloaded)) File.Delete(downloaded);
                    progress("准备完成", 100);
                    return SafePath(installed, release.entrypoint);
                } catch (Exception error) {
                    Log.Exception("runtime extraction or installation failed", error);
                    Log.Write("diagnostic files retained", "installer_log=" + Log.PathFor(AppDomain.CurrentDomain.BaseDirectory, "Buggcraft-install.log") + Environment.NewLine +
                        "download_cache=" + downloaded + Environment.NewLine + "install_cache=" + root);
                    throw;
                } finally { if (Directory.Exists(staging)) Directory.Delete(staging, true); }
            }
        }, cancel);
    }
}

internal sealed class InstallWindow : Form {
    readonly RuntimeInstaller installer;
    readonly Label status = new Label();
    readonly ProgressBar progress = new ProgressBar();
    readonly Button retry = new Button();
    readonly CancellationTokenSource cancel = new CancellationTokenSource();
    public InstallWindow(RuntimeInstaller runtime) {
        installer = runtime;
        Text = "Buggcraft"; ClientSize = new Size(520, 270);
        Font = new Font("Microsoft YaHei UI", 9);
        BackColor = Color.White; StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        var title = new Label { Text = "Buggcraft", Font = new Font("Segoe UI", 19, FontStyle.Bold),
                                Location = new Point(25, 20), Size = new Size(468, 40) };
        status.Text = "正在准备启动器…"; status.SetBounds(26, 76, 468, 108);
        progress.SetBounds(26, 194, 468, 12);
        retry.Text = "重试"; retry.SetBounds(409, 222, 85, 32); retry.Visible = false;
        Controls.AddRange(new Control[] { title, status, progress, retry });
        Shown += async delegate { await StartAsync(); };
        retry.Click += async delegate { await StartAsync(); };
        FormClosing += delegate { cancel.Cancel(); };
    }
    async Task StartAsync() {
        retry.Visible = false;
        try {
            string exe = await installer.EnsureAsync(delegate(string text, int value) {
                if (!IsDisposed && IsHandleCreated) BeginInvoke((Action)delegate { status.Text = text; progress.Value = value; });
            }, cancel.Token);
            Hide();
            await Program.LaunchAsync(exe);
            Close();
        } catch (OperationCanceledException) { }
        catch (Exception error) {
            Show();
            Log.Exception("installation failed", error);
            Log.SnapshotFailure();
            status.Text = error.Message + "\r\n故障文件：" + (Log.FailureDirectory ?? Log.DirectoryPath);
            retry.Visible = true;
        }
    }
}
