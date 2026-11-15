// FILE: src/SaveStore.cs
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

internal static class SaveStore
{
    internal const int MaxSaveBytes = 32 * 1024 * 1024;

    internal static Action<string> TestAfterNoLinksHook = null;
    internal static Action<string> TestBeforePublishHook = null;
    internal static Action<int, string, SafeFileHandle> TestAfterBackupCreatedHook = null;
    internal static Action<string, SafeFileHandle> TestOnTempFailureHook = null;
    internal static int TestReplaceBatchFailAtCommitIndex = -1;

    internal sealed class BatchItem
    {
        public string Path;
        public string ExpectedHash;
        public byte[] Data;
    }

    private sealed class PreparedBatchEntry
    {
        public string FullPath;
        public string ExpectedHash;
        public byte[] Data;
        public byte[] Before;
        public FileStream Stream;
        public string BackupPath;
        public SafeFileHandle BackupHandle;
        public FileStream BackupStream;
    }

    private const uint FILE_ATTRIBUTE_DIRECTORY = 0x00000010u;
    private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400u;
    private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000u;

    [StructLayout(LayoutKind.Sequential)]
    private struct FILETIME
    {
        public uint dwLowDateTime;
        public uint dwHighDateTime;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BY_HANDLE_FILE_INFORMATION
    {
        public uint FileAttributes;
        public FILETIME CreationTime;
        public FILETIME LastAccessTime;
        public FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle hFile,
        out BY_HANDLE_FILE_INFORMATION lpFileInformation);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "GetFinalPathNameByHandleW")]
    private static extern uint GetFinalPathNameByHandleW(
        SafeFileHandle hFile,
        StringBuilder lpszFilePath,
        uint cchFilePath,
        uint dwFlags);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string lpFileName,
        uint dwDesiredAccess,
        uint dwShareMode,
        IntPtr lpSecurityAttributes,
        uint dwCreationDisposition,
        uint dwFlagsAndAttributes,
        IntPtr hTemplateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetFileInformationByHandle(
        SafeFileHandle hFile,
        int FileInformationClass,
        IntPtr lpFileInformation,
        uint dwBufferSize);

    private static void RenameExclusiveByHandle(SafeFileHandle hFile, string fullPath)
    {
        byte[] nameBytes = Encoding.Unicode.GetBytes(fullPath);
        int rootOffset = IntPtr.Size;
        int lenOffset = IntPtr.Size * 2;
        int strOffset = lenOffset + 4;
        int total = strOffset + nameBytes.Length + 2;
        IntPtr buf = Marshal.AllocHGlobal(total);
        try
        {
            for (int i = 0; i < total; i++)
                Marshal.WriteByte(buf, i, 0);
            Marshal.WriteByte(buf, 0, 0);
            Marshal.WriteIntPtr(buf, rootOffset, IntPtr.Zero);
            Marshal.WriteInt32(buf, lenOffset, nameBytes.Length);
            Marshal.Copy(nameBytes, 0, new IntPtr(buf.ToInt64() + strOffset), nameBytes.Length);
            if (!SetFileInformationByHandle(hFile, 3, buf, (uint)total))
            {
                int winErr = Marshal.GetLastWin32Error();
                throw new IOException("새 파일 원자적 이동에 실패했습니다(" + winErr + "): " + fullPath);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buf);
        }
    }

    private static bool TryMarkDeleteByHandle(SafeFileHandle hFile, out int winErr)
    {
        winErr = 0;
        if (hFile == null || hFile.IsInvalid || hFile.IsClosed)
        {
            winErr = 6;
            return false;
        }

        IntPtr buf = Marshal.AllocHGlobal(1);
        try
        {
            Marshal.WriteByte(buf, 0, 1);
            if (SetFileInformationByHandle(hFile, 4, buf, 1u))
                return true;
            winErr = Marshal.GetLastWin32Error();
            return false;
        }
        finally
        {
            Marshal.FreeHGlobal(buf);
        }
    }

    private static bool TryGetHandleFileId(SafeFileHandle hFile, out BY_HANDLE_FILE_INFORMATION info)
    {
        info = default(BY_HANDLE_FILE_INFORMATION);
        if (hFile == null || hFile.IsInvalid || hFile.IsClosed)
            return false;
        return GetFileInformationByHandle(hFile, out info);
    }

    private static bool TryGetExistingPathFileId(string fullPath, out BY_HANDLE_FILE_INFORMATION info)
    {
        info = default(BY_HANDLE_FILE_INFORMATION);
        using (SafeFileHandle h = CreateFileW(fullPath, 0x80u, 7u, IntPtr.Zero, 3u, FILE_FLAG_BACKUP_SEMANTICS | 0x00200000u, IntPtr.Zero))
        {
            if (h == null || h.IsInvalid || h.IsClosed)
                return false;
            return GetFileInformationByHandle(h, out info);
        }
    }

    private static void DisposeStreamAndHandleQuietly(ref FileStream stream, ref SafeFileHandle handle)
    {
        if (stream != null)
        {
            try { stream.Dispose(); }
            catch { }
            stream = null;
        }
        if (handle != null)
        {
            try { handle.Dispose(); }
            catch { }
            handle = null;
        }
    }

    private static string DeleteOwnedHandleOnFailure(ref SafeFileHandle handle, ref FileStream stream, string expectedPath)
    {
        if (String.IsNullOrEmpty(expectedPath))
        {
            DisposeStreamAndHandleQuietly(ref stream, ref handle);
            return null;
        }

        BY_HANDLE_FILE_INFORMATION ownedInfo;
        bool hasOwned = TryGetHandleFileId(handle, out ownedInfo);
        int winErr;
        bool marked = TryMarkDeleteByHandle(handle, out winErr);
        DisposeStreamAndHandleQuietly(ref stream, ref handle);

        BY_HANDLE_FILE_INFORMATION after;
        bool hasAfter = TryGetExistingPathFileId(expectedPath, out after);
        if (!marked)
        {
            if (!hasAfter && !File.Exists(expectedPath))
                return null;
            return expectedPath + " (배타 핸들 삭제 불가 win32=" + winErr + ", 외부 파일 보호를 위해 경로 보존)";
        }

        if (!hasAfter)
            return null;

        if (!hasOwned || (
            after.VolumeSerialNumber == ownedInfo.VolumeSerialNumber &&
            after.FileIndexHigh == ownedInfo.FileIndexHigh &&
            after.FileIndexLow == ownedInfo.FileIndexLow))
        {
            return expectedPath + " (핸들 닫기 후 잔존 파일 감지, 경로 보존)";
        }

        return null;
    }

    private static void VerifyStreamHash(FileStream stream, byte[] expectedBytes, string errPrefix)
    {
        if (stream == null || expectedBytes == null || stream.Length != expectedBytes.Length)
            throw new IOException(errPrefix + " (크기 불일치)");
        stream.Position = 0;
        byte[] actual = ReadFrom(stream, (int)stream.Length);
        if (!String.Equals(Hash(actual), Hash(expectedBytes), StringComparison.OrdinalIgnoreCase))
            throw new IOException(errPrefix + " (해시 불일치)");
    }

    internal static bool HasInvalidColon(string path)
    {
        if (String.IsNullOrEmpty(path))
            return false;

        for (int i = 0; i < path.Length; i++)
        {
            if (path[i] != ':')
                continue;

            bool driveColon =
                i == 1 &&
                path.Length >= 3 &&
                ((path[0] >= 'A' && path[0] <= 'Z') || (path[0] >= 'a' && path[0] <= 'z')) &&
                (path[2] == '\\' || path[2] == '/');

            if (!driveColon)
                return true;
        }

        return false;
    }

    internal static bool IsReservedDeviceName(string stem)
    {
        if (String.IsNullOrEmpty(stem))
            return false;

        string s = stem.TrimEnd(' ', '.');
        if (s.Length == 0)
            return false;

        string u = s.ToUpperInvariant();
        if (u == "CON" || u == "PRN" || u == "AUX" || u == "NUL")
            return true;

        if (u.Length == 4)
        {
            if ((u.StartsWith("COM", StringComparison.Ordinal) || u.StartsWith("LPT", StringComparison.Ordinal)) &&
                u[3] >= '1' && u[3] <= '9')
            {
                return true;
            }
        }

        return false;
    }

    private static bool TryGetSafeFileName(string path, out string fileName)
    {
        fileName = null;
        if (String.IsNullOrEmpty(path) || HasInvalidColon(path))
            return false;

        string candidate;
        try
        {
            candidate = Path.GetFileName(path);
        }
        catch
        {
            return false;
        }

        if (String.IsNullOrEmpty(candidate) || candidate.IndexOf(':') >= 0)
            return false;

        int dot = candidate.IndexOf('.');
        string stem = dot >= 0 ? candidate.Substring(0, dot) : candidate;
        stem = stem.TrimEnd(' ', '.');
        if (stem.Length == 0 || IsReservedDeviceName(stem))
            return false;

        fileName = candidate;
        return true;
    }

    internal static bool IsSaveFile(string path)
    {
        string fileName;
        if (!TryGetSafeFileName(path, out fileName))
            return false;

        if (String.Equals(fileName, "CacheData", StringComparison.OrdinalIgnoreCase))
            return true;
        if (String.Equals(fileName, "CacheFixVer", StringComparison.OrdinalIgnoreCase))
            return true;
        return String.Equals(Path.GetExtension(fileName), ".cache", StringComparison.OrdinalIgnoreCase);
    }

    internal static bool IsSaveExtension(string path)
    {
        return IsSaveFile(path);
    }

    internal static bool IsEditableSaveFile(string path)
    {
        if (!IsSaveFile(path))
            return false;

        string fileName = Path.GetFileName(path);
        return !String.Equals(fileName, "CacheFixVer", StringComparison.OrdinalIgnoreCase);
    }

    internal static bool IsAllowedWritePath(string path, bool allowBackup)
    {
        string fileName;
        if (!TryGetSafeFileName(path, out fileName))
            return false;

        if (IsSaveFile(path))
            return true;

        return allowBackup &&
               String.Equals(Path.GetExtension(fileName), ".bak", StringComparison.OrdinalIgnoreCase);
    }

    internal static string Hash(byte[] bytes)
    {
        if (bytes == null)
            throw new ArgumentNullException("bytes");

        using (SHA256 sha = SHA256.Create())
        {
            byte[] digest = sha.ComputeHash(bytes);
            StringBuilder sb = new StringBuilder(digest.Length * 2);
            for (int i = 0; i < digest.Length; i++)
                sb.Append(digest[i].ToString("x2"));
            return sb.ToString();
        }
    }

    private static string NormalizeFullPathNoTrailingSlash(string p)
    {
        string full = Path.GetFullPath(p);
        string root = Path.GetPathRoot(full);
        if (root != null && full.Length > root.Length)
            full = full.TrimEnd('\\', '/');
        return full;
    }

    private static void NoLinksCore(string path)
    {
        if (String.IsNullOrEmpty(path))
            throw new IOException("경로가 비어 있습니다.");

        string trimmed = path.TrimStart();
        if (trimmed.StartsWith("\\\\", StringComparison.Ordinal) ||
            trimmed.StartsWith("//", StringComparison.Ordinal))
            throw new IOException("네트워크(UNC) 경로는 허용되지 않습니다: " + path);

        if (HasInvalidColon(path))
            throw new IOException("허용되지 않는 경로 형식(대체 데이터 스트림 등)입니다: " + path);

        string full;
        try
        {
            full = Path.GetFullPath(path);
        }
        catch (Exception ex)
        {
            throw new IOException("유효하지 않은 경로입니다: " + path, ex);
        }

        if (full.StartsWith("\\\\", StringComparison.Ordinal) ||
            full.StartsWith("//", StringComparison.Ordinal))
            throw new IOException("네트워크(UNC) 경로는 허용되지 않습니다: " + path);

        if (full.IndexOf(':', 2) >= 0)
            throw new IOException("NTFS 대체 데이터 스트림 경로는 허용되지 않습니다: " + path);

        string current = full;
        while (!String.IsNullOrEmpty(current))
        {
            if ((File.Exists(current) || Directory.Exists(current)) &&
                (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
            {
                throw new IOException("링크(심볼릭 링크/정션) 경로는 지원하지 않습니다: " + current);
            }

            string parent = Path.GetDirectoryName(current);
            if (String.IsNullOrEmpty(parent) || String.Equals(parent, current, StringComparison.OrdinalIgnoreCase))
                break;
            current = parent;
        }
    }

    internal static void NoLinks(string path)
    {
        NoLinksCore(path);
        Action<string> hook = TestAfterNoLinksHook;
        if (hook != null)
            hook(path);
    }

    private static void VerifySafeHandle(SafeFileHandle handle, string expectedFullPath, bool requireDirectory)
    {
        if (handle == null || handle.IsInvalid || handle.IsClosed)
            throw new IOException("열린 파일 핸들이 유효하지 않습니다.");

        BY_HANDLE_FILE_INFORMATION info;
        if (!GetFileInformationByHandle(handle, out info))
            throw new IOException("파일 핸들 정보를 확인할 수 없습니다: " + Marshal.GetLastWin32Error());

        if ((info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
            throw new IOException("링크 핸들은 지원하지 않습니다: " + expectedFullPath);

        if (requireDirectory)
        {
            if ((info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0)
                throw new IOException("폴더 핸들이 아닙니다: " + expectedFullPath);
        }
        else
        {
            if ((info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0)
                throw new IOException("파일 핸들이 아닙니다: " + expectedFullPath);
            if (info.NumberOfLinks > 1u)
                throw new IOException("하드 링크된 파일은 허용되지 않습니다: " + expectedFullPath);
        }

        StringBuilder sb = new StringBuilder(512);
        uint resultLength = GetFinalPathNameByHandleW(handle, sb, (uint)sb.Capacity, 0u);
        while (resultLength >= sb.Capacity)
        {
            sb = new StringBuilder((int)resultLength + 1);
            resultLength = GetFinalPathNameByHandleW(handle, sb, (uint)sb.Capacity, 0u);
        }

        if (resultLength == 0)
            throw new IOException("최종 파일 경로를 확인할 수 없습니다: " + Marshal.GetLastWin32Error());

        string finalPath = sb.ToString();
        if (String.IsNullOrEmpty(finalPath))
            throw new IOException("최종 파일 경로가 비어 있습니다.");
        if (finalPath.StartsWith("\\\\?\\UNC\\", StringComparison.OrdinalIgnoreCase))
            throw new IOException("네트워크(UNC) 최종 경로는 지원하지 않습니다.");
        if (finalPath.StartsWith("\\\\?\\", StringComparison.Ordinal))
            finalPath = finalPath.Substring(4);

        NoLinksCore(finalPath);

        if (!String.Equals(
                NormalizeFullPathNoTrailingSlash(finalPath),
                NormalizeFullPathNoTrailingSlash(expectedFullPath),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new IOException("열린 파일 경로가 예상 경로와 다릅니다: " + finalPath);
        }
    }

    internal static void VerifyOpenedHandle(FileStream stream, string expectedFullPath)
    {
        if (stream == null)
            throw new IOException("파일 스트림이 비어 있습니다.");
        if (String.IsNullOrEmpty(expectedFullPath))
            throw new IOException("확인할 파일 경로가 비어 있습니다.");

        if (Environment.OSVersion.Platform != PlatformID.Win32NT)
            return;

        VerifySafeHandle(stream.SafeFileHandle, expectedFullPath, false);
    }

    internal static SafeFileHandle PinParentDirectory(string fullPath)
    {
        string parentDir = Path.GetDirectoryName(Path.GetFullPath(fullPath));
        if (String.IsNullOrEmpty(parentDir) || !Directory.Exists(parentDir))
            throw new IOException("상위 폴더를 찾을 수 없습니다: " + fullPath);

        NoLinksCore(parentDir);

        if (Environment.OSVersion.Platform != PlatformID.Win32NT)
            return null;

        SafeFileHandle handle = CreateFileW(
            parentDir,
            1u,
            3u,
            IntPtr.Zero,
            3u,
            FILE_FLAG_BACKUP_SEMANTICS,
            IntPtr.Zero);
        try
        {
            if (handle == null || handle.IsInvalid)
                throw new IOException("상위 폴더 핸들을 열 수 없습니다: " + parentDir);
            VerifySafeHandle(handle, parentDir, true);
            return handle;
        }
        catch
        {
            if (handle != null)
                handle.Dispose();
            throw;
        }
    }

    internal static byte[] Read(string path)
    {
        if (!IsSaveFile(path))
            throw new IOException("귀곡팔황 세이브 파일(CacheData/CacheFixVer/*.cache)만 읽을 수 있습니다: " + path);

        NoLinks(path);
        string fullPath = Path.GetFullPath(path);

        using (FileStream stream = new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            VerifyOpenedHandle(stream, fullPath);
            if (stream.Length <= 0 || stream.Length > MaxSaveBytes)
                throw new IOException("세이브 파일 크기가 허용 범위(1B~32MiB)를 벗어났습니다: " + fullPath);
            return ReadFrom(stream, (int)stream.Length);
        }
    }

    internal static void WriteNew(string path, byte[] data, Action<Stream, byte[]> writer = null)
    {
        WriteAtomicNew(path, ".tmp-", data, writer, true);
    }

    private static void WriteAtomicNew(
        string path,
        string tempInfix,
        byte[] data,
        Action<Stream, byte[]> writer,
        bool allowBackup)
    {
        if (!IsAllowedWritePath(path, allowBackup))
            throw new IOException("쓰기 가능한 세이브 경로가 아닙니다: " + path);
        if (data == null || data.Length <= 0 || data.Length > MaxSaveBytes)
            throw new IOException("세이브 파일 데이터가 올바르지 않습니다.");
        if (Environment.OSVersion.Platform != PlatformID.Win32NT)
            throw new IOException("Windows NT 이상에서만 원자적 새 파일 쓰기를 지원합니다: " + path);

        NoLinks(path);
        string fullPath = Path.GetFullPath(path);
        if (File.Exists(fullPath))
            throw new IOException("이미 파일이 존재합니다: " + fullPath);

        string tmp = fullPath + tempInfix + Guid.NewGuid().ToString("N");
        NoLinksCore(tmp);
        SafeFileHandle hTmp = null;
        FileStream stream = null;
        bool renamed = false;
        try
        {
            using (SafeFileHandle dirPin = PinParentDirectory(fullPath))
            {
                hTmp = CreateFileW(tmp, 0xC0010000u, 0u, IntPtr.Zero, 1u, 0x80u, IntPtr.Zero);
                if (hTmp == null || hTmp.IsInvalid)
                {
                    int openErr = Marshal.GetLastWin32Error();
                    throw new IOException("임시 파일을 생성할 수 없습니다(" + openErr + "): " + tmp);
                }

                VerifySafeHandle(hTmp, tmp, false);
                stream = new FileStream(hTmp, FileAccess.ReadWrite);
                if (writer == null)
                {
                    WriteAndVerify(stream, data);
                }
                else
                {
                    writer(stream, data);
                    stream.Flush(true);
                    VerifyStreamHash(stream, data, "작성된 임시 파일 검증 실패: " + tmp);
                }

                Action<string> hook = TestBeforePublishHook;
                if (hook != null)
                    hook(fullPath);

                VerifySafeHandle(hTmp, tmp, false);
                VerifyStreamHash(stream, data, "게시 직전 임시 파일 무결성 검증 실패: " + tmp);
                if (File.Exists(fullPath))
                    throw new IOException("이미 파일이 존재합니다: " + fullPath);

                RenameExclusiveByHandle(hTmp, fullPath);
                renamed = true;
                VerifySafeHandle(hTmp, fullPath, false);
            }
        }
        catch (Exception innerEx)
        {
            if (!renamed)
            {
                Action<string, SafeFileHandle> failHook = TestOnTempFailureHook;
                if (failHook != null)
                    failHook(tmp, hTmp);
                string rbErr = DeleteOwnedHandleOnFailure(ref hTmp, ref stream, tmp);
                if (rbErr != null)
                    throw new IOException("임시 파일 정리에 실패했습니다: " + rbErr + " / 원인: " + innerEx.Message, innerEx);
            }
            if (innerEx is IOException)
                throw;
            throw new IOException("새 파일 작성에 실패했습니다: " + fullPath, innerEx);
        }
        finally
        {
            DisposeStreamAndHandleQuietly(ref stream, ref hTmp);
        }
    }

    private static void CreateLockedBackup(string backupPath, byte[] beforeBytes, out SafeFileHandle outHandle, out FileStream outStream)
    {
        outHandle = null;
        outStream = null;
        if (!IsAllowedWritePath(backupPath, true))
            throw new IOException("허용되지 않은 백업 경로입니다: " + backupPath);
        NoLinks(backupPath);
        string fullPath = Path.GetFullPath(backupPath);
        if (File.Exists(fullPath))
            throw new IOException("이미 백업 파일이 존재합니다: " + fullPath);

        SafeFileHandle h = null;
        FileStream s = null;
        try
        {
            using (SafeFileHandle dirPin = PinParentDirectory(fullPath))
            {
                h = CreateFileW(fullPath, 0xC0010000u, 0u, IntPtr.Zero, 1u, 0x80u, IntPtr.Zero);
                if (h == null || h.IsInvalid)
                {
                    int openErr = Marshal.GetLastWin32Error();
                    throw new IOException("백업 파일을 생성할 수 없습니다(" + openErr + "): " + fullPath);
                }

                VerifySafeHandle(h, fullPath, false);
                s = new FileStream(h, FileAccess.ReadWrite);
                WriteAndVerify(s, beforeBytes);
                outHandle = h;
                outStream = s;
            }
        }
        catch (Exception ex)
        {
            string rbErr = DeleteOwnedHandleOnFailure(ref h, ref s, fullPath);
            if (rbErr != null)
                throw new IOException("백업 생성 정리에 실패했습니다: " + rbErr + " / 원인: " + ex.Message, ex);
            throw;
        }
    }

    internal static string CopyWithBackup(
        string source,
        string destination,
        string expectedHash,
        byte[] data,
        Action<Stream, byte[]> writer = null)
    {
        if (String.IsNullOrEmpty(source) || String.IsNullOrEmpty(destination))
            throw new IOException("새 복사본 경로를 선택하세요.");
        if (!IsEditableSaveFile(destination))
            throw new IOException("편집 가능한 세이브 파일(CacheData/*.cache) 경로가 아닙니다: " + destination);
        if (data == null || data.Length <= 0 || data.Length > MaxSaveBytes)
            throw new IOException("32 MiB 이하의 유효한 세이브 데이터여야 합니다.");

        NoLinks(source);
        NoLinks(destination);

        string srcFull = Path.GetFullPath(source);
        string dstFull = Path.GetFullPath(destination);
        if (String.Equals(srcFull, dstFull, StringComparison.OrdinalIgnoreCase) || File.Exists(dstFull))
            throw new IOException("새 복사본 경로를 선택하세요. 기존 파일은 덮어쓰지 않습니다.");

        byte[] sourceBytes = Read(srcFull);
        if (!String.Equals(Hash(sourceBytes), expectedHash, StringComparison.OrdinalIgnoreCase))
            throw new IOException("원본 세이브 파일이 변경되었습니다.");

        string backup = dstFull + ".original-" + Guid.NewGuid().ToString("N") + ".bak";
        WriteNew(backup, sourceBytes, null);
        try
        {
            WriteAtomicNew(dstFull, ".pending-", data, writer, false);
            return backup;
        }
        catch (Exception ex)
        {
            throw new IOException("복사본 저장에 실패했습니다. 원본 및 백업은 보존되었습니다: " + backup + " / " + ex.Message, ex);
        }
    }

    internal static string ReplaceWithBackup(string path, string expectedHash, byte[] data)
    {
        if (String.IsNullOrEmpty(path))
            throw new IOException("경로가 비어 있습니다.");

        List<string> backups = ReplaceBatch(
            new BatchItem[]
            {
                new BatchItem
                {
                    Path = path,
                    ExpectedHash = expectedHash,
                    Data = data
                }
            },
            null);

        return backups[0];
    }

    internal static List<string> ReplaceBatch(IList<BatchItem> items, Action<int, Stream> faultInjector = null)
    {
        if (items == null || items.Count <= 0)
            throw new IOException("교체할 파일 목록이 비어 있습니다.");

        List<PreparedBatchEntry> callerOrder = new List<PreparedBatchEntry>(items.Count);
        HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        for (int i = 0; i < items.Count; i++)
        {
            BatchItem item = items[i];
            if (item == null || String.IsNullOrEmpty(item.Path))
                throw new IOException("파일 항목이 비어 있습니다.");
            if (!IsEditableSaveFile(item.Path))
                throw new IOException("편집 가능한 세이브 파일이 아닙니다: " + item.Path);
            if (item.Data == null || item.Data.Length <= 0 || item.Data.Length > MaxSaveBytes)
                throw new IOException("세이브 파일 데이터가 올바르지 않습니다: " + item.Path);

            string fullPath = Path.GetFullPath(item.Path);
            if (!seen.Add(fullPath))
                throw new IOException("중복된 파일 경로가 있습니다: " + fullPath);

            PreparedBatchEntry entry = new PreparedBatchEntry();
            entry.FullPath = fullPath;
            entry.ExpectedHash = item.ExpectedHash;
            entry.Data = item.Data;
            callerOrder.Add(entry);
        }

        List<PreparedBatchEntry> lockOrder = new List<PreparedBatchEntry>(callerOrder);
        lockOrder.Sort(CompareBatchEntries);

        List<string> createdBackups = new List<string>();
        string stamp = DateTime.UtcNow.ToString("yyyyMMddHHmmssfff");

        try
        {
            try
            {
                for (int i = 0; i < lockOrder.Count; i++)
                {
                    PreparedBatchEntry entry = lockOrder[i];
                    NoLinks(entry.FullPath);

                    entry.Stream = new FileStream(entry.FullPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                    VerifyOpenedHandle(entry.Stream, entry.FullPath);

                    if (entry.Stream.Length <= 0 || entry.Stream.Length > MaxSaveBytes)
                        throw new IOException("세이브 파일 크기가 올바르지 않습니다: " + entry.FullPath);

                    entry.Before = ReadFrom(entry.Stream, (int)entry.Stream.Length);
                    if (!String.Equals(Hash(entry.Before), entry.ExpectedHash, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("파일 해시가 일치하지 않습니다: " + entry.FullPath);
                }

                for (int i = 0; i < callerOrder.Count; i++)
                {
                    PreparedBatchEntry entry = callerOrder[i];
                    string backupPath = entry.FullPath + ".backup-" + stamp + "-" + Guid.NewGuid().ToString("N") + ".bak";
                    SafeFileHandle hBak;
                    FileStream bakStream;
                    CreateLockedBackup(backupPath, entry.Before, out hBak, out bakStream);
                    entry.BackupPath = Path.GetFullPath(backupPath);
                    entry.BackupHandle = hBak;
                    entry.BackupStream = bakStream;
                    createdBackups.Add(entry.BackupPath);

                    Action<int, string, SafeFileHandle> backupHook = TestAfterBackupCreatedHook;
                    if (backupHook != null)
                        backupHook(i, entry.BackupPath, entry.BackupHandle);

                    VerifySafeHandle(entry.BackupHandle, entry.BackupPath, false);
                    VerifyStreamHash(entry.BackupStream, entry.Before, "백업 파일 해시가 일치하지 않습니다: " + entry.BackupPath);
                }
            }
            catch (Exception phaseOneError)
            {
                List<string> cleanupErrors = new List<string>();
                for (int i = callerOrder.Count - 1; i >= 0; i--)
                {
                    if (callerOrder[i].BackupPath != null)
                    {
                        string rbErr = DeleteOwnedHandleOnFailure(ref callerOrder[i].BackupHandle, ref callerOrder[i].BackupStream, callerOrder[i].BackupPath);
                        if (rbErr != null)
                            cleanupErrors.Add(rbErr);
                    }
                }

                if (cleanupErrors.Count > 0)
                    throw new IOException("다중 파일 저장 준비 정리에 실패했습니다: " + String.Join(" | ", cleanupErrors.ToArray()) + " / 원인: " + phaseOneError.Message, phaseOneError);
                if (phaseOneError is IOException)
                    throw;
                throw new IOException("다중 파일 저장 준비에 실패했습니다.", phaseOneError);
            }

            int currentIndex = -1;
            try
            {
                for (int i = 0; i < callerOrder.Count; i++)
                {
                    currentIndex = i;
                    if (faultInjector != null)
                        faultInjector(i, callerOrder[i].Stream);

                    if (TestReplaceBatchFailAtCommitIndex >= 0 && i == TestReplaceBatchFailAtCommitIndex)
                        throw new IOException("테스트용 배치 커밋 중간 실패");

                    WriteAndVerify(callerOrder[i].Stream, callerOrder[i].Data);
                }
            }
            catch (Exception writeError)
            {
                List<string> rollbackFailures = new List<string>();
                for (int j = currentIndex; j >= 0; j--)
                {
                    try
                    {
                        VerifyStreamHash(callerOrder[j].BackupStream, callerOrder[j].Before, "롤백 백업 무결성 실패: " + callerOrder[j].BackupPath);
                        WriteAndVerify(callerOrder[j].Stream, callerOrder[j].Before);
                    }
                    catch (Exception restoreEx)
                    {
                        rollbackFailures.Add(callerOrder[j].FullPath + ": " + restoreEx.Message);
                    }
                }

                StringBuilder message = new StringBuilder();
                message.Append("다중 파일 저장 중 쓰기 실패가 발생했습니다. ");
                if (rollbackFailures.Count == 0)
                    message.Append("자동 롤백에 성공했습니다.");
                else
                    message.Append("자동 롤백에 실패했습니다.");

                message.Append(" 백업 파일: ");
                for (int i = 0; i < createdBackups.Count; i++)
                {
                    if (i > 0) message.Append(", ");
                    message.Append(createdBackups[i]);
                }

                if (rollbackFailures.Count > 0)
                {
                    message.Append(" 롤백 실패: ");
                    for (int i = 0; i < rollbackFailures.Count; i++)
                    {
                        if (i > 0) message.Append("; ");
                        message.Append(rollbackFailures[i]);
                    }
                }

                message.Append(" 쓰기 오류: ");
                message.Append(writeError.Message);
                throw new IOException(message.ToString(), writeError);
            }

            List<string> backups = new List<string>(callerOrder.Count);
            for (int i = 0; i < callerOrder.Count; i++)
                backups.Add(callerOrder[i].BackupPath);
            return backups;
        }
        finally
        {
            for (int i = 0; i < callerOrder.Count; i++)
                DisposeStreamAndHandleQuietly(ref callerOrder[i].BackupStream, ref callerOrder[i].BackupHandle);
            for (int i = 0; i < lockOrder.Count; i++)
            {
                FileStream stream = lockOrder[i].Stream;
                if (stream != null)
                {
                    try
                    {
                        stream.Dispose();
                    }
                    catch
                    {
                    }
                }
            }
        }
    }

    private static int CompareBatchEntries(PreparedBatchEntry a, PreparedBatchEntry b)
    {
        return StringComparer.OrdinalIgnoreCase.Compare(a.FullPath, b.FullPath);
    }

    internal static void UpdateOrRestore(Stream target, byte[] before, byte[] data, string backup)
    {
        if (target == null)
            throw new IOException("저장 대상이 없습니다. 백업: " + backup);
        if (before == null || before.Length <= 0 || before.Length > MaxSaveBytes)
            throw new IOException("32 MiB 이하의 세이브 데이터가 필요합니다.");
        if (data == null || data.Length <= 0 || data.Length > MaxSaveBytes)
            throw new IOException("32 MiB 이하의 세이브 데이터가 필요합니다.");

        try
        {
            WriteAndVerify(target, data);
        }
        catch (Exception writeError)
        {
            try
            {
                WriteAndVerify(target, before);
            }
            catch (Exception restoreError)
            {
                throw new IOException(
                    "저장 및 자동 원상복구에 실패했습니다. 게임을 열지 말고 백업을 복원하세요: " +
                    backup + " / " + restoreError.Message,
                    writeError);
            }

            throw new IOException("저장에 실패하여 원래 내용으로 복구했습니다. 백업: " + backup + " / " + writeError.Message, writeError);
        }
    }

    internal static void WriteAndVerify(Stream target, byte[] data)
    {
        if (target == null)
            throw new IOException("저장 대상이 없습니다.");
        if (data == null || data.Length <= 0 || data.Length > MaxSaveBytes)
            throw new IOException("32 MiB 이하의 세이브 데이터가 필요합니다.");

        target.Position = 0;
        target.Write(data, 0, data.Length);
        target.SetLength(data.Length);
        FileStream fs = target as FileStream;
        if (fs != null)
            fs.Flush(true);
        else
            target.Flush();

        target.Position = 0;
        byte[] actual = ReadFrom(target, data.Length);
        if (!String.Equals(Hash(actual), Hash(data), StringComparison.OrdinalIgnoreCase))
            throw new IOException("세이브 파일 해시 검증에 실패했습니다.");
    }

    private static byte[] ReadFrom(Stream stream, int length)
    {
        if (stream == null)
            throw new IOException("스트림이 비어 있습니다.");
        if (length < 0)
            throw new IOException("읽을 길이가 올바르지 않습니다.");

        byte[] buffer = new byte[length];
        int offset = 0;
        while (offset < length)
        {
            int read = stream.Read(buffer, offset, length - offset);
            if (read <= 0)
                throw new IOException("파일을 끝까지 읽을 수 없습니다.");
            offset += read;
        }
        return buffer;
    }
}
