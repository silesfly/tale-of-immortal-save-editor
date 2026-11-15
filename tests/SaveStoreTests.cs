// FILE: tests/SaveStoreTests.cs
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Microsoft.Win32.SafeHandles;

internal static class SaveStoreTests
{
    private static int total;
    private static int passed;

    private static void Assert(bool c, string m)
    {
        total++;
        if (!c) throw new Exception(m);
        passed++;
    }

    private static void Reject(Action a, string m)
    {
        try
        {
            a();
        }
        catch (IOException)
        {
            Assert(true, m);
            return;
        }
        catch (UnauthorizedAccessException)
        {
            Assert(true, m);
            return;
        }
        Assert(false, m);
    }

    private static void Same(byte[] a, byte[] b, string m)
    {
        Assert(a != null && b != null && a.SequenceEqual(b), m);
    }

    private static byte[] B(params byte[] x)
    {
        return x;
    }

    private sealed class FaultStream : MemoryStream
    {
        public int FailWrites;

        public FaultStream(byte[] initial) : base()
        {
            base.Write(initial, 0, initial.Length);
            Position = 0;
        }

        public override void Write(byte[] buffer, int offset, int count)
        {
            if (FailWrites > 0)
            {
                FailWrites--;
                if (count > 0) base.Write(buffer, offset, 1);
                throw new IOException("fault");
            }
            base.Write(buffer, offset, count);
        }
    }

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 1)
                throw new Exception("Usage: SaveStoreTests.exe <new_folder>");
            string root = Path.GetFullPath(args[0]);
            if (Directory.Exists(root))
                throw new Exception("Target folder already exists: " + root);
            Directory.CreateDirectory(root);

            string cacheA = Path.Combine(root, "O33a@9fkh++YwffVNeV1RA==.cache");
            string headerPath = Path.Combine(root, "CacheData");
            string fixVerPath = Path.Combine(root, "CacheFixVer");
            string jsonPath = Path.Combine(root, "c.json");
            string txtPath = Path.Combine(root, "d.txt");
            string bakPath = Path.Combine(root, "e.bak");
            byte[] data = B(1, 2, 3, 4, 5);
            string hash = SaveStore.Hash(data);

            // 1) File name / ADS / reserved device name validation
            Assert(SaveStore.MaxSaveBytes == 32 * 1024 * 1024, "max bytes");
            Assert(SaveStore.IsSaveFile(cacheA) && SaveStore.IsSaveFile(headerPath) && SaveStore.IsSaveFile(fixVerPath), "save files allowed");
            Assert(SaveStore.IsEditableSaveFile(cacheA) && SaveStore.IsEditableSaveFile(headerPath), "editable save files");
            Assert(!SaveStore.IsEditableSaveFile(fixVerPath), "CacheFixVer is read-only");
            Assert(!SaveStore.IsSaveFile(jsonPath) && !SaveStore.IsSaveFile(txtPath) && !SaveStore.IsSaveFile(bakPath), "other extensions rejected");
            Assert(!SaveStore.IsSaveFile(Path.Combine(root, "CON.cache")), "CON.cache rejected");
            Assert(!SaveStore.IsSaveFile(Path.Combine(root, "NUL")), "NUL rejected");
            Assert(!SaveStore.IsSaveFile(Path.Combine(root, "COM1.cache")), "COM1.cache rejected");
            Assert(!SaveStore.IsSaveFile(cacheA + ":evil"), "ADS colon rejected");
            Assert(SaveStore.HasInvalidColon(cacheA + ":evil"), "HasInvalidColon detects ADS");
            Assert(SaveStore.HasInvalidColon("C:relative.cache"), "HasInvalidColon detects drive-relative");

            // 2) WriteNew, Read, SHA-256 verification, CacheFixVer read-only enforcement
            SaveStore.WriteNew(cacheA, data);
            Same(SaveStore.Read(cacheA), data, "write/read cache");
            Assert(SaveStore.Hash(SaveStore.Read(cacheA)) == hash, "sha256 hash matches");

            SaveStore.WriteNew(headerPath, data);
            Same(SaveStore.Read(headerPath), data, "write/read CacheData");

            SaveStore.WriteNew(fixVerPath, B(56, 53));
            Same(SaveStore.Read(fixVerPath), B(56, 53), "write/read CacheFixVer");
            Reject(delegate { SaveStore.ReplaceWithBackup(fixVerPath, SaveStore.Hash(B(56, 53)), B(56, 54)); }, "ReplaceWithBackup rejects CacheFixVer");
            Reject(delegate { SaveStore.CopyWithBackup(cacheA, Path.Combine(root, "sub_CacheFixVer_err", "CacheFixVer"), hash, data, null); }, "CopyWithBackup rejects CacheFixVer");

            File.WriteAllBytes(txtPath, data);
            Reject(delegate { SaveStore.Read(jsonPath); }, "read rejects json");
            Reject(delegate { SaveStore.Read(txtPath); }, "read rejects txt");
            Reject(delegate { SaveStore.Read(bakPath); }, "read rejects bak");
            Reject(delegate { SaveStore.ReplaceWithBackup(txtPath, hash, data); }, "replace rejects txt");
            Reject(delegate { SaveStore.CopyWithBackup(cacheA, Path.Combine(root, "copy.txt"), hash, data, null); }, "copy rejects txt");
            Reject(delegate { SaveStore.WriteNew(cacheA, data); }, "writenew rejects overwrite");

            // 3) UNC, ADS, empty, >32MiB rejected
            Reject(delegate { SaveStore.NoLinks(@"\\server\share\slot.cache"); }, "unc path rejected");
            Reject(delegate { SaveStore.NoLinks(cacheA + ":ads"); }, "ADS NoLinks rejected");
            Reject(delegate { SaveStore.WriteNew(Path.Combine(root, "empty.cache"), new byte[0]); }, "empty write rejected");
            File.WriteAllBytes(Path.Combine(root, "zero.cache"), new byte[0]);
            Reject(delegate { SaveStore.Read(Path.Combine(root, "zero.cache")); }, "zero-byte read rejected");
            byte[] tooBig = new byte[SaveStore.MaxSaveBytes + 1];
            Reject(delegate { SaveStore.WriteNew(Path.Combine(root, "big.cache"), tooBig); }, "32MiB+ write rejected");
            Reject(delegate { SaveStore.ReplaceWithBackup(cacheA, hash, tooBig); }, "32MiB+ replace rejected");

            string bigRead = Path.Combine(root, "bigread.cache");
            using (FileStream bigReadStream = new FileStream(bigRead, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                bigReadStream.SetLength((long)SaveStore.MaxSaveBytes + 1);
            }
            Reject(delegate { SaveStore.Read(bigRead); }, "32MiB+ read rejected");

            // 4) ReplaceWithBackup & UpdateOrRestore rollback
            string rep = Path.Combine(root, "rep.cache");
            byte[] first = B(10, 11, 12);
            byte[] second = B(20, 21, 22, 23);
            SaveStore.WriteNew(rep, first);
            string b1 = SaveStore.ReplaceWithBackup(rep, SaveStore.Hash(first), second);
            Same(SaveStore.Read(rep), second, "replace updates slot");
            Assert(b1.IndexOf(".backup-", StringComparison.OrdinalIgnoreCase) >= 0 && b1.EndsWith(".bak", StringComparison.OrdinalIgnoreCase), "backup naming");
            Same(File.ReadAllBytes(b1), first, "backup preserves original bytes");
            Reject(delegate { SaveStore.ReplaceWithBackup(rep, "0000", second); }, "hash mismatch rejected");
            Same(SaveStore.Read(rep), first == second ? second : second, "slot preserved on hash mismatch");
            Same(SaveStore.Read(rep), second, "slot bytes intact on hash mismatch");

            byte[] before = B(30, 31, 32);
            byte[] after = B(40, 41, 42, 43);
            using (FaultStream temp = new FaultStream(before))
            {
                temp.FailWrites = 1;
                Reject(delegate { SaveStore.UpdateOrRestore(temp, before, after, "manual.bak"); }, "transient fault reported");
                Same(temp.ToArray(), before, "transient fault rolled back");
            }
            using (FaultStream perm = new FaultStream(before))
            {
                perm.FailWrites = int.MaxValue;
                try
                {
                    SaveStore.UpdateOrRestore(perm, before, after, "manual.bak");
                    Assert(false, "permanent fault must throw");
                }
                catch (IOException ex)
                {
                    Assert(ex.Message.Contains("manual.bak") && ex.Message.Contains("자동 원상복구에 실패"), "permanent fault reports backup");
                }
            }

            // 5) CopyWithBackup & partial write cleanup
            string src = Path.Combine(root, "src.cache");
            string dst = Path.Combine(root, "dst.cache");
            SaveStore.WriteNew(src, first);
            string origBak = SaveStore.CopyWithBackup(src, dst, SaveStore.Hash(first), second, null);
            Same(SaveStore.Read(src), first, "copy preserves source");
            Same(SaveStore.Read(dst), second, "copy writes destination");
            Same(File.ReadAllBytes(origBak), first, "copy original backup matches source");
            Reject(delegate { SaveStore.CopyWithBackup(src, src, SaveStore.Hash(first), second, null); }, "copy rejects same path");
            Reject(delegate { SaveStore.CopyWithBackup(src, dst, SaveStore.Hash(first), second, null); }, "copy rejects existing file");

            string b8 = Path.Combine(root, "b8.bak");
            Reject(delegate { SaveStore.WriteNew(b8, B(1, 1), delegate(Stream s, byte[] d) { s.WriteByte(9); throw new IOException("b8 partial"); }); }, "partial write rejected");
            Assert(!File.Exists(b8), "failed write leaves no file");
            Assert(Directory.GetFiles(root, "*.tmp-*").Length == 0, "failed write leaves no temp file");

            // 6) Win32 junction swap, hardlink block & PinParentDirectory
            if (Environment.OSVersion.Platform == PlatformID.Win32NT)
            {
                string hlReal = Path.Combine(root, "hl_real.cache");
                string hlLink = Path.Combine(root, "hl_link.cache");
                SaveStore.WriteNew(hlReal, B(9, 8, 7));
                Process hlProc = Process.Start(new ProcessStartInfo("cmd.exe", "/c fsutil hardlink create \"" + hlLink + "\" \"" + hlReal + "\"") { CreateNoWindow = true, UseShellExecute = false });
                hlProc.WaitForExit();
                if (File.Exists(hlLink))
                {
                    try
                    {
                        Reject(delegate { SaveStore.Read(hlLink); }, "hardlink read rejected");
                        Reject(delegate { SaveStore.ReplaceWithBackup(hlReal, SaveStore.Hash(B(9, 8, 7)), B(1, 1, 1)); }, "hardlink replace rejected");
                    }
                    finally
                    {
                        File.Delete(hlLink);
                    }
                }

                string jReal = Path.Combine(root, "jreal");
                string jEvil = Path.Combine(root, "jevil");
                int swapSeq = 0;
                Directory.CreateDirectory(jReal);
                Directory.CreateDirectory(jEvil);
                File.WriteAllBytes(Path.Combine(jReal, "v.cache"), B(3, 3, 3));
                File.WriteAllBytes(Path.Combine(jEvil, "v.cache"), B(3, 3, 3));
                Action<string> swapHook = delegate(string p)
                {
                    if (p.StartsWith(jReal, StringComparison.OrdinalIgnoreCase))
                    {
                        SaveStore.TestAfterNoLinksHook = null;
                        Directory.Move(jReal, jReal + "_orig" + (++swapSeq));
                        Process.Start(new ProcessStartInfo("cmd.exe", "/c mklink /J \"" + jReal + "\" \"" + jEvil + "\"") { CreateNoWindow = true, UseShellExecute = false }).WaitForExit();
                    }
                };
                try
                {
                    SaveStore.TestAfterNoLinksHook = swapHook;
                    Reject(delegate { SaveStore.Read(Path.Combine(jReal, "v.cache")); }, "read junction swap rejected");
                    Directory.Delete(jReal, false);
                    Directory.CreateDirectory(jReal);
                    File.WriteAllBytes(Path.Combine(jReal, "v.cache"), B(3, 3, 3));
                    SaveStore.TestAfterNoLinksHook = swapHook;
                    Reject(delegate { SaveStore.ReplaceWithBackup(Path.Combine(jReal, "v.cache"), SaveStore.Hash(B(3, 3, 3)), B(4, 4, 4)); }, "replace junction swap rejected");
                    Same(File.ReadAllBytes(Path.Combine(jEvil, "v.cache")), B(3, 3, 3), "evil target untouched");
                }
                finally
                {
                    SaveStore.TestAfterNoLinksHook = null;
                    if (Directory.Exists(jReal) && ((new DirectoryInfo(jReal).Attributes & FileAttributes.ReparsePoint) != 0))
                        Directory.Delete(jReal, false);
                }

                string pinDir = Path.Combine(root, "pin-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(pinDir);
                string pinFile = Path.Combine(pinDir, "pin.cache");
                bool pinBlocked = false;
                bool tmpWriteBlocked = false;
                bool tmpDeleteBlocked = false;
                try
                {
                    SaveStore.TestBeforePublishHook = delegate(string p)
                    {
                        try
                        {
                            Directory.Move(pinDir, pinDir + "_moved");
                        }
                        catch (IOException)
                        {
                            pinBlocked = true;
                        }
                        catch (UnauthorizedAccessException)
                        {
                            pinBlocked = true;
                        }

                        string[] tmpCandidates = Directory.GetFiles(pinDir, "pin.cache.tmp-*");
                        if (tmpCandidates.Length == 1)
                        {
                            try
                            {
                                File.WriteAllBytes(tmpCandidates[0], B(9, 9, 9));
                            }
                            catch (IOException)
                            {
                                tmpWriteBlocked = true;
                            }
                            catch (UnauthorizedAccessException)
                            {
                                tmpWriteBlocked = true;
                            }

                            try
                            {
                                File.Delete(tmpCandidates[0]);
                            }
                            catch (IOException)
                            {
                                tmpDeleteBlocked = true;
                            }
                            catch (UnauthorizedAccessException)
                            {
                                tmpDeleteBlocked = true;
                            }
                        }
                    };
                    SaveStore.WriteNew(pinFile, B(5, 6, 7));
                    Assert(pinBlocked, "parent directory pin blocks move");
                    Assert(tmpWriteBlocked, "exclusive handle blocks temp file overwrite before publish");
                    Assert(tmpDeleteBlocked, "exclusive handle blocks temp file delete/swap before publish");
                    Same(File.ReadAllBytes(pinFile), B(5, 6, 7), "pinned write succeeded");
                }
                finally
                {
                    SaveStore.TestBeforePublishHook = null;
                }
            }

            // 7) ReplaceBatch hash mismatch, fault rollback & TestReplaceBatchFailAtCommitIndex
            string b3a = Path.Combine(root, "b3a.cache");
            string b3b = Path.Combine(root, "b3b.cache");
            SaveStore.WriteNew(b3a, B(1, 1, 1));
            SaveStore.WriteNew(b3b, B(2, 2, 2));

            List<SaveStore.BatchItem> b3bad = new List<SaveStore.BatchItem>();
            b3bad.Add(new SaveStore.BatchItem { Path = b3a, ExpectedHash = SaveStore.Hash(B(1, 1, 1)), Data = B(7, 7, 7) });
            b3bad.Add(new SaveStore.BatchItem { Path = b3b, ExpectedHash = "0000", Data = B(8, 8, 8) });
            Reject(delegate { SaveStore.ReplaceBatch(b3bad, null); }, "batch hash mismatch rejected");
            Same(File.ReadAllBytes(b3a), B(1, 1, 1), "first file unchanged after hash mismatch");
            Same(File.ReadAllBytes(b3b), B(2, 2, 2), "second file unchanged after hash mismatch");
            Assert(Directory.GetFiles(root, "b3*.backup-*.bak").Length == 0, "no backups after hash mismatch");

            List<SaveStore.BatchItem> b3fault = new List<SaveStore.BatchItem>();
            b3fault.Add(new SaveStore.BatchItem { Path = b3a, ExpectedHash = SaveStore.Hash(B(1, 1, 1)), Data = B(7, 7, 7) });
            b3fault.Add(new SaveStore.BatchItem { Path = b3b, ExpectedHash = SaveStore.Hash(B(2, 2, 2)), Data = B(8, 8, 8) });
            Reject(delegate
            {
                SaveStore.ReplaceBatch(b3fault, delegate(int idx, Stream s)
                {
                    if (idx == 1)
                    {
                        s.Position = 0;
                        s.WriteByte(99);
                        throw new IOException("fault2");
                    }
                });
            }, "batch fault rejected");
            Same(File.ReadAllBytes(b3a), B(1, 1, 1), "first file rolled back after fault");
            Same(File.ReadAllBytes(b3b), B(2, 2, 2), "second file rolled back after fault");

            List<SaveStore.BatchItem> b3good = new List<SaveStore.BatchItem>();
            b3good.Add(new SaveStore.BatchItem { Path = b3a, ExpectedHash = SaveStore.Hash(B(1, 1, 1)), Data = B(7, 7, 7) });
            b3good.Add(new SaveStore.BatchItem { Path = b3b, ExpectedHash = SaveStore.Hash(B(2, 2, 2)), Data = B(8, 8, 8) });
            IList<string> b3backs = SaveStore.ReplaceBatch(b3good, null);
            Assert(b3backs.Count == 2, "batch returns two backups");
            Same(File.ReadAllBytes(b3a), B(7, 7, 7), "first file replaced");
            Same(File.ReadAllBytes(b3b), B(8, 8, 8), "second file replaced");

            try
            {
                SaveStore.TestReplaceBatchFailAtCommitIndex = 1;
                List<SaveStore.BatchItem> failBatch = new List<SaveStore.BatchItem>();
                failBatch.Add(new SaveStore.BatchItem { Path = b3a, ExpectedHash = SaveStore.Hash(B(7, 7, 7)), Data = B(9, 9, 9) });
                failBatch.Add(new SaveStore.BatchItem { Path = b3b, ExpectedHash = SaveStore.Hash(B(8, 8, 8)), Data = B(6, 6, 6) });
                Reject(delegate { SaveStore.ReplaceBatch(failBatch, null); }, "batch fails at commit index");
                Same(File.ReadAllBytes(b3a), B(7, 7, 7), "first file restored");
                Same(File.ReadAllBytes(b3b), B(8, 8, 8), "second file restored");
            }
            finally
            {
                SaveStore.TestReplaceBatchFailAtCommitIndex = -1;
            }

            // 8) Phase-1 backup & WriteNew temp handle-only delete + external replacement preservation
            {
                string b8Dir = Path.Combine(root, "b8");
                Directory.CreateDirectory(b8Dir);
                string w8a = Path.Combine(b8Dir, "a.cache");
                string w8b = Path.Combine(b8Dir, "b.cache");
                SaveStore.WriteNew(w8a, B(1, 2, 3), null);
                SaveStore.WriteNew(w8b, B(4, 5, 6), null);

                List<SaveStore.BatchItem> items8 = new List<SaveStore.BatchItem>();
                items8.Add(new SaveStore.BatchItem { Path = w8a, ExpectedHash = SaveStore.Hash(B(1, 2, 3)), Data = B(11, 12, 13) });
                items8.Add(new SaveStore.BatchItem { Path = w8b, ExpectedHash = SaveStore.Hash(B(4, 5, 6)), Data = B(21, 22, 23) });

                try
                {
                    SaveStore.TestAfterBackupCreatedHook = delegate(int idx, string bakFile, SafeFileHandle hBak)
                    {
                        if (idx == 0)
                        {
                            Reject(delegate { File.WriteAllBytes(bakFile, B(9, 9, 9)); }, "8a backup write blocked");
                            Reject(delegate { File.Delete(bakFile); }, "8a backup delete blocked");
                        }
                        else if (idx == 1)
                        {
                            throw new IOException("phase1 fault");
                        }
                    };
                    Reject(delegate { SaveStore.ReplaceBatch(items8, null); }, "8a phase1 fault rejected");
                }
                finally
                {
                    SaveStore.TestAfterBackupCreatedHook = null;
                }
                Assert(Directory.GetFiles(b8Dir, "*.backup-*.bak").Length == 0, "8a backups deleted by handle");

                string swappedBak = null;
                bool threw8b = false;
                try
                {
                    SaveStore.TestAfterBackupCreatedHook = delegate(int idx, string bakFile, SafeFileHandle hBak)
                    {
                        if (idx == 0)
                        {
                            swappedBak = bakFile;
                            hBak.Dispose();
                            File.WriteAllBytes(bakFile, B(42, 43, 44));
                        }
                    };
                    SaveStore.ReplaceBatch(items8, null);
                }
                catch (IOException ex8b)
                {
                    threw8b = swappedBak != null &&
                        ex8b.Message.IndexOf(swappedBak, StringComparison.OrdinalIgnoreCase) >= 0 &&
                        ex8b.Message.IndexOf("경로 보존", StringComparison.Ordinal) >= 0;
                }
                finally
                {
                    SaveStore.TestAfterBackupCreatedHook = null;
                }
                Assert(threw8b, "8b external backup replacement reported");
                Same(File.ReadAllBytes(swappedBak), B(42, 43, 44), "8b external backup replacement preserved");
                File.Delete(swappedBak);

                string w8new = Path.Combine(b8Dir, "new8.cache");
                string swappedTmp = null;
                bool threw8c = false;
                try
                {
                    SaveStore.TestOnTempFailureHook = delegate(string tmpFile, SafeFileHandle hTmp)
                    {
                        swappedTmp = tmpFile;
                        hTmp.Dispose();
                        File.WriteAllBytes(tmpFile, B(77, 88, 99));
                    };
                    SaveStore.WriteNew(w8new, B(1, 2, 3), delegate(Stream s, byte[] d) { throw new IOException("writer boom"); });
                }
                catch (IOException ex8c)
                {
                    threw8c = swappedTmp != null &&
                        ex8c.Message.IndexOf(swappedTmp, StringComparison.OrdinalIgnoreCase) >= 0 &&
                        ex8c.Message.IndexOf("경로 보존", StringComparison.Ordinal) >= 0 &&
                        ex8c.InnerException != null &&
                        ex8c.InnerException.Message.IndexOf("writer boom", StringComparison.Ordinal) >= 0;
                }
                finally
                {
                    SaveStore.TestOnTempFailureHook = null;
                }
                Assert(threw8c, "8c external temp replacement reported");
                Assert(!File.Exists(w8new), "8c target not created");
                Same(File.ReadAllBytes(swappedTmp), B(77, 88, 99), "8c external temp replacement preserved");
                File.Delete(swappedTmp);
            }

            Console.WriteLine("PASS " + passed + "/" + total);
            Environment.ExitCode = 0;
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("FAIL: " + ex.Message);
            Environment.ExitCode = 1;
            return 1;
        }
    }
}
