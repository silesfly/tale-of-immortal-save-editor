# FILE: tests/test_cli.py
import base64
import contextlib
import hashlib
import http.client
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import tale_of_immortal_editor as toi


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _make_demo_tree(base_dir: str):
    base = Path(base_dir)
    slot = base / "1_DEMO01"
    slot.mkdir(parents=True, exist_ok=True)

    header = {
        "name": "청운",
        "gradeID": 16,
        "worldDay": 1835,
        "gameLevel": 3,
        "createTicks": 637860102819648961,
    }
    world = {
        "playerUnitID": "DEMO01",
        "worldDay": 1835,
        "gameLevel": 3,
        "resurgeCount": 3,
        "animaWeapons": [1],
    }
    unit = {
        "allUnit": {
            "DEMO01": {
                "u": "SCH001",
                "q": {
                    "q": ["청", "운"],
                    "r": 1,
                    "d": 16,
                    "s": 45000,
                    "y": 360,
                    "u": 3600,
                    "x": 500,
                    "c": 800,
                    "v": 300,
                    "b": 400,
                    "n": 200,
                    "m": 300,
                    "l": 100,
                    "z": 200,
                    "5": 100,
                    "6": 200,
                    "qx": 100,
                    "qc": 200,
                    "1": 500,
                    "2": 300,
                    "i": 100,
                    "k": 100,
                    "j": 100,
                    "qt": 50,
                    "qb": [{"q": 102, "w": -1, "e": 0, "t": None}],
                    "qn": [],
                },
                "z": {
                    "allProps": [
                        {"q": "CUR001", "w": [1, 10001, 25000], "e": ""},
                        {"q": "CUR002", "w": [1, 10011, 1200], "e": ""},
                        {"q": "CUR003", "w": [1, 10041, 15], "e": ""},
                    ]
                },
                "k": {
                    "MRT001": {
                        "q": {"q": "MRT001", "w": [2, 0, 0, 1, 10111, 4, 3], "e": ""},
                        "w": 120,
                        "e": 0,
                        "r": {"allObject": {}},
                    }
                },
                "qe": {"y": 1001, "u": 2, "o": True, "e": 100, "h": 2, "j": 200},
            }
        },
        "curUnitIndexNum": 1,
    }
    school = {
        "allBuild": {
            "SCH001": {
                "id": "SCH001",
                "money": 25000,
                "reputation": 1200,
                "totalMember": 84,
                "values": ['{"name1ID":59,"name2ID":59}'],
                "propertyData": {
                    "fixName": None,
                    "prosperous": 1200,
                    "prosperousMax": 5000,
                    "loyal": 650,
                    "Loyal": 650,
                    "medicina": 2500,
                    "mine": 2400,
                    "largeArrayHP": 12000,
                    "largeArrayHPMax": 50000,
                },
            }
        }
    }
    glob = {
        "achievement": {
            "allAchievement": {
                "110001": {"count": 1, "achieved": True},
                "110002": {"count": 0, "achieved": False},
            }
        }
    }

    (slot / toi.FILE_NAMES["header"]).write_bytes(toi.encode_cache_data(header, mode="cipher-gzip"))
    (slot / toi.FILE_NAMES["fixVer"]).write_bytes(b"85")
    (slot / toi.FILE_NAMES["world"]).write_bytes(toi.encode_cache_data(world, mode="cipher-gzip"))
    (slot / toi.FILE_NAMES["unit"]).write_bytes(toi.encode_cache_data(unit, mode="cipher-gzip"))
    (slot / toi.FILE_NAMES["school"]).write_bytes(toi.encode_cache_data(school, mode="cipher-gzip"))
    (slot / "untouched_extra.cache").write_bytes(toi.encode_cache_data({"marker": "keep"}, mode="cipher-gzip"))
    (base / toi.FILE_NAMES["global"]).write_bytes(toi.encode_cache_data(glob, mode="cipher-gzip"))
    return base, slot


def _run_json(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = toi.main(argv)
    text = out.getvalue().strip()
    return rc, (json.loads(text) if text else None)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base, self.slot = _make_demo_tree(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cipher_gzip_cli_roundtrip_preserves_int64(self):
        src = self.slot / toi.FILE_NAMES["header"]
        plain = self.base / "plain.json"
        enc = self.base / "roundtrip.cache"
        self.assertEqual(toi.main(["decrypt", str(src), "-o", str(plain), "--pretty"]), 0)
        self.assertIn("637860102819648961", plain.read_text(encoding="utf-8"))
        self.assertEqual(toi.main(["encrypt", str(plain), "-o", str(enc)]), 0)
        mode, data = toi.decode_cache_bytes(enc.read_bytes())
        self.assertEqual(mode, "cipher-gzip")
        self.assertEqual(data["createTicks"], 637860102819648961)
        self.assertIsInstance(data["createTicks"], int)

    def test_encrypt_decrypt_refuse_existing_and_slot_targets(self):
        plain = self.base / "plain_guard.json"
        self.assertEqual(
            toi.main(["decrypt", str(self.slot / "CacheData"), "-o", str(plain)]), 0
        )

        def _sha(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        cache_sha_before = _sha(self.slot / "CacheData")
        globle = self.base / "DataGloble.cache"
        globle_sha_before = _sha(globle)

        with contextlib.redirect_stderr(io.StringIO()):
            # Existing slot file must not be overwritten and must not create backups.
            self.assertEqual(
                toi.main(["encrypt", str(plain), "-o", str(self.slot / "CacheData")]), 1
            )
            self.assertEqual(_sha(self.slot / "CacheData"), cache_sha_before)
            self.assertEqual(list(self.slot.glob("*.bak")), [])

            # Arbitrary file inside a save slot folder is refused.
            self.assertEqual(
                toi.main(
                    ["encrypt", str(plain), "-o", str(self.slot / "injected.cache")]
                ),
                1,
            )

            # Protected global cache file is refused and left untouched.
            self.assertEqual(
                toi.main(["encrypt", str(plain), "-o", str(self.base / "DataGloble.cache")]),
                1,
            )
            self.assertEqual(_sha(globle), globle_sha_before)

            # Protected version marker file is refused.
            self.assertEqual(
                toi.main(["encrypt", str(plain), "-o", str(self.base / "CacheFixVer")]),
                1,
            )

            # Running-game guard blocks writes.
            os.environ["TOISE_SIMULATE_GAME_RUNNING"] = "1"
            try:
                self.assertEqual(
                    toi.main(
                        [
                            "encrypt",
                            str(plain),
                            "-o",
                            str(self.base / "running_guard.cache"),
                        ]
                    ),
                    1,
                )
            finally:
                del os.environ["TOISE_SIMULATE_GAME_RUNNING"]

            # decrypt must also refuse an existing output file and slot-folder writes.
            self.assertEqual(
                toi.main(["decrypt", str(self.slot / "CacheData"), "-o", str(plain)]), 1
            )
            self.assertEqual(
                toi.main(
                    ["decrypt", str(self.slot / "CacheData"), "-o", str(self.base / "bad_out.cache")]
                ),
                1,
            )

    def test_inspect_validate_presets_json(self):
        rc, info = _run_json(["inspect", str(self.slot), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(info["name"], "청운")
        self.assertEqual(info["createTicks"], 637860102819648961)
        rc, val = _run_json(["validate", str(self.slot), "--json"])
        self.assertEqual(rc, 0)
        self.assertTrue(val["ok"])
        self.assertEqual(val["errors"], [])
        self.assertEqual(val["warnings"], [])
        rc, presets = _run_json(["presets", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual({p["id"] for p in presets}, set(toi.PRESET_IDS))

    def test_edit_to_output_dir_non_destructive(self):
        out_dir = self.base / "edited_slot"
        src_hash = _sha(self.slot / toi.FILE_NAMES["header"])
        args = [
            "edit", str(self.slot), "-o", str(out_dir), "--json",
            "--preset", "rich-cultivator",
            "--preset", "sect-prosperity",
            "--preset", "full-recovery",
            "--surname", "홍",
            "--given-name", "길동",
            "--grade", "34",
            "--world-day", "2400",
            "--set-prop", "qt=999",
            "--add-item", "10041:77",
            "--max-martials",
        ]
        rc, res = _run_json(args)
        self.assertEqual(rc, 0)
        self.assertGreaterEqual(len(res["written"]), 4)
        self.assertEqual(_sha(self.slot / toi.FILE_NAMES["header"]), src_hash)

        rc, val = _run_json(["validate", str(out_dir), "--json"])
        self.assertEqual(rc, 0)
        self.assertTrue(val["ok"])
        self.assertEqual(val["warnings"], [])

        rc, info = _run_json(["inspect", str(out_dir), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(info["name"], "홍길동")
        self.assertEqual(info["gradeID"], 34)
        self.assertEqual(info["worldDay"], 2400)
        self.assertEqual(info["spiritStones"], 9999999)
        self.assertEqual(info["cityTokens"], 9999 + 77)
        self.assertEqual(info["createTicks"], 637860102819648961)

    def test_edit_output_dir_refuses_concurrent_target_creation(self):
        out_a = self.base / "out_a"

        def after_untouched_copy(root_dir):
            (root_dir / "CacheData").write_bytes(b"EXTERNAL_RACED_HEADER")

        toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = after_untouched_copy
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                rc_a = toi.main(["edit", str(self.slot), "-o", str(out_a), "--surname", "홍"])
        finally:
            toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = None
        self.assertEqual(rc_a, 1)
        self.assertEqual((out_a / "CacheData").read_bytes(), b"EXTERNAL_RACED_HEADER")
        self.assertEqual(list(out_a.glob("*.bak")), [])
        self.assertEqual([p.name for p in out_a.iterdir()], ["CacheData"])

        out_b = self.base / "out_b"
        first_path = None
        raced_path = None

        def before_commit_replace_first(idx, target_path):
            nonlocal first_path, raced_path
            if idx == 0:
                first_path = target_path
            elif idx == 1:
                raced_path = target_path
                target_path.write_bytes(b"EXTERNAL_COMMIT_RACE")
                if os.name == "nt":
                    with self.assertRaises(OSError):
                        first_path.write_bytes(b"EXTERNAL_REPLACED_FIRST")
                else:
                    first_path.unlink()
                    first_path.write_bytes(b"EXTERNAL_REPLACED_FIRST")

        toi.TEST_BEFORE_COMMIT_HOOK = before_commit_replace_first
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                rc_b = toi.main(["edit", str(self.slot), "-o", str(out_b), "--surname", "임"])
        finally:
            toi.TEST_BEFORE_COMMIT_HOOK = None
        self.assertEqual(rc_b, 1)
        self.assertIsNotNone(first_path)
        self.assertIsNotNone(raced_path)
        self.assertEqual(raced_path.read_bytes(), b"EXTERNAL_COMMIT_RACE")
        self.assertEqual(list(out_b.glob("*.bak")), [])
        if os.name == "nt":
            self.assertEqual([p.name for p in out_b.iterdir()], [raced_path.name])
        else:
            self.assertEqual(first_path.read_bytes(), b"EXTERNAL_REPLACED_FIRST")
            self.assertEqual(sorted(p.name for p in out_b.iterdir()), sorted([first_path.name, raced_path.name]))

        out_c = self.base / "out_c"
        raced_c = None

        def before_commit_normal_rollback(idx, target_path):
            nonlocal raced_c
            if idx == 1:
                raced_c = target_path
                target_path.write_bytes(b"EXTERNAL_COMMIT_RACE_C")

        toi.TEST_BEFORE_COMMIT_HOOK = before_commit_normal_rollback
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                rc_c = toi.main(["edit", str(self.slot), "-o", str(out_c), "--surname", "박"])
        finally:
            toi.TEST_BEFORE_COMMIT_HOOK = None
        self.assertEqual(rc_c, 1)
        self.assertIsNotNone(raced_c)
        self.assertEqual(raced_c.read_bytes(), b"EXTERNAL_COMMIT_RACE_C")
        self.assertEqual([p.name for p in out_c.iterdir()], [raced_c.name])
        self.assertEqual(list(out_c.glob("*.bak")), [])

    def test_edit_in_place_backups_and_preserves_untouched(self):
        fix = self.slot / toi.FILE_NAMES["fixVer"]
        extra = self.slot / "untouched_extra.cache"
        hdr = self.slot / toi.FILE_NAMES["header"]
        unit = self.slot / toi.FILE_NAMES["unit"]
        glob = self.base / toi.FILE_NAMES["global"]
        fix_hash, extra_hash = _sha(fix), _sha(extra)
        hdr_orig, unit_orig, glob_orig = _sha(hdr), _sha(unit), _sha(glob)

        rc, _ = _run_json([
            "edit", str(self.slot), "--json",
            "--preset", "rich-cultivator",
            "--world-day", "1900",
            "--unlock-achievements",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(fix.read_bytes(), b"85")
        self.assertEqual(_sha(fix), fix_hash)
        self.assertEqual(_sha(extra), extra_hash)
        self.assertEqual(list(self.slot.glob("CacheFixVer.backup-*.bak")), [])
        self.assertEqual(list(self.slot.glob("untouched_extra.cache.backup-*.bak")), [])

        hdr_baks = list(self.slot.glob("CacheData.backup-*.bak"))
        unit_baks = list(self.slot.glob("O33a@9fkh++YwffVNeV1RA==.cache.backup-*.bak"))
        glob_baks = list(self.base.glob("DataGloble.cache.backup-*.bak"))
        self.assertEqual(len(hdr_baks), 1)
        self.assertEqual(len(unit_baks), 1)
        self.assertEqual(len(glob_baks), 1)
        self.assertEqual(_sha(hdr_baks[0]), hdr_orig)
        self.assertEqual(_sha(unit_baks[0]), unit_orig)
        self.assertEqual(_sha(glob_baks[0]), glob_orig)

    def test_process_guard_and_force(self):
        old = os.environ.get("TOISE_SIMULATE_GAME_RUNNING")
        os.environ["TOISE_SIMULATE_GAME_RUNNING"] = "1"
        try:
            hdr = self.slot / toi.FILE_NAMES["header"]
            h_before = _sha(hdr)
            with contextlib.redirect_stderr(io.StringIO()):
                rc_blocked = toi.main(["edit", str(self.slot), "--spirit-stones", "888888"])
            self.assertEqual(rc_blocked, 1)
            self.assertEqual(_sha(hdr), h_before)
            rc_forced, _ = _run_json(["edit", str(self.slot), "--spirit-stones", "888888", "--force", "--json"])
            self.assertEqual(rc_forced, 0)
        finally:
            if old is None:
                os.environ.pop("TOISE_SIMULATE_GAME_RUNNING", None)
            else:
                os.environ["TOISE_SIMULATE_GAME_RUNNING"] = old

    def test_filename_and_path_guards(self):
        self.assertFalse(toi.is_valid_cache_filename("CON.cache"))
        self.assertFalse(toi.is_valid_cache_filename("NUL"))
        self.assertFalse(toi.is_valid_cache_filename("a:b.cache"))
        self.assertFalse(toi.is_valid_cache_filename("../escape.cache"))
        with self.assertRaises(PermissionError):
            toi.assert_safe_path(self.base / "CON.cache", root_anchor=self.base)
        with self.assertRaises(PermissionError):
            toi.assert_safe_path(Path(str(self.slot / "CacheData") + ":ads"), root_anchor=self.base)

        if os.name == "nt":
            junc = self.base / "dirjunc"
            subprocess.run(["cmd", "/c", "mklink", "/J", str(junc), str(self.slot)], check=True, capture_output=True)
            try:
                with self.assertRaises(PermissionError):
                    toi.assert_safe_path(junc / "CacheData", root_anchor=self.base)
                self.assertFalse(toi._is_slot_dir(junc, root_anchor=self.base))
            finally:
                os.rmdir(str(junc))
        else:
            link = self.base / "link.cache"
            link.symlink_to(self.slot / toi.FILE_NAMES["header"])
            with self.assertRaises(PermissionError):
                toi.assert_safe_path(link, root_anchor=self.base)

            dlink = self.base / "dirlink"
            dlink.symlink_to(self.slot, target_is_directory=True)
            with self.assertRaises(PermissionError):
                toi.assert_safe_path(dlink / "CacheData", root_anchor=self.base)

        hard = self.base / "hard.cache"
        os.link(self.slot / toi.FILE_NAMES["header"], hard)
        try:
            with self.assertRaises(PermissionError):
                toi.assert_safe_path(hard, root_anchor=self.base)
        finally:
            hard.unlink()

        with self.assertRaises(ValueError):
            toi.replace_batch_safely(
                [{"path": self.slot / toi.FILE_NAMES["fixVer"], "data": b"86"}],
                force=True,
                root_anchor=self.base,
            )

    def test_mid_batch_rollback(self):
        files = [self.slot / f"rb{i}.cache" for i in range(3)]
        originals = [b"orig-0", b"orig-1", b"orig-2"]
        for p, b in zip(files, originals):
            p.write_bytes(b)
        old = toi.TEST_FAIL_AT_COMMIT_INDEX
        toi.TEST_FAIL_AT_COMMIT_INDEX = 1
        try:
            with self.assertRaises(OSError):
                toi.replace_batch_safely(
                    [{"path": p, "data": b"mutated"} for p in files],
                    force=True,
                    root_anchor=self.base,
                )
            for p, b in zip(files, originals):
                self.assertEqual(p.read_bytes(), b)
        finally:
            toi.TEST_FAIL_AT_COMMIT_INDEX = old

    def test_rollback_failure_preserves_backup(self):
        files = [self.slot / f"rbfail{i}.cache" for i in range(2)]
        originals = [b"orig-rb-0", b"orig-rb-1"]
        for p, b in zip(files, originals):
            p.write_bytes(b)
        old_idx = toi.TEST_FAIL_AT_COMMIT_INDEX
        old_rb = toi.TEST_FAIL_ROLLBACK
        toi.TEST_FAIL_AT_COMMIT_INDEX = 1
        toi.TEST_FAIL_ROLLBACK = True
        try:
            with self.assertRaises(RuntimeError):
                toi.replace_batch_safely(
                    [{"path": p, "data": b"mutated"} for p in files],
                    force=True,
                    root_anchor=self.base,
                )
            baks0 = list(self.slot.glob("rbfail0.cache.backup-*.bak"))
            self.assertEqual(len(baks0), 1)
            self.assertEqual(baks0[0].read_bytes(), b"orig-rb-0")
            self.assertEqual(list(self.slot.glob("rbfail1.cache.backup-*.bak")), [])
        finally:
            toi.TEST_FAIL_AT_COMMIT_INDEX = old_idx
            toi.TEST_FAIL_ROLLBACK = old_rb

    def test_edit_rejects_non_empty_output_dir(self):
        out_dir = self.base / "non_empty_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        stray = out_dir / "other_slot.cache"
        stray.write_bytes(b"other-slot-bytes")
        with contextlib.redirect_stderr(io.StringIO()):
            rc = toi.main(["edit", str(self.slot), "-o", str(out_dir), "--spirit-stones", "777777"])
        self.assertEqual(rc, 1)
        self.assertEqual(stray.read_bytes(), b"other-slot-bytes")

    def test_concurrent_http_save_same_session_serialized(self):
        srv = toi.create_http_server(save_dir=str(self.base), host="127.0.0.1", port=0)
        host, port = srv.server_address
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            json_hdrs = {"Content-Type": "application/json", "X-Toi-Token": srv.csrf_token}
            c0 = http.client.HTTPConnection(host, port, timeout=5)
            c0.request("POST", "/api/load-slot", body=json.dumps({"slot": "1_DEMO01"}).encode(), headers=json_hdrs)
            loaded = json.loads(c0.getresponse().read())
            c0.close()
            sid = loaded["session"]
            hdr_entry = next(f for f in loaded["files"] if f["name"] == "CacheData")
            _, hdr_obj = toi.decode_cache_bytes(base64.b64decode(hdr_entry["base64"]))

            barrier = threading.Barrier(2)
            statuses = []
            lock = threading.Lock()

            def worker(day_val: int) -> None:
                obj = dict(hdr_obj)
                obj["worldDay"] = day_val
                b64 = base64.b64encode(toi.encode_cache_data(obj, mode="cipher-gzip")).decode("ascii")
                payload = json.dumps({
                    "slot": "1_DEMO01",
                    "session": sid,
                    "files": [{"name": "CacheData", "relativePath": "CacheData", "base64": b64}],
                }).encode()
                conn = http.client.HTTPConnection(host, port, timeout=5)
                barrier.wait(timeout=5)
                conn.request("POST", "/api/save-slot", body=payload, headers=json_hdrs)
                st = conn.getresponse().status
                conn.close()
                with lock:
                    statuses.append(st)

            workers = [threading.Thread(target=worker, args=(3001,)), threading.Thread(target=worker, args=(3002,))]
            for w in workers:
                w.start()
            for w in workers:
                w.join(timeout=5)
            self.assertEqual(sorted(statuses), [200, 409])
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2)

    def test_pinned_directory_blocks_post_check_swap(self):
        with tempfile.TemporaryDirectory() as out_tmp:
            outside = Path(out_tmp)
            ext_file = outside / "victim.cache"
            ext_file.write_bytes(b"outside-untouched")
            victim_dir = self.base / "swap_slot"
            victim_dir.mkdir(parents=True, exist_ok=True)
            (victim_dir / "victim.cache").write_bytes(b"inside-orig")

            def swap_to_symlink(clean_parent: Path) -> None:
                if clean_parent == victim_dir and not toi._is_reparse_or_link(victim_dir):
                    os.rename(str(victim_dir), str(self.base / "swap_slot_moved"))
                    if os.name == "nt":
                        subprocess.run(["cmd", "/c", "mklink", "/J", str(victim_dir), str(outside)], check=True, capture_output=True)
                    else:
                        os.symlink(str(outside), str(victim_dir), target_is_directory=True)

            old_hook = toi.TEST_AFTER_PIN_HOOK
            toi.TEST_AFTER_PIN_HOOK = swap_to_symlink
            try:
                with self.assertRaises(PermissionError):
                    toi.replace_batch_safely(
                        [{"path": victim_dir / "victim.cache", "data": b"evil-overwrite"}],
                        force=True,
                        root_anchor=self.base,
                    )
                self.assertEqual(ext_file.read_bytes(), b"outside-untouched")
            finally:
                toi.TEST_AFTER_PIN_HOOK = old_hook
                if os.name == "nt" and toi._is_reparse_or_link(victim_dir):
                    os.rmdir(str(victim_dir))

    def test_http_security_and_e2e(self):
        with self.assertRaises(ValueError):
            toi.create_http_server(save_dir=str(self.base), host="0.0.0.0", port=0)

        srv = toi.create_http_server(save_dir=str(self.base), host="127.0.0.1", port=0)
        host, port = srv.server_address
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            def req(method, path, body=None, headers=None):
                c = http.client.HTTPConnection(host, port, timeout=5)
                c.request(method, path, body=body, headers=headers or {})
                r = c.getresponse()
                data = r.read()
                c.close()
                return r.status, r.getheaders(), data

            st, hs, body = req("GET", "/")
            self.assertEqual(st, 200)
            self.assertIn(b"window.__TOI_SERVER_CONFIG__", body)
            self.assertTrue(any(k.lower() == "content-security-policy" and "default-src 'none'" in v for k, v in hs))

            self.assertEqual(req("GET", "/api/slots", headers={"Host": "evil.example", "X-Toi-Token": srv.csrf_token})[0], 403)
            self.assertEqual(req("GET", "/api/slots", headers={"Sec-Fetch-Site": "cross-site", "X-Toi-Token": srv.csrf_token})[0], 403)
            self.assertEqual(req("GET", "/api/slots", headers={"X-Toi-Token": "wrong"})[0], 403)
            self.assertEqual(
                req("POST", "/api/load-slot", body=b"{}", headers={"Content-Type": "text/plain", "X-Toi-Token": srv.csrf_token})[0],
                415,
            )
            self.assertEqual(
                req("POST", "/api/load-slot", body=b"{}", headers={"Content-Type": "application/json", "Origin": "https://evil.example", "X-Toi-Token": srv.csrf_token})[0],
                403,
            )

            json_hdrs = {"Content-Type": "application/json", "X-Toi-Token": srv.csrf_token}
            st, _, body = req("GET", "/api/slots", headers={"X-Toi-Token": srv.csrf_token})
            self.assertEqual(st, 200)
            slots = json.loads(body)["slots"]
            self.assertEqual(slots[0]["slot"], "1_DEMO01")

            st, _, body = req("POST", "/api/load-slot", body=json.dumps({"slot": "1_DEMO01"}).encode(), headers=json_hdrs)
            self.assertEqual(st, 200)
            loaded = json.loads(body)
            sid = loaded["session"]
            hdr_entry = next(f for f in loaded["files"] if f["name"] == "CacheData")
            _, hdr_obj = toi.decode_cache_bytes(base64.b64decode(hdr_entry["base64"]))
            hdr_obj["worldDay"] = 2222
            new_b64 = base64.b64encode(toi.encode_cache_data(hdr_obj, mode="cipher-gzip")).decode("ascii")

            save_payload = {
                "slot": "1_DEMO01",
                "session": sid,
                "files": [{"name": "CacheData", "relativePath": "CacheData", "base64": new_b64}],
            }
            st, _, body = req("POST", "/api/save-slot", body=json.dumps(save_payload).encode(), headers=json_hdrs)
            self.assertEqual(st, 200)
            saved = json.loads(body)
            self.assertNotEqual(saved["session"], sid)
            self.assertEqual(len(list(self.slot.glob("CacheData.backup-*.bak"))), 1)

            # Re-using stale session ID -> 409
            st, _, _ = req("POST", "/api/save-slot", body=json.dumps(save_payload).encode(), headers=json_hdrs)
            self.assertEqual(st, 409)

            # External tamper on disk before save -> 409
            (self.slot / "CacheData").write_bytes(b"external-tamper")
            tamper_payload = {
                "slot": "1_DEMO01",
                "session": saved["session"],
                "files": [{"name": "CacheData", "relativePath": "CacheData", "base64": new_b64}],
            }
            st, _, _ = req("POST", "/api/save-slot", body=json.dumps(tamper_payload).encode(), headers=json_hdrs)
            self.assertEqual(st, 409)
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2)

    def test_pre_commit_external_tamper_aborts_and_rolls_back(self):
        f0 = self.slot / "tamper0.cache"
        f1 = self.slot / "tamper1.cache"
        f0.write_bytes(b"orig-a")
        f1.write_bytes(b"orig-b")
        h0, h1 = _sha(f0), _sha(f1)

        if os.name == "nt":
            ext_blocked = []

            def win_hook(idx: int, target_path: Path) -> None:
                if idx == 1:
                    proc = subprocess.run(
                        [sys.executable, "-c", "import sys; open(sys.argv[1], 'r+b').write(b'ext')", str(target_path)],
                        capture_output=True,
                        text=True,
                    )
                    ext_blocked.append(proc.returncode != 0)

            old_hook = toi.TEST_BEFORE_COMMIT_HOOK
            toi.TEST_BEFORE_COMMIT_HOOK = win_hook
            try:
                res = toi.replace_batch_safely(
                    [
                        {"path": f0, "data": b"new-a", "expected_sha256": h0},
                        {"path": f1, "data": b"new-b", "expected_sha256": h1},
                    ],
                    force=True,
                    root_anchor=self.base,
                )
                self.assertEqual(ext_blocked, [True])
                self.assertEqual(f0.read_bytes(), b"new-a")
                self.assertEqual(f1.read_bytes(), b"new-b")
                self.assertEqual(res["hashes"][str(f0)], _sha(f0))
            finally:
                toi.TEST_BEFORE_COMMIT_HOOK = old_hook
        else:
            coop_blocked = []

            def posix_hook(idx: int, target_path: Path) -> None:
                if idx == 1:
                    lock_file = target_path.parent / f".toi-lock-{target_path.name}"
                    proc = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import fcntl, os, sys; fd=os.open(sys.argv[1], os.O_RDWR); fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)",
                            str(lock_file),
                        ],
                        capture_output=True,
                    )
                    coop_blocked.append(proc.returncode != 0)
                    target_path.write_bytes(b"uncooperative-ext-b")

            old_hook = toi.TEST_BEFORE_COMMIT_HOOK
            toi.TEST_BEFORE_COMMIT_HOOK = posix_hook
            try:
                with self.assertRaises(RuntimeError):
                    toi.replace_batch_safely(
                        [
                            {"path": f0, "data": b"new-a", "expected_sha256": h0},
                            {"path": f1, "data": b"new-b", "expected_sha256": h1},
                        ],
                        force=True,
                        root_anchor=self.base,
                    )
                self.assertEqual(coop_blocked, [True])
                self.assertEqual(f0.read_bytes(), b"orig-a")
                self.assertEqual(f1.read_bytes(), b"uncooperative-ext-b")
            finally:
                toi.TEST_BEFORE_COMMIT_HOOK = old_hook

    def test_load_and_http_read_block_post_check_swap(self):
        with tempfile.TemporaryDirectory() as out_tmp:
            secret_file = Path(out_tmp) / "secret.txt"
            secret_file.write_bytes(b"SECRET_OUTSIDE_PAYLOAD_DO_NOT_LEAK")

            srv = toi.create_http_server(save_dir=str(self.base), host="127.0.0.1", port=0)
            host, port = srv.server_address
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            json_hdrs = {"Content-Type": "application/json", "X-Toi-Token": srv.csrf_token}
            try:
                # 1. Invalid non-cache content disguised as CacheData -> rejected with 400
                bad_slot = self.base / "2_BADFMT"
                bad_slot.mkdir(parents=True, exist_ok=True)
                (bad_slot / "CacheData").write_bytes(b"NOT_A_VALID_CACHE_OR_JSON")
                c_bad = http.client.HTTPConnection(host, port, timeout=5)
                c_bad.request("POST", "/api/load-slot", body=json.dumps({"slot": "2_BADFMT"}).encode(), headers=json_hdrs)
                r_bad = c_bad.getresponse()
                body_bad = r_bad.read()
                c_bad.close()
                self.assertEqual(r_bad.status, 400)
                self.assertNotIn(b"NOT_A_VALID_CACHE_OR_JSON", body_bad)

                # 2. Post-check leaf swap right before read_leaf_bytes in both SlotSession.load and /api/load-slot
                swap_slot = self.base / "3_SWAPRD"
                swap_slot.mkdir(parents=True, exist_ok=True)
                orig_hdr = (self.slot / "CacheData").read_bytes()
                hdr_target = swap_slot / "CacheData"
                hdr_target.write_bytes(orig_hdr)

                def swap_leaf_before_read(clean_parent: Path, leaf_name: str) -> None:
                    if clean_parent == swap_slot and leaf_name == "CacheData" and not os.path.islink(str(hdr_target)):
                        hdr_target.unlink()
                        if os.name == "nt":
                            # On Windows without symlink privilege, plant a hardlink if same volume or test directory junction swap
                            try:
                                os.symlink(str(secret_file), str(hdr_target))
                            except OSError:
                                same_vol_secret = self.base / "outside_hard_secret.txt"
                                same_vol_secret.write_bytes(b"SECRET_OUTSIDE_PAYLOAD_DO_NOT_LEAK")
                                os.link(str(same_vol_secret), str(hdr_target))
                        else:
                            os.symlink(str(secret_file), str(hdr_target))

                old_leaf_hook = toi.TEST_BEFORE_LEAF_READ_HOOK
                toi.TEST_BEFORE_LEAF_READ_HOOK = swap_leaf_before_read
                try:
                    with self.assertRaises(PermissionError):
                        toi.SlotSession.load(swap_slot, include_parent_global=False)

                    if os.path.lexists(str(hdr_target)):
                        os.unlink(str(hdr_target))
                    hdr_target.write_bytes(orig_hdr)

                    c_sw = http.client.HTTPConnection(host, port, timeout=5)
                    c_sw.request("POST", "/api/load-slot", body=json.dumps({"slot": "3_SWAPRD"}).encode(), headers=json_hdrs)
                    r_sw = c_sw.getresponse()
                    body_sw = r_sw.read()
                    c_sw.close()
                    self.assertEqual(r_sw.status, 400)
                    self.assertNotIn(b"SECRET_OUTSIDE_PAYLOAD", body_sw)
                    self.assertNotIn(base64.b64encode(b"SECRET_OUTSIDE_PAYLOAD_DO_NOT_LEAK"), body_sw)
                finally:
                    toi.TEST_BEFORE_LEAF_READ_HOOK = old_leaf_hook
                    if os.path.lexists(str(hdr_target)):
                        os.unlink(str(hdr_target))
            finally:
                srv.shutdown()
                srv.server_close()
                t.join(timeout=2)

    def test_posix_publish_blocks_tmp_swap(self):
        dst = self.slot / "pubguard.cache"
        dst.write_bytes(b"safe-original")

        if os.name == "nt":
            blocked = []

            def win_pub_hook(tmp_path: Path) -> None:
                try:
                    tmp_path.write_bytes(b"evil-injected")
                    blocked.append(False)
                except PermissionError:
                    blocked.append(True)

            old = toi.TEST_BEFORE_PUBLISH_HOOK
            toi.TEST_BEFORE_PUBLISH_HOOK = win_pub_hook
            try:
                toi._write_output_atomic(dst, b"verified-new", root_anchor=self.base)
                self.assertEqual(blocked, [True])
                self.assertEqual(dst.read_bytes(), b"verified-new")
            finally:
                toi.TEST_BEFORE_PUBLISH_HOOK = old
        else:
            stage_modes = []
            swapped_paths = []

            def posix_pub_hook(tmp_path: Path) -> None:
                st_dir = os.stat(tmp_path.parent, follow_symlinks=False)
                stage_modes.append(st_dir.st_mode & 0o777)
                swapped_paths.append(tmp_path)
                tmp_path.unlink()
                tmp_path.write_bytes(b"evil-injected")

            old = toi.TEST_BEFORE_PUBLISH_HOOK
            toi.TEST_BEFORE_PUBLISH_HOOK = posix_pub_hook
            try:
                with self.assertRaises(RuntimeError) as cm:
                    toi._write_output_atomic(dst, b"verified-new", root_anchor=self.base)
                self.assertIsInstance(cm.exception.__cause__, PermissionError)
                self.assertTrue(swapped_paths)
                self.assertIn(str(swapped_paths[0]), str(cm.exception))
                self.assertIn("외부 파일 보존", str(cm.exception))
                self.assertEqual(stage_modes, [0o700])
                self.assertEqual(dst.read_bytes(), b"safe-original")
                self.assertEqual(len(swapped_paths), 1)
                self.assertTrue(swapped_paths[0].is_file())
                self.assertEqual(swapped_paths[0].read_bytes(), b"evil-injected")
            finally:
                toi.TEST_BEFORE_PUBLISH_HOOK = old
                if swapped_paths:
                    try:
                        if swapped_paths[0].exists():
                            swapped_paths[0].unlink()
                    except OSError:
                        pass
                    try:
                        if swapped_paths[0].parent.exists():
                            swapped_paths[0].parent.rmdir()
                    except OSError:
                        pass

            moved_prepub = self.base / "moved_prepub_stage"
            moved_post_new = self.base / "moved_post_new_stage"
            moved_batch = self.slot / "moved_batch_stage"
            dst_new = self.base / "posix_stage_post_new.json"
            old_stage_rmdir = toi.TEST_BEFORE_STAGE_RMDIR_HOOK

            def _rm_quiet(*paths):
                for p in paths:
                    if p is None:
                        continue
                    try:
                        if p.exists():
                            if p.is_dir():
                                p.rmdir()
                            else:
                                p.unlink()
                    except OSError:
                        pass

            def _make_stage_swap(moved_dst, from_parent=False):
                st = {"stage_dir": None, "ext_stage": None, "ext_ino": None}

                def hook(tmp_path: Path) -> None:
                    base = tmp_path.parent if from_parent else tmp_path
                    st["stage_dir"] = base
                    base.rename(moved_dst)
                    os.mkdir(base, 0o755)
                    st_ext = os.stat(base, follow_symlinks=False)
                    st["ext_ino"] = (st_ext.st_dev, st_ext.st_ino)
                    st["ext_stage"] = base

                return st, hook

            try:
                st_prepub, hk_prepub = _make_stage_swap(moved_prepub, from_parent=True)
                try:
                    toi.TEST_BEFORE_PUBLISH_HOOK = hk_prepub
                    with self.assertRaises(RuntimeError) as cm:
                        toi._write_output_atomic(dst, b"verified-new", root_anchor=self.base)
                    self.assertIsInstance(cm.exception.__cause__, PermissionError)
                    self.assertIn(str(st_prepub["ext_stage"]), str(cm.exception))
                    self.assertIn("외부 디렉터리 보존", str(cm.exception))
                    self.assertEqual(dst.read_bytes(), b"safe-original")
                    self.assertEqual(
                        (os.stat(st_prepub["ext_stage"]).st_dev, os.stat(st_prepub["ext_stage"]).st_ino),
                        st_prepub["ext_ino"],
                    )
                    self.assertEqual(list(moved_prepub.iterdir()), [])
                finally:
                    toi.TEST_BEFORE_PUBLISH_HOOK = old
                    _rm_quiet(st_prepub["ext_stage"], moved_prepub)

                st_post_new, hk_post_new = _make_stage_swap(moved_post_new)
                try:
                    toi.TEST_BEFORE_STAGE_RMDIR_HOOK = hk_post_new
                    with self.assertRaises(RuntimeError) as cm:
                        toi._write_output_atomic(dst_new, b"{}", root_anchor=self.base, replace_existing=False)
                    self.assertIsNone(cm.exception.__cause__)
                    self.assertIn(str(st_post_new["ext_stage"]), str(cm.exception))
                    self.assertIn("외부 디렉터리 보존", str(cm.exception))
                    self.assertFalse(dst_new.exists())
                    self.assertEqual(
                        (os.stat(st_post_new["ext_stage"]).st_dev, os.stat(st_post_new["ext_stage"]).st_ino),
                        st_post_new["ext_ino"],
                    )
                finally:
                    toi.TEST_BEFORE_STAGE_RMDIR_HOOK = old_stage_rmdir
                    _rm_quiet(st_post_new["ext_stage"], moved_post_new, dst_new)

                hdr_path = self.slot / "CacheData"
                orig_hdr = hdr_path.read_bytes()
                orig_sha = hashlib.sha256(orig_hdr).hexdigest()
                st_batch, hk_batch = _make_stage_swap(moved_batch)
                try:
                    toi.TEST_BEFORE_STAGE_RMDIR_HOOK = hk_batch
                    with self.assertRaises(RuntimeError) as cm:
                        toi.replace_batch_safely(
                            [{"path": hdr_path, "data": b"NEW_HDR_DATA", "expected_sha256": orig_sha}],
                            force=True,
                            root_anchor=self.base,
                        )
                    self.assertIsNone(cm.exception.__cause__)
                    self.assertIn(str(st_batch["ext_stage"]), str(cm.exception))
                    self.assertIn("외부 디렉터리 보존", str(cm.exception))
                    self.assertEqual(hdr_path.read_bytes(), orig_hdr)
                    self.assertEqual(list(self.slot.glob("CacheData.backup-*.bak")), [])
                    self.assertEqual(
                        (os.stat(st_batch["ext_stage"]).st_dev, os.stat(st_batch["ext_stage"]).st_ino),
                        st_batch["ext_ino"],
                    )
                finally:
                    toi.TEST_BEFORE_STAGE_RMDIR_HOOK = old_stage_rmdir
                    _rm_quiet(st_batch["ext_stage"], moved_batch)

                import errno
                from unittest import mock
                leftover_stages = []
                try:
                    with mock.patch(
                        "os.fchmod",
                        side_effect=OSError(errno.EIO, "posix stage fchmod fault"),
                    ):
                        with self.assertRaises(RuntimeError) as cm:
                            toi._write_output_atomic(dst, b"verified-new", root_anchor=self.base)
                    self.assertIsInstance(cm.exception.__cause__, OSError)
                    self.assertIn("posix stage fchmod fault", str(cm.exception.__cause__))
                    self.assertIn(".toi-stage-", str(cm.exception))
                    self.assertIn("외부 디렉터리 보존", str(cm.exception))
                    self.assertEqual(dst.read_bytes(), b"safe-original")
                    leftover_stages = list(dst.parent.glob(".toi-stage-*"))
                    self.assertEqual(len(leftover_stages), 1)
                finally:
                    _rm_quiet(*leftover_stages)
                moved_init = self.base / "moved_init_stage"
                init_swap = {"ext_stage": None, "ext_ino": None}
                real_os_open = os.open
                def _swap_before_stage_open(path, flags, *args, **kwargs):
                    if isinstance(path, str) and path.startswith(".toi-stage-") and init_swap["ext_stage"] is None:
                        stage_path = dst.parent / path
                        stage_path.rename(moved_init)
                        os.mkdir(stage_path, 0o755)
                        os.chmod(stage_path, 0o755)
                        st_ext = os.stat(stage_path, follow_symlinks=False)
                        init_swap["ext_stage"] = stage_path
                        init_swap["ext_ino"] = (st_ext.st_dev, st_ext.st_ino)
                    return real_os_open(path, flags, *args, **kwargs)
                try:
                    with mock.patch("os.open", _swap_before_stage_open):
                        with self.assertRaises(RuntimeError) as cm:
                            toi._write_output_atomic(dst, b"verified-new", root_anchor=self.base)
                    self.assertIsInstance(cm.exception.__cause__, PermissionError)
                    self.assertIn("초기 준비 중 외부에서 교체", str(cm.exception.__cause__))
                    self.assertIn(str(init_swap["ext_stage"]), str(cm.exception))
                    self.assertIn("외부 디렉터리 보존", str(cm.exception))
                    self.assertEqual(dst.read_bytes(), b"safe-original")
                    self.assertTrue(init_swap["ext_stage"].is_dir())
                    st_after = os.stat(init_swap["ext_stage"], follow_symlinks=False)
                    self.assertEqual((st_after.st_dev, st_after.st_ino), init_swap["ext_ino"])
                    self.assertEqual((st_after.st_mode & 0o777), 0o755)
                finally:
                    _rm_quiet(init_swap["ext_stage"], moved_init)
            finally:
                toi.TEST_BEFORE_PUBLISH_HOOK = old
                toi.TEST_BEFORE_STAGE_RMDIR_HOOK = old_stage_rmdir

    def test_duplicate_target_rejected_in_batch_and_http(self):
        hdr_path = self.slot / "CacheData"
        orig_bytes = hdr_path.read_bytes()
        with self.assertRaises(ValueError):
            toi.replace_batch_safely(
                [
                    {"path": hdr_path, "data": orig_bytes},
                    {"path": hdr_path, "data": orig_bytes},
                ],
                force=True,
                root_anchor=self.base,
            )

        srv = toi.create_http_server(save_dir=str(self.base), host="127.0.0.1", port=0)
        host, port = srv.server_address
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        json_hdrs = {"Content-Type": "application/json", "X-Toi-Token": srv.csrf_token}
        try:
            c0 = http.client.HTTPConnection(host, port, timeout=5)
            c0.request("POST", "/api/load-slot", body=json.dumps({"slot": "1_DEMO01"}).encode(), headers=json_hdrs)
            loaded = json.loads(c0.getresponse().read())
            c0.close()
            sid = loaded["session"]
            hdr_entry = next(f for f in loaded["files"] if f["name"] == "CacheData")
            glob_entry = next(f for f in loaded["files"] if f["name"] == "DataGloble.cache")
            _, hdr_obj = toi.decode_cache_bytes(base64.b64decode(hdr_entry["base64"]))
            hdr_a = dict(hdr_obj, worldDay=4001)
            hdr_b = dict(hdr_obj, worldDay=4002)
            b64_a = base64.b64encode(toi.encode_cache_data(hdr_a, mode="cipher-gzip")).decode("ascii")
            b64_b = base64.b64encode(toi.encode_cache_data(hdr_b, mode="cipher-gzip")).decode("ascii")

            # Duplicate CacheData -> 400
            dup1 = {
                "slot": "1_DEMO01",
                "session": sid,
                "files": [
                    {"name": "CacheData", "relativePath": "CacheData", "base64": b64_a},
                    {"name": "CacheData", "relativePath": "CacheData", "base64": b64_b},
                ],
            }
            c1 = http.client.HTTPConnection(host, port, timeout=5)
            c1.request("POST", "/api/save-slot", body=json.dumps(dup1).encode(), headers=json_hdrs)
            self.assertEqual(c1.getresponse().status, 400)
            c1.close()
            self.assertEqual(hdr_path.read_bytes(), orig_bytes)

            # Duplicate DataGloble.cache via alias pair -> 400
            dup2 = {
                "slot": "1_DEMO01",
                "session": sid,
                "files": [
                    {"name": "DataGloble.cache", "relativePath": "DataGloble.cache", "base64": glob_entry["base64"]},
                    {"name": "DataGloble.cache", "relativePath": "parent/DataGloble.cache", "base64": glob_entry["base64"]},
                ],
            }
            c2 = http.client.HTTPConnection(host, port, timeout=5)
            c2.request("POST", "/api/save-slot", body=json.dumps(dup2).encode(), headers=json_hdrs)
            self.assertEqual(c2.getresponse().status, 400)
            c2.close()

            # Clean save after rejected duplicate still works across consecutive saves (200 -> 200)
            ok1 = {
                "slot": "1_DEMO01",
                "session": sid,
                "files": [{"name": "CacheData", "relativePath": "CacheData", "base64": b64_a}],
            }
            c3 = http.client.HTTPConnection(host, port, timeout=5)
            c3.request("POST", "/api/save-slot", body=json.dumps(ok1).encode(), headers=json_hdrs)
            r3 = c3.getresponse()
            res3 = json.loads(r3.read())
            c3.close()
            self.assertEqual(r3.status, 200)

            ok2 = {
                "slot": "1_DEMO01",
                "session": res3["session"],
                "files": [{"name": "CacheData", "relativePath": "CacheData", "base64": b64_b}],
            }
            c4 = http.client.HTTPConnection(host, port, timeout=5)
            c4.request("POST", "/api/save-slot", body=json.dumps(ok2).encode(), headers=json_hdrs)
            r4 = c4.getresponse()
            r4.read()
            c4.close()
            self.assertEqual(r4.status, 200)
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2)

    def test_partial_write_failure_restores_current_file_and_preserves_bak_on_rb_fail(self):
        f0 = self.slot / "midfail0.cache"
        f0.write_bytes(b"orig-mid-0")
        old_mid = toi.TEST_FAIL_MID_WRITE
        old_rb = toi.TEST_FAIL_ROLLBACK
        try:
            # 1. Mid-write / post-publish failure on current file -> automatically restored from .bak
            toi.TEST_FAIL_MID_WRITE = True
            toi.TEST_FAIL_ROLLBACK = False
            with self.assertRaises(OSError):
                toi.replace_batch_safely(
                    [{"path": f0, "data": b"mutated-mid-0", "expected_sha256": _sha(f0)}],
                    force=True,
                    root_anchor=self.base,
                )
            self.assertEqual(f0.read_bytes(), b"orig-mid-0")
            self.assertEqual(list(self.slot.glob("midfail0.cache.backup-*.bak")), [])

            # 2. Mid-write failure + rollback failure -> original .bak preserved undeleted
            toi.TEST_FAIL_MID_WRITE = True
            toi.TEST_FAIL_ROLLBACK = True
            with self.assertRaises(RuntimeError):
                toi.replace_batch_safely(
                    [{"path": f0, "data": b"mutated-mid-0", "expected_sha256": _sha(f0)}],
                    force=True,
                    root_anchor=self.base,
                )
            baks = list(self.slot.glob("midfail0.cache.backup-*.bak"))
            self.assertEqual(len(baks), 1)
            self.assertEqual(baks[0].read_bytes(), b"orig-mid-0")
        finally:
            toi.TEST_FAIL_MID_WRITE = old_mid
            toi.TEST_FAIL_ROLLBACK = old_rb

    def test_new_target_external_create_not_overwritten_and_rolls_back_prior(self):
        existing_f0 = self.slot / "newrace0.cache"
        new_f1 = self.slot / "newrace1.cache"
        existing_f0.write_bytes(b"orig-race-0")

        def create_external_new(tmp_path: Path) -> None:
            if tmp_path.name.startswith("newrace1.cache.tmp-") and not new_f1.exists():
                new_f1.write_bytes(b"external-created-bytes")

        old_hook = toi.TEST_BEFORE_PUBLISH_HOOK
        toi.TEST_BEFORE_PUBLISH_HOOK = create_external_new
        try:
            with self.assertRaises(FileExistsError):
                toi.replace_batch_safely(
                    [
                        {"path": existing_f0, "data": b"mutated-race-0", "expected_sha256": _sha(existing_f0)},
                        {"path": new_f1, "data": b"our-new-bytes"},
                    ],
                    force=True,
                    root_anchor=self.base,
                )
            self.assertEqual(existing_f0.read_bytes(), b"orig-race-0")
            self.assertEqual(new_f1.read_bytes(), b"external-created-bytes")
            self.assertEqual(list(self.slot.glob("newrace0.cache.backup-*.bak")), [])
        finally:
            toi.TEST_BEFORE_PUBLISH_HOOK = old_hook

    def test_existing_rollback_preserves_externally_modified_committed_file(self):
        f0 = self.slot / "rbown0.cache"
        f1 = self.slot / "rbown1.cache"
        f0.write_bytes(b"orig-a")
        f1.write_bytes(b"orig-b")
        h0, h1 = _sha(f0), _sha(f1)

        old_hook = toi.TEST_BEFORE_COMMIT_HOOK
        old_fail_index = toi.TEST_FAIL_AT_COMMIT_INDEX

        if os.name == "nt":
            blocked = []

            def hook(idx, *args, **kwargs):
                if idx == 1:
                    proc = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import sys; open(sys.argv[1], 'r+b').write(b'ext-a')",
                            str(f0),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    blocked.append(proc.returncode != 0)

            try:
                toi.TEST_BEFORE_COMMIT_HOOK = hook
                toi.TEST_FAIL_AT_COMMIT_INDEX = 1
                pair_items = [{"path": f0, "data": b"new-a", "expected_sha256": h0}, {"path": f1, "data": b"new-b", "expected_sha256": h1}]
                with self.assertRaises(OSError):
                    toi.replace_batch_safely(pair_items, force=True, root_anchor=self.base)
                self.assertEqual(blocked, [True])
                self.assertEqual(f0.read_bytes(), b"orig-a")
                self.assertEqual(f1.read_bytes(), b"orig-b")
                self.assertEqual(list(self.slot.glob("rbown*.backup-*.bak")), [])
            finally:
                toi.TEST_BEFORE_COMMIT_HOOK = old_hook
                toi.TEST_FAIL_AT_COMMIT_INDEX = old_fail_index
            return

        def hook_a(idx, *args, **kwargs):
            if idx == 1:
                f0.write_bytes(b"ext-a-inplace")
                f1.write_bytes(b"ext-b")

        try:
            toi.TEST_BEFORE_COMMIT_HOOK = hook_a
            with self.assertRaises(RuntimeError) as cm:
                toi.replace_batch_safely(
                    [
                        {"path": f0, "data": b"new-a", "expected_sha256": h0},
                        {"path": f1, "data": b"new-b", "expected_sha256": h1},
                    ],
                    force=True,
                    root_anchor=self.base,
                )
            self.assertIn("원본 .bak 보존됨", str(cm.exception))
            self.assertIsInstance(cm.exception.__cause__, RuntimeError)
            self.assertEqual(f0.read_bytes(), b"ext-a-inplace")
            self.assertEqual(f1.read_bytes(), b"ext-b")
            backups0 = list(self.slot.glob("rbown0.cache.backup-*.bak"))
            self.assertEqual(len(backups0), 1)
            self.assertEqual(backups0[0].read_bytes(), b"orig-a")
            self.assertEqual(list(self.slot.glob("rbown1.cache.backup-*.bak")), [])
        finally:
            toi.TEST_BEFORE_COMMIT_HOOK = old_hook
            for backup in self.slot.glob("rbown*.backup-*.bak"):
                try:
                    backup.unlink()
                except FileNotFoundError:
                    pass

        f_pre = self.slot / "rbown_pre.cache"
        g0 = self.slot / "rbown2_a.cache"
        g1 = self.slot / "rbown2_b.cache"
        f_pre.write_bytes(b"orig-pre")
        g0.write_bytes(b"orig-a-2")
        g1.write_bytes(b"orig-b-2")
        hp = _sha(f_pre)
        hg0 = _sha(g0)
        hg1 = _sha(g1)

        def hook_b(idx, *args, **kwargs):
            if idx == 2:
                ext_tmp = self.slot / "rbown2_a.exttmp"
                ext_tmp.write_bytes(b"ext-a-replaced")
                os.replace(str(ext_tmp), str(g0))
                g1.write_bytes(b"ext-b-2")

        try:
            toi.TEST_BEFORE_COMMIT_HOOK = hook_b
            with self.assertRaises(RuntimeError) as cm:
                toi.replace_batch_safely(
                    [
                        {"path": f_pre, "data": b"new-pre", "expected_sha256": hp},
                        {"path": g0, "data": b"new-a-2", "expected_sha256": hg0},
                        {"path": g1, "data": b"new-b-2", "expected_sha256": hg1},
                    ],
                    force=True,
                    root_anchor=self.base,
                )
            self.assertIn("원본 .bak 보존됨", str(cm.exception))
            self.assertEqual(f_pre.read_bytes(), b"orig-pre")
            self.assertEqual(list(self.slot.glob("rbown_pre.cache.backup-*.bak")), [])
            self.assertEqual(g0.read_bytes(), b"ext-a-replaced")
            backups_g0 = list(self.slot.glob("rbown2_a.cache.backup-*.bak"))
            self.assertEqual(len(backups_g0), 1)
            self.assertEqual(backups_g0[0].read_bytes(), b"orig-a-2")
            self.assertEqual(g1.read_bytes(), b"ext-b-2")
            self.assertEqual(list(self.slot.glob("rbown2_b.cache.backup-*.bak")), [])
        finally:
            toi.TEST_BEFORE_COMMIT_HOOK = old_hook
            for backup in self.slot.glob("rbown*.backup-*.bak"):
                try:
                    backup.unlink()
                except FileNotFoundError:
                    pass

    def test_publish_rechecks_staged_bytes_and_rolls_back_post_link_unlink_failure(self):
        import errno
        import os
        import subprocess
        import sys
        from unittest import mock

        s0 = self.slot / "stagemut0.cache"
        s1 = self.slot / "stagemut1.cache"
        s0.write_bytes(b"orig-s0")
        s1.write_bytes(b"orig-s1")
        hs0, hs1 = _sha(s0), _sha(s1)
        s_new = self.slot / "stagemut_new.cache"

        original_hook = getattr(toi, "TEST_BEFORE_PUBLISH_HOOK", None)
        try:
            if os.name == "nt":
                def hook(tmp_path):
                    if "stagemut1.cache.tmp-" in tmp_path.name:
                        proc = subprocess.run(
                            [sys.executable, "-c", "import sys; open(sys.argv[1], 'r+b')", str(tmp_path)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self.assertNotEqual(proc.returncode, 0)

                toi.TEST_BEFORE_PUBLISH_HOOK = hook
                toi.replace_batch_safely(
                    [
                        {"path": s0, "data": b"new-s0!!", "expected_sha256": hs0},
                        {"path": s1, "data": b"new-s1!!", "expected_sha256": hs1},
                    ],
                    force=True,
                    root_anchor=self.base,
                )
            else:
                def hook(tmp_path):
                    if tmp_path.name.startswith("stagemut1.cache.tmp-"):
                        with open(tmp_path, "r+b") as fh:
                            fh.seek(0)
                            fh.write(b"BAD-DATA")
                    elif tmp_path.name.startswith("stagemut_new.cache.tmp-"):
                        tmp_path.write_bytes(b"TAMPERED_NEW")

                toi.TEST_BEFORE_PUBLISH_HOOK = hook

                with self.assertRaises(RuntimeError) as cm:
                    toi.replace_batch_safely(
                        [
                            {"path": s0, "data": b"new-s0!!", "expected_sha256": hs0},
                            {"path": s1, "data": b"new-s1!!", "expected_sha256": hs1},
                        ],
                        force=True,
                        root_anchor=self.base,
                    )

                self.assertIsInstance(cm.exception.__cause__, PermissionError)
                self.assertIn("외부 파일 보존", str(cm.exception))
                self.assertIn("stagemut1.cache.tmp-", str(cm.exception))

                self.assertEqual(s0.read_bytes(), b"orig-s0")
                self.assertEqual(s1.read_bytes(), b"orig-s1")
                self.assertEqual(list(self.slot.glob("stagemut*.backup-*.bak")), [])

                with self.assertRaises(RuntimeError) as cm:
                    toi.replace_batch_safely(
                        [
                            {"path": s0, "data": b"new-s0-2", "expected_sha256": hs0},
                            {"path": s_new, "data": b"clean-new", "must_not_exist": True},
                        ],
                        force=True,
                        root_anchor=self.base,
                    )

                self.assertIsInstance(cm.exception.__cause__, PermissionError)
                self.assertIn("외부 파일 보존", str(cm.exception))
                self.assertIn("stagemut_new.cache.tmp-", str(cm.exception))

                self.assertEqual(s0.read_bytes(), b"orig-s0")
                self.assertFalse(s_new.exists())
                self.assertEqual(list(self.slot.glob("stagemut*.backup-*.bak")), [])
        finally:
            toi.TEST_BEFORE_PUBLISH_HOOK = original_hook
            for stage_dir in self.slot.glob(".toi-stage-*"):
                for child in list(stage_dir.iterdir()):
                    try:
                        child.unlink()
                    except OSError:
                        pass
                try:
                    stage_dir.rmdir()
                except OSError:
                    pass

        if os.name == "nt":
            return

        la = self.slot / "linkrb_a.cache"
        lb = self.slot / "linkrb_b.cache"
        la.write_bytes(b"orig-la")
        hla = _sha(la)
        if lb.exists():
            lb.unlink()

        real_unlink = os.unlink

        def stage_unlink_failure(name, *args, **kwargs):
            if kwargs.get("dir_fd") is not None and isinstance(name, str) and name.startswith("linkrb_b.cache.tmp-"):
                raise OSError(errno.EIO, "injected stage unlink error")
            return real_unlink(name, *args, **kwargs)

        with mock.patch("os.unlink", side_effect=stage_unlink_failure):
            with self.assertRaises(RuntimeError) as cm_link:
                toi.replace_batch_safely(
                    [
                        {"path": la, "data": b"new-la", "expected_sha256": hla},
                        {"path": lb, "data": b"new-lb", "must_not_exist": True},
                    ],
                    force=True,
                    root_anchor=self.base,
                )

        self.assertIsInstance(cm_link.exception.__cause__, OSError)
        self.assertIn("linkrb_b.cache.tmp-", str(cm_link.exception))
        self.assertIn("injected stage unlink error", str(cm_link.exception))

        self.assertFalse(lb.exists())
        self.assertEqual(la.read_bytes(), b"orig-la")
        self.assertEqual(list(self.slot.glob("linkrb_*.backup-*.bak")), [])

        for stage_dir in self.slot.glob(".toi-stage-*"):
            for child in list(stage_dir.iterdir()):
                real_unlink(child)
            os.rmdir(stage_dir)

        lc = self.base / "standalone_linkfail.json"
        calls = {"count": 0}

        def one_shot_unlink(name, *args, **kwargs):
            if isinstance(name, str) and name.startswith("standalone_linkfail.json.tmp-") and calls["count"] == 0:
                calls["count"] += 1
                raise OSError(errno.EIO, "one-shot stage unlink")
            return real_unlink(name, *args, **kwargs)

        with mock.patch("os.unlink", side_effect=one_shot_unlink):
            with self.assertRaises(OSError):
                toi._write_output_atomic(lc, b"{}", root_anchor=self.base, replace_existing=False)

        self.assertFalse(lc.exists())

    def test_atomic_output_and_untouched_copy_surface_rollback_errors(self):
        import errno
        import subprocess
        import sys
        from unittest import mock

        real_unlink = os.unlink
        real_rmdir = os.rmdir
        real_win_close_handle = toi._win_close_handle
        real_write_atomic = toi._write_output_atomic
        real_rb = toi._rollback_published_new_leaf
        real_pub = toi.PinnedDirectory.publish_atomic_leaf

        dst_ok = self.base / "standalone_ok.json"
        dst1 = self.base / "standalone_del_err.json"
        dst2a = self.base / "standalone_ext_active.json"
        dst2 = self.base / "standalone_ext_swap.json"
        out3 = self.base / "slot_copy_del_err"
        out4 = self.base / "slot_copy_ext_swap"

        def _cleanup_paths(*paths):
            for path in paths:
                p = Path(path)
                if p.is_dir():
                    for child in sorted(p.rglob("*"), reverse=True):
                        try:
                            real_unlink(child) if child.is_file() or child.is_symlink() else real_rmdir(child)
                        except OSError:
                            pass
                    try:
                        real_rmdir(p)
                    except OSError:
                        pass
                else:
                    try:
                        real_unlink(p)
                    except OSError:
                        pass

        def _cleanup_stages():
            for pattern in (
                ".toi-stage-*",
                "standalone_del_err.json.tmp-*",
                "standalone_ext_active.json.tmp-*",
                "standalone_ext_swap.json.tmp-*",
                "standalone_ok.json.tmp-*",
                "slot_copy_del_err*",
                "slot_copy_ext_swap*",
                "batch_bak_*.cache*",
                "prepub_*",
            ):
                for path in self.base.glob(pattern):
                    _cleanup_paths(path)

        def _probe_child_write_blocked(target_path):
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; open(sys.argv[1], 'wb').write(b'X')",
                    str(target_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertNotEqual(proc.returncode, 0)

        def _assert_chained_rb_error(cm, expected_path, expected_substr, cause_cls):
            self.assertIn(str(expected_path), str(cm.exception))
            self.assertIn(expected_substr, str(cm.exception))
            self.assertIsInstance(cm.exception.__cause__, cause_cls)

        original_after_untouched = getattr(toi, "TEST_AFTER_UNTOUCHED_COPY_HOOK", None)
        original_after_bak = getattr(toi, "TEST_AFTER_BACKUP_CREATED_HOOK", None)
        original_fail_mid = getattr(toi, "TEST_FAIL_MID_WRITE", False)

        try:
            _cleanup_paths(dst_ok, dst1, dst2a, dst2, out3, out4)
            _cleanup_stages()

            toi._write_output_atomic(dst_ok, b'{"ok":1}', root_anchor=self.base, replace_existing=False)
            self.assertEqual(dst_ok.read_bytes(), b'{"ok":1}')
            dst_ok.write_bytes(b'{"ok":2}')
            dst_ok.unlink()

            # 1. Standalone _write_output_atomic rollback delete failure (Windows & POSIX).
            try:
                if os.name == "nt":
                    toi.TEST_FAIL_MID_WRITE = True

                    def deny_nt_delete(handle, delete_on_close=False):
                        if delete_on_close:
                            real_win_close_handle(handle, delete_on_close=False)
                            raise OSError("nt handle delete denied")
                        return real_win_close_handle(handle, delete_on_close=delete_on_close)

                    with mock.patch.object(toi, "_win_close_handle", side_effect=deny_nt_delete):
                        with self.assertRaises(RuntimeError) as cm:
                            toi._write_output_atomic(dst1, b"{}", root_anchor=self.base, replace_existing=False)
                    _assert_chained_rb_error(cm, dst1, "nt handle delete denied", OSError)
                else:
                    def deny_posix_unlink(path, *args, **kwargs):
                        name = os.path.basename(os.fspath(path))
                        if name.startswith("standalone_del_err.json.tmp-") or name == "standalone_del_err.json":
                            raise OSError(errno.EIO, "posix unlink denied")
                        return real_unlink(path, *args, **kwargs)

                    with mock.patch("os.unlink", side_effect=deny_posix_unlink):
                        with self.assertRaises(RuntimeError) as cm:
                            toi._write_output_atomic(dst1, b"{}", root_anchor=self.base, replace_existing=False)
                    _assert_chained_rb_error(cm, dst1, "posix unlink denied", OSError)
            finally:
                toi.TEST_FAIL_MID_WRITE = original_fail_mid
                _cleanup_paths(dst1)
                _cleanup_stages()

            # 2. Standalone _write_output_atomic external replacement protection & preservation (Windows & POSIX).
            try:
                if os.name == "nt":
                    toi.TEST_FAIL_MID_WRITE = True

                    def rb_probe_exclusive(pin, dst_path, state):
                        self.assertIsNotNone(state.get("win_handle"))
                        _probe_child_write_blocked(dst2a)
                        return real_rb(pin, dst_path, state)

                    with mock.patch.object(toi, "_rollback_published_new_leaf", side_effect=rb_probe_exclusive):
                        with self.assertRaises(OSError):
                            toi._write_output_atomic(dst2a, b"{}", root_anchor=self.base, replace_existing=False)
                    self.assertFalse(dst2a.exists())

                    toi.TEST_FAIL_MID_WRITE = False

                    def publish_then_swap(pin_self, tmp_name, dst_name, data, **kw):
                        result = real_pub(pin_self, tmp_name, dst_name, data, **kw)
                        if Path(os.fspath(dst_name)).name == dst2.name:
                            out_state = kw["out_state"]
                            wh = out_state.pop("win_handle", None)
                            toi._win_close_handle(wh, delete_on_close=False)
                            dst2.write_bytes(b'{"ext":1}')
                            raise OSError("post-publish fault after handle release")
                        return result

                    with mock.patch.object(toi.PinnedDirectory, "publish_atomic_leaf", autospec=True, side_effect=publish_then_swap):
                        with self.assertRaises(RuntimeError) as cm:
                            toi._write_output_atomic(dst2, b"{}", root_anchor=self.base, replace_existing=False)
                    _assert_chained_rb_error(cm, dst2, "외부 파일 보존", OSError)
                    self.assertEqual(dst2.read_bytes(), b'{"ext":1}')
                else:
                    swapped = {"done": False}

                    def swap_then_fail_unlink(path, *args, **kwargs):
                        name = os.path.basename(os.fspath(path))
                        if not swapped["done"] and name.startswith("standalone_ext_swap.json.tmp-"):
                            swapped["done"] = True
                            try:
                                real_unlink(dst2)
                            except OSError:
                                pass
                            dst2.write_bytes(b'{"ext":1}')
                            raise OSError(errno.EIO, "stage unlink after ext swap")
                        return real_unlink(path, *args, **kwargs)

                    with mock.patch("os.unlink", side_effect=swap_then_fail_unlink):
                        with self.assertRaises(RuntimeError) as cm:
                            toi._write_output_atomic(dst2, b"{}", root_anchor=self.base, replace_existing=False)
                    _assert_chained_rb_error(cm, dst2, "외부 파일 보존", OSError)
                    self.assertEqual(dst2.read_bytes(), b'{"ext":1}')
            finally:
                toi.TEST_FAIL_MID_WRITE = original_fail_mid
                _cleanup_paths(dst2a, dst2)
                _cleanup_stages()

            # 3. SlotSession.save untouched-copy rollback delete failure (Windows & POSIX).
            try:
                sess = toi.SlotSession.load(self.slot)
                sess.set_identity(surname="강")

                def after_copy_del_hook(root_dir):
                    (Path(root_dir) / "CacheData").write_bytes(b"CONFLICT_HDR")

                toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = after_copy_del_hook

                if os.name == "nt":
                    def deny_copy_delete(handle, delete_on_close=False):
                        if delete_on_close:
                            real_win_close_handle(handle, delete_on_close=False)
                            raise OSError("win handle delete failed")
                        return real_win_close_handle(handle, delete_on_close=delete_on_close)

                    with mock.patch.object(toi, "_win_close_handle", side_effect=deny_copy_delete):
                        with self.assertRaises(RuntimeError) as cm:
                            sess.save(output_dir=out3, force=True)
                else:
                    def deny_copy_unlink(path, *args, **kwargs):
                        name = os.path.basename(os.fspath(path))
                        if "CacheFixVer" in name:
                            raise OSError(errno.EACCES, "copy unlink failed")
                        return real_unlink(path, *args, **kwargs)

                    with mock.patch("os.unlink", side_effect=deny_copy_unlink):
                        with self.assertRaises(RuntimeError) as cm:
                            sess.save(output_dir=out3, force=True)

                _assert_chained_rb_error(
                    cm,
                    out3 / "CacheFixVer",
                    "win handle delete failed" if os.name == "nt" else "copy unlink failed",
                    (FileExistsError, RuntimeError, OSError),
                )
            finally:
                toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = original_after_untouched
                _cleanup_paths(out3)
                _cleanup_stages()

            # 4. SlotSession.save untouched-copy external replacement protection & preservation (Windows & POSIX).
            try:
                sess2 = toi.SlotSession.load(self.slot)
                sess2.set_identity(surname="조")

                if os.name == "nt":
                    tracked_copies = []

                    def track_write_atomic(dst, data, *args, **kwargs):
                        tracked_copies.append((Path(os.fspath(dst)), kwargs.get("out_state")))
                        return real_write_atomic(dst, data, *args, **kwargs)

                    def after_copy_ext_hook_nt(root_dir):
                        root_dir = Path(root_dir)
                        _probe_child_write_blocked(root_dir / "CacheFixVer")
                        target_state = None
                        for tracked_path, state in tracked_copies:
                            if tracked_path.name == "CacheFixVer":
                                target_state = state
                                break
                        self.assertIsNotNone(target_state)
                        wh = target_state.pop("win_handle", None)
                        toi._win_close_handle(wh, delete_on_close=False)
                        (root_dir / "CacheFixVer").write_bytes(b"EXT_FIXVER")
                        (root_dir / "CacheData").write_bytes(b"CONFLICT_HDR_2")

                    toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = after_copy_ext_hook_nt
                    with mock.patch.object(toi, "_write_output_atomic", side_effect=track_write_atomic):
                        with self.assertRaises(RuntimeError) as cm:
                            sess2.save(output_dir=out4, force=True)
                else:
                    def after_copy_ext_hook_posix(root_dir):
                        root_dir = Path(root_dir)
                        fixver = root_dir / "CacheFixVer"
                        try:
                            real_unlink(fixver)
                        except OSError:
                            pass
                        fixver.write_bytes(b"EXT_FIXVER")
                        (root_dir / "CacheData").write_bytes(b"CONFLICT_HDR_2")

                    toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = after_copy_ext_hook_posix
                    with self.assertRaises(RuntimeError) as cm:
                        sess2.save(output_dir=out4, force=True)

                _assert_chained_rb_error(cm, out4 / "CacheFixVer", "외부 파일 보존", FileExistsError)
                self.assertEqual((out4 / "CacheFixVer").read_bytes(), b"EXT_FIXVER")
            finally:
                toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = original_after_untouched
                _cleanup_paths(out4)
                _cleanup_stages()

            # 5. replace_batch_safely Phase-1 .bak exclusive handle & external replacement preservation (Windows & POSIX).
            bak_a = self.base / "batch_bak_a.cache"
            bak_b = self.base / "batch_bak_b.cache"
            swapped_bak = {"path": None}
            try:
                bak_a.write_bytes(b"ORIG_A")
                bak_b.write_bytes(b"ORIG_B")
                batch_items = [
                    {"path": bak_a, "data": b"NEW_A", "expected_sha256": toi._sha256_bytes(b"ORIG_A")},
                    {"path": bak_b, "data": b"NEW_B", "expected_sha256": "0" * 64},
                ]
                if os.name == "nt":
                    def _probe_bak_hook(idx, bak_path, bak_state):
                        self.assertIsNotNone(bak_state.get("win_handle"))
                        _probe_child_write_blocked(bak_path)

                    toi.TEST_AFTER_BACKUP_CREATED_HOOK = _probe_bak_hook
                    with self.assertRaises(RuntimeError):
                        toi.replace_batch_safely(batch_items, force=True, root_anchor=self.base)
                    self.assertEqual(list(self.base.glob("batch_bak_a.cache.backup-*.bak")), [])

                def _swap_bak_hook(idx, bak_path, bak_state):
                    swapped_bak["path"] = Path(bak_path)
                    if os.name == "nt":
                        wh = bak_state.pop("win_handle", None)
                        toi._win_close_handle(wh, delete_on_close=False)
                    else:
                        real_unlink(bak_path)
                    Path(bak_path).write_bytes(b"EXT_BAK")

                toi.TEST_AFTER_BACKUP_CREATED_HOOK = _swap_bak_hook
                with self.assertRaises(RuntimeError) as cm:
                    toi.replace_batch_safely(batch_items, force=True, root_anchor=self.base)
                self.assertIsNotNone(swapped_bak["path"])
                _assert_chained_rb_error(cm, swapped_bak["path"], "외부 파일 보존", RuntimeError)
                self.assertEqual(swapped_bak["path"].read_bytes(), b"EXT_BAK")
            finally:
                toi.TEST_AFTER_BACKUP_CREATED_HOOK = original_after_bak
                if swapped_bak["path"] is not None:
                    _cleanup_paths(swapped_bak["path"])
                _cleanup_paths(bak_a, bak_b)
                _cleanup_stages()

            # ------------------------------------------------------------------
            # Case 6: pre-publish/prepare write failure combined with delete
            # failure. The cleanup error must be surfaced (never swallowed) and
            # chained onto the original write failure as the root __cause__.
            # ------------------------------------------------------------------
            real_win_close_handle = toi._win_close_handle
            real_unlink = os.unlink

            def _raise_win_write(self, h, raw, label):
                raise OSError("prepub win write fault")

            if os.name == "nt":
                def _win_tmp_delete_fault(handle, delete_on_close=False):
                    if delete_on_close:
                        try:
                            real_win_close_handle(handle, delete_on_close=False)
                        except OSError:
                            pass
                        raise OSError("prepub win tmp delete fault")
                    return real_win_close_handle(handle, delete_on_close=False)

                def _win_bak_delete_fault(handle, delete_on_close=False):
                    if delete_on_close:
                        try:
                            real_win_close_handle(handle, delete_on_close=False)
                        except OSError:
                            pass
                        raise OSError("prepub win bak delete fault")
                    return real_win_close_handle(handle, delete_on_close=False)

                prepub_dst = self.base / "prepub_pub.json"
                with mock.patch.object(toi.PinnedDirectory, "_win_write_and_verify_handle", _raise_win_write), \
                        mock.patch.object(toi, "_win_close_handle", _win_tmp_delete_fault):
                    with self.assertRaises(RuntimeError) as cm:
                        toi._write_output_atomic(prepub_dst, b"{x:1}", root_anchor=self.base, replace_existing=False)
                self.assertIsInstance(cm.exception.__cause__, OSError)
                self.assertIn(".tmp-", str(cm.exception))
                self.assertIn("prepub win tmp delete fault", str(cm.exception))
                self.assertTrue(list(self.base.glob("prepub_pub.json.tmp-*")))
                _cleanup_paths(prepub_dst)
                _cleanup_stages()

                prepub_bak = self.base / "prepub_excl.bak"
                with toi.PinnedDirectory(self.base, root_anchor=self.base) as pin:
                    try:
                        with mock.patch.object(toi.PinnedDirectory, "_win_write_and_verify_handle", _raise_win_write), \
                                mock.patch.object(toi, "_win_close_handle", _win_bak_delete_fault):
                            with self.assertRaises(RuntimeError) as cm:
                                pin.write_exclusive_leaf("prepub_excl.bak", b"BAK_BYTES", keep_win_handle=True)
                        self.assertIsInstance(cm.exception.__cause__, OSError)
                        self.assertIn(str(prepub_bak), str(cm.exception))
                        self.assertIn("prepub win bak delete fault", str(cm.exception))
                    finally:
                        _cleanup_paths(prepub_bak)
            else:
                def _raise_posix_write(self, fd, raw, label, state=None):
                    raise OSError(errno.EIO, "prepub posix write fault")

                def _posix_tmp_unlink_fault(path, *args, **kwargs):
                    if ".tmp-" in str(path):
                        raise OSError(errno.EACCES, "prepub posix tmp unlink fault")
                    return real_unlink(path, *args, **kwargs)

                def _posix_bak_unlink_fault(path, *args, **kwargs):
                    if "prepub_excl" in str(path) and ".tmp-" not in str(path):
                        raise OSError(errno.EACCES, "prepub posix bak unlink fault")
                    return real_unlink(path, *args, **kwargs)

                prepub_dst = self.base / "prepub_pub.json"
                with mock.patch.object(toi.PinnedDirectory, "_posix_write_and_verify_fd", _raise_posix_write), \
                        mock.patch("os.unlink", _posix_tmp_unlink_fault):
                    with self.assertRaises(RuntimeError) as cm:
                        toi._write_output_atomic(prepub_dst, b"{x:1}", root_anchor=self.base, replace_existing=False)
                self.assertIsInstance(cm.exception.__cause__, OSError)
                self.assertIn(".toi-stage-", str(cm.exception))
                self.assertIn(".tmp-", str(cm.exception))
                self.assertIn("prepub posix tmp unlink fault", str(cm.exception))
                _cleanup_paths(prepub_dst)

                prepub_bak = self.base / "prepub_excl.bak"
                with toi.PinnedDirectory(self.base, root_anchor=self.base) as pin:
                    try:
                        with mock.patch.object(toi.PinnedDirectory, "_posix_write_and_verify_fd", _raise_posix_write), \
                                mock.patch("os.unlink", _posix_bak_unlink_fault):
                            with self.assertRaises(RuntimeError) as cm:
                                pin.write_exclusive_leaf("prepub_excl.bak", b"BAK_BYTES", keep_win_handle=False)
                        self.assertIsInstance(cm.exception.__cause__, OSError)
                        self.assertIn(str(prepub_bak), str(cm.exception))
                        self.assertIn("prepub posix bak unlink fault", str(cm.exception))
                    finally:
                        _cleanup_paths(prepub_bak)

                # POSIX external swap during write_exclusive_leaf must be preserved.
                prepub_swap = self.base / "prepub_excl_swap.bak"
                if prepub_swap.exists():
                    try:
                        prepub_swap.unlink()
                    except OSError:
                        pass
                with toi.PinnedDirectory(self.base, root_anchor=self.base) as pin_swap:
                    fsync_calls = {"n": 0}
                    real_fsync = os.fsync

                    def _swap_then_fsync(fd):
                        fsync_calls["n"] += 1
                        if fsync_calls["n"] == 1:
                            try:
                                real_unlink(prepub_swap)
                            except OSError:
                                pass
                            prepub_swap.write_bytes(b"EXT_EXCL")
                        return real_fsync(fd)

                    try:
                        with mock.patch("os.fsync", _swap_then_fsync):
                            with self.assertRaises(RuntimeError) as cm:
                                pin_swap.write_exclusive_leaf("prepub_excl_swap.bak", b"BAK_BYTES", keep_win_handle=False)
                        self.assertIsInstance(cm.exception.__cause__, PermissionError)
                        self.assertIn(str(prepub_swap), str(cm.exception))
                        self.assertIn("외부 파일 보존", str(cm.exception))
                        self.assertEqual(prepub_swap.read_bytes(), b"EXT_EXCL")
                    finally:
                        _cleanup_paths(prepub_swap)

                def _run_partial_write_case(expected_exc, run_op, find_target_fn, tamper_bytes):
                    real_os_write = os.write
                    state = {"step": 0, "target": None, "orig_ino": None, "exc": None}

                    def patched_write(wfd, data):
                        target = find_target_fn()
                        if target is None or not os.path.exists(target):
                            return real_os_write(wfd, data)

                        tst = os.stat(target)
                        wst = os.fstat(wfd)
                        if (wst.st_dev, wst.st_ino) != (tst.st_dev, tst.st_ino):
                            return real_os_write(wfd, data)

                        if state["step"] == 0:
                            state["step"] = 1
                            state["target"] = target
                            state["orig_ino"] = (tst.st_dev, tst.st_ino)
                            return real_os_write(wfd, bytes(data)[:4])

                        if state["step"] == 1:
                            state["step"] = 2
                            if tamper_bytes is not None:
                                tfd = os.open(target, os.O_WRONLY | os.O_TRUNC)
                                try:
                                    real_os_write(tfd, tamper_bytes)
                                finally:
                                    os.close(tfd)
                            raise OSError(errno.EIO, "posix second write fault")

                        return real_os_write(wfd, data)

                    with mock.patch("os.write", patched_write):
                        with self.assertRaises(expected_exc) as cm:
                            run_op()
                    state["exc"] = cm.exception
                    return state

                with toi.PinnedDirectory(self.base, root_anchor=self.base) as pin_part:
                    part_bak = self.base / "prepub_part_tamper.bak"
                    st = _run_partial_write_case(
                        RuntimeError,
                        lambda: pin_part.write_exclusive_leaf(
                            "prepub_part_tamper.bak",
                            b"ABCDEFGH",
                            keep_win_handle=False,
                        ),
                        lambda: part_bak if part_bak.exists() else None,
                        b"EXT_PARTIAL_BAK",
                    )
                    self.assertIsInstance(st["exc"].__cause__, OSError)
                    self.assertIn("posix second write fault", str(st["exc"].__cause__))
                    self.assertIn("외부 파일 보존", str(st["exc"]))
                    self.assertEqual(
                        (os.stat(part_bak).st_dev, os.stat(part_bak).st_ino),
                        st["orig_ino"],
                    )
                    self.assertEqual(part_bak.read_bytes(), b"EXT_PARTIAL_BAK")
                    _cleanup_paths(part_bak)

                    part_dst = self.base / "prepub_part_dst.json"
                    part_dst.write_bytes(b"ORIG_DST")
                    st = _run_partial_write_case(
                        RuntimeError,
                        lambda: toi._write_output_atomic(
                            part_dst,
                            b"VERIFIED_PAYLOAD",
                            root_anchor=self.base,
                        ),
                        lambda: next(
                            self.base.glob(".toi-stage-*/prepub_part_dst.json.tmp-*"),
                            None,
                        ),
                        b"EXT_PARTIAL_TMP",
                    )
                    self.assertIsInstance(st["exc"].__cause__, OSError)
                    self.assertIn("외부 파일 보존", str(st["exc"]))
                    self.assertEqual(part_dst.read_bytes(), b"ORIG_DST")
                    self.assertEqual(
                        (os.stat(st["target"]).st_dev, os.stat(st["target"]).st_ino),
                        st["orig_ino"],
                    )
                    self.assertEqual(st["target"].read_bytes(), b"EXT_PARTIAL_TMP")
                    _cleanup_paths(st["target"], part_dst)
                    _cleanup_stages()

                    part_clean_bak = self.base / "prepub_part_clean.bak"
                    st_c1 = _run_partial_write_case(
                        OSError,
                        lambda: pin_part.write_exclusive_leaf(
                            "prepub_part_clean.bak",
                            b"ABCDEFGH",
                            keep_win_handle=False,
                        ),
                        lambda: part_clean_bak if part_clean_bak.exists() else None,
                        None,
                    )
                    part_clean_dst = self.base / "prepub_part_clean.json"
                    st_c2 = _run_partial_write_case(
                        OSError,
                        lambda: toi._write_output_atomic(
                            part_clean_dst,
                            b"VERIFIED_PAYLOAD",
                            root_anchor=self.base,
                            replace_existing=False,
                        ),
                        lambda: next(
                            self.base.glob(".toi-stage-*/prepub_part_clean.json.tmp-*"),
                            None,
                        ),
                        None,
                    )
                    self.assertIn("posix second write fault", str(st_c1["exc"]))
                    self.assertIn("posix second write fault", str(st_c2["exc"]))
                    self.assertFalse(part_clean_bak.exists())
                    self.assertFalse(part_clean_dst.exists())
                    self.assertEqual(list(self.base.glob(".toi-stage-*")), [])

                _cleanup_stages()
        finally:
            toi.TEST_FAIL_MID_WRITE = original_fail_mid
            toi.TEST_AFTER_UNTOUCHED_COPY_HOOK = original_after_untouched
            toi.TEST_AFTER_BACKUP_CREATED_HOOK = original_after_bak
            _cleanup_paths(dst_ok, dst1, dst2a, dst2, out3, out4)
            _cleanup_stages()



    def test_optional_real_save_sweep(self):
        root = os.environ.get("TOI_REAL_SAVES_DIR")
        if not root or not Path(root).exists():
            return
        checked = 0
        for slot in sorted(Path(root).iterdir()):
            if slot.is_dir() and slot.name[:1].isdigit() and "_" in slot.name:
                sess = toi.SlotSession.load(slot)
                rep = sess.validate()
                self.assertTrue(rep["ok"])
                self.assertEqual(rep["errors"], [])
                checked += 1
        self.assertGreaterEqual(checked, 1)


if __name__ == "__main__":
    unittest.main()
