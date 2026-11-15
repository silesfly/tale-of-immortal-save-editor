#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tale of Immortal (귀곡팔황 / 鬼谷八荒) Save Editor v1.0 — CLI & Local Loopback Server.

Pure Python 3 standard library only. Zero external packages, zero external network access.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import errno
import gzip
import hashlib
import http.server
import json
import os
import re
import secrets
import shutil
import socketserver
import stat
import subprocess
import sys
import threading
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent

HEADER_BYTES = b"1b8bg-/%ePe]P[-/921CG"
KEY_BYTES = b"5:.A%KL;,.?<aH._=-/DF4s"

FILE_NAMES: Dict[str, str] = {
    "header": "CacheData",
    "fixVer": "CacheFixVer",
    "world": "eMZk7avfjaaSiFBwLwtZHg==.cache",
    "unit": "O33a@9fkh++YwffVNeV1RA==.cache",
    "school": "soegnXJ65qU3ZS4O9xLDgg==.cache",
    "global": "DataGloble.cache",
}
ROLE_BY_NAME: Dict[str, str] = {v: k for k, v in FILE_NAMES.items()}
EDITABLE_ROLES = frozenset({"header", "world", "unit", "school", "global"})

ROOT_KEYS = ("qt", "qy", "qu", "qi", "qo", "qp")
WEAPON_KEYS = ("qa", "qs", "qd", "qf", "qg", "qh")
ARTISAN_KEYS = ("qj", "qk", "ql", "qz", "wq", "ww")

PRESETS: List[Dict[str, str]] = [
    {"id": "rich-cultivator", "kr": "만능 재화 충만", "desc": "영석 9,999,999 · 종문 공헌 999,999 · 성주령 9,999"},
    {"id": "full-recovery", "kr": "상태 완전 회복", "desc": "체력·영력·염력·건강·정력·기분 최대치 회복 및 도심 안정화"},
    {"id": "omni-aptitude", "kr": "12대 자질 극대화", "desc": "6대 영근·6대 무기·6대 기예 자질 999 달성"},
    {"id": "immortal-stat", "kr": "불사 전투원", "desc": "수명 9,999년 · 오성/매력 999 · 공격/방어 대폭 강화"},
    {"id": "martial-perfection", "kr": "습득 비급 만렙", "desc": "보유 무예·절기·신법·신통·심법 숙련도·품질 최대치"},
    {"id": "sect-prosperity", "kr": "소속 종문 번영", "desc": "종문 영석·명성·번영도·충성도·약재·광재·호산대진 강화"},
]
PRESET_IDS = frozenset(p["id"] for p in PRESETS)

TEST_FAIL_AT_COMMIT_INDEX = -1
TEST_FAIL_MID_WRITE = False
TEST_FAIL_ROLLBACK = False
TEST_AFTER_PIN_HOOK = None
TEST_BEFORE_LEAF_READ_HOOK = None
TEST_BEFORE_COMMIT_HOOK = None
TEST_BEFORE_PUBLISH_HOOK = None
TEST_BEFORE_STAGE_RMDIR_HOOK = None
TEST_AFTER_UNTOUCHED_COPY_HOOK = None
TEST_AFTER_BACKUP_CREATED_HOOK = None
SAVE_IO_LOCK = threading.RLock()

_DEC_TABLES = [bytes((b - k) & 0xFF for b in range(256)) for k in KEY_BYTES]
_ENC_TABLES = [bytes((b + k) & 0xFF for b in range(256)) for k in KEY_BYTES]
_WINDOWS_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _cipher(data: bytes, encrypt: bool = False) -> bytes:
    out = bytearray(len(data))
    tables = _ENC_TABLES if encrypt else _DEC_TABLES
    for r in range(23):
        out[r::23] = data[r::23].translate(tables[r])
    return bytes(out)


def has_cache_header(raw: bytes) -> bool:
    return isinstance(raw, (bytes, bytearray)) and len(raw) >= 21 and bytes(raw[:21]) == HEADER_BYTES


def decrypt_to_json_bytes(raw: bytes) -> bytes:
    if not has_cache_header(raw):
        raise ValueError("유효한 귀곡팔황 암호화 세이브 헤더가 아닙니다.")
    gz = _cipher(bytes(raw[21:]), encrypt=False)
    if len(gz) < 2 or gz[0] != 0x1F or gz[1] != 0x8B:
        raise ValueError("복호화된 데이터가 GZip 형식이 아닙니다.")
    return gzip.decompress(gz)


def encrypt_json_bytes(plain: bytes) -> bytes:
    gz = gzip.compress(bytes(plain))
    return HEADER_BYTES + _cipher(gz, encrypt=True)


def decode_cache_bytes(raw: bytes, allow_plain_json: bool = True) -> Tuple[str, Any]:
    if has_cache_header(raw):
        text = decrypt_to_json_bytes(raw).decode("utf-8-sig")
        return "cipher-gzip", json.loads(text)
    if allow_plain_json:
        try:
            text = bytes(raw).decode("utf-8-sig")
            stripped = text.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                return "plain-json", json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    raise ValueError("유효한 귀곡팔황 암호화 캐시 또는 JSON 파일이 아닙니다.")


def encode_cache_data(data: Any, mode: str = "cipher-gzip", indent: Optional[int] = None) -> bytes:
    separators = None if indent is not None else (",", ":")
    plain = json.dumps(data, ensure_ascii=False, indent=indent, separators=separators).encode("utf-8")
    if mode == "plain-json":
        return plain
    return encrypt_json_bytes(plain)


def classify_file_role(name: str) -> str:
    base = os.path.basename(name)
    if base in ROLE_BY_NAME:
        return ROLE_BY_NAME[base]
    if base.lower().endswith(".cache"):
        return "other"
    return "ignore"


def is_valid_cache_filename(name: str) -> bool:
    if not isinstance(name, str) or not name or os.path.basename(name) != name:
        return False
    if any(tok in name for tok in ("/", "\\", ":", "\x00", "..")):
        return False
    if name != name.strip(" .") or name.endswith((".", " ")):
        return False
    stem = name.split(".", 1)[0].rstrip(" .").upper()
    if not stem or stem in _WINDOWS_RESERVED:
        return False
    if name in ("CacheData", "CacheFixVer"):
        return True
    return bool(name.lower().endswith(".cache") and re.fullmatch(r"[A-Za-z0-9_@+=.\-]+", name))


def _is_reparse_or_link(path: Path) -> bool:
    s = str(path)
    if os.path.islink(s):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if isjunction(s):
                return True
        except OSError:
            pass
    try:
        st = os.lstat(s)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def assert_safe_path(path: Path, root_anchor: Optional[Path] = None) -> Path:
    s = str(path)
    if s.startswith("\\\\") or s.startswith("//"):
        raise PermissionError("안전하지 않은 경로입니다: UNC 네트워크 경로는 허용되지 않습니다.")
    rest = s[2:] if re.match(r"^[A-Za-z]:", s) else s
    if ":" in rest:
        raise PermissionError("안전하지 않은 경로입니다: 대체 데이터 스트림(ADS)은 허용되지 않습니다.")
    p = Path(os.path.abspath(s))
    for part in p.parts:
        if part in ("/", "\\") or re.fullmatch(r"[A-Za-z]:\\?", part):
            continue
        stem = part.split(".", 1)[0].rstrip(" .").upper()
        if stem in _WINDOWS_RESERVED:
            raise PermissionError(f"안전하지 않은 경로입니다: 예약된 장치 이름({part})은 허용되지 않습니다.")
    anchor = Path(os.path.abspath(str(root_anchor))) if root_anchor is not None else None
    if anchor is not None:
        try:
            p.relative_to(anchor)
        except ValueError:
            raise PermissionError("안전하지 않은 경로입니다: 허용된 루트 디렉터리를 벗어났습니다.")
    cur = p
    while True:
        if _is_reparse_or_link(cur):
            raise PermissionError(f"안전하지 않은 경로입니다: 심볼릭 링크 또는 정션이 감지되었습니다 ({cur}).")
        if cur.exists() and cur.is_file():
            st = cur.stat()
            if st.st_nlink > 1:
                raise PermissionError(f"안전하지 않은 경로입니다: 하드 링크 파일은 허용되지 않습니다 ({cur}).")
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    if anchor is not None:
        real_anchor = Path(os.path.realpath(str(anchor)))
        real_p = Path(os.path.realpath(str(p)))
        try:
            real_p.relative_to(real_anchor)
        except ValueError:
            raise PermissionError("안전하지 않은 경로입니다: 정션 또는 링크로 인해 루트 디렉터리를 벗어났습니다.")
    return p


def is_game_running() -> bool:
    if os.environ.get("TOISE_SIMULATE_GAME_RUNNING") == "1":
        return True
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq guigubahuang.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "guigubahuang.exe" in (proc.stdout or "").lower()
        except Exception:
            return False
    try:
        for comm in Path("/proc").glob("[0-9]*/comm"):
            try:
                if comm.read_text(errors="ignore").strip().lower() == "guigubahuang":
                    return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path, root_anchor: Optional[Path] = None) -> Optional[str]:
    try:
        return _sha256_bytes(_read_pinned_bytes(path, root_anchor=root_anchor))
    except (OSError, PermissionError):
        return None


_WIN32_CACHE = None


def _win32_api():
    global _WIN32_CACHE
    if _WIN32_CACHE is not None:
        return _WIN32_CACHE
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    k32.ReadFile.restype = wintypes.BOOL
    k32.WriteFile.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    k32.WriteFile.restype = wintypes.BOOL
    k32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    k32.FlushFileBuffers.restype = wintypes.BOOL
    k32.SetEndOfFile.argtypes = [wintypes.HANDLE]
    k32.SetEndOfFile.restype = wintypes.BOOL
    k32.SetFilePointer.argtypes = [wintypes.HANDLE, wintypes.LONG, ctypes.POINTER(wintypes.LONG), wintypes.DWORD]
    k32.SetFilePointer.restype = wintypes.DWORD
    k32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)]
    k32.GetFileInformationByHandle.restype = wintypes.BOOL
    k32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    k32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    k32.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    k32.SetFileInformationByHandle.restype = wintypes.BOOL

    _WIN32_CACHE = (ctypes, wintypes, k32, BY_HANDLE_FILE_INFORMATION)
    return _WIN32_CACHE


def _validate_leaf_name(name: str) -> str:
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise PermissionError(f"안전하지 않은 파일 이름입니다: {name!r}")
    if any(tok in name for tok in ("/", "\\", ":", "\x00")) or os.path.basename(name) != name:
        raise PermissionError(f"안전하지 않은 파일 이름입니다: {name!r}")
    stem = name.split(".", 1)[0].rstrip(" .").upper()
    if not stem or stem in _WINDOWS_RESERVED:
        raise PermissionError(f"예약된 장치 이름은 사용할 수 없습니다: {name}")
    return name


class PinnedDirectory:
    def __init__(self, raw_parent: Path, root_anchor: Optional[Path] = None) -> None:
        self.raw_parent = Path(raw_parent)
        self.root_anchor = Path(root_anchor) if root_anchor is not None else None
        self.clean_parent: Optional[Path] = None
        self._fd: Optional[int] = None
        self._handle: Any = None

    def __enter__(self) -> "PinnedDirectory":
        clean_parent = assert_safe_path(self.raw_parent, root_anchor=self.root_anchor)
        self.clean_parent = clean_parent
        if callable(TEST_AFTER_PIN_HOOK):
            TEST_AFTER_PIN_HOOK(clean_parent)

        if os.name != "nt":
            dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open("/", dir_flags)
            try:
                parts = clean_parent.parts[1:] if clean_parent.parts and clean_parent.parts[0] == os.sep else clean_parent.parts
                for part in parts:
                    try:
                        next_fd = os.open(part, dir_flags, dir_fd=fd)
                    except OSError as exc:
                        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                            raise PermissionError(f"안전하지 않은 디렉터리 경로입니다: {clean_parent}") from exc
                        raise
                    if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                        os.close(next_fd)
                        raise PermissionError(f"디렉터리가 아닙니다: {clean_parent}")
                    os.close(fd)
                    fd = next_fd
                self._fd = fd
            except BaseException:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            return self

        ctypes, wintypes, k32, BY_HANDLE_FILE_INFORMATION = _win32_api()
        invalid = wintypes.HANDLE(-1).value
        handle = k32.CreateFileW(str(clean_parent), 1, 3, None, 3, 0x02200000, None)
        if handle == invalid:
            raise PermissionError(f"디렉터리를 고정할 수 없습니다: {clean_parent}")
        self._handle = handle
        try:
            info = BY_HANDLE_FILE_INFORMATION()
            if not k32.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise PermissionError(f"디렉터리 핸들 정보를 확인할 수 없습니다: {clean_parent}")
            if (info.dwFileAttributes & 0x400) != 0 or (info.dwFileAttributes & 0x10) == 0:
                raise PermissionError(f"안전하지 않은 디렉터리(정션/심볼릭 링크)입니다: {clean_parent}")
            buf = ctypes.create_unicode_buffer(32768)
            n = k32.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
            if n == 0 or n >= len(buf):
                raise PermissionError(f"최종 디렉터리 경로를 확인할 수 없습니다: {clean_parent}")
            final_str = buf.value
            if final_str.startswith("\\\\?\\UNC\\"):
                final_str = "\\\\" + final_str[8:]
            elif final_str.startswith("\\\\?\\"):
                final_str = final_str[4:]
            if os.path.normcase(os.path.abspath(final_str)) != os.path.normcase(os.path.abspath(str(clean_parent))):
                raise PermissionError(f"디렉터리 경로가 변경되었습니다: {clean_parent}")
            if self.root_anchor is not None:
                real_anchor = Path(os.path.realpath(str(self.root_anchor)))
                try:
                    Path(os.path.abspath(final_str)).relative_to(real_anchor)
                except ValueError:
                    raise PermissionError("고정된 디렉터리가 허용 루트를 벗어났습니다.")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._handle is not None:
            try:
                _, _, k32, _ = _win32_api()
                k32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        return False

    @staticmethod
    def _win_verify_handle_path(h: Any, expected_full: str) -> None:
        ctypes, _, k32, _ = _win32_api()
        buf = ctypes.create_unicode_buffer(32768)
        n = k32.GetFinalPathNameByHandleW(h, buf, len(buf), 0)
        if n == 0 or n >= len(buf):
            raise PermissionError(f"최종 파일 경로를 확인할 수 없습니다: {expected_full}")
        final_str = buf.value
        if final_str.startswith("\\\\?\\UNC\\"):
            final_str = "\\\\" + final_str[8:]
        elif final_str.startswith("\\\\?\\"):
            final_str = final_str[4:]
        if os.path.normcase(os.path.abspath(final_str)) != os.path.normcase(os.path.abspath(expected_full)):
            raise PermissionError(f"열린 핸들의 최종 경로가 일치하지 않습니다: {expected_full}")

    def list_leaf_names(self) -> List[str]:
        if os.name != "nt":
            return sorted(os.listdir(self._fd))
        return sorted(os.listdir(str(self.clean_parent)))

    def lstat_leaf(self, name: str) -> Any:
        _validate_leaf_name(name)
        if os.name != "nt":
            st = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode):
                raise PermissionError(f"심볼릭 링크 파일은 허용되지 않습니다: {name}")
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                raise PermissionError(f"하드 링크 파일은 허용되지 않습니다: {name}")
            return st

        ctypes, wintypes, k32, BY_HANDLE_FILE_INFORMATION = _win32_api()
        full = str(self.clean_parent / name)
        h = k32.CreateFileW(full, 0, 7, None, 3, 0x02200000, None)
        if h == wintypes.HANDLE(-1).value:
            err = ctypes.get_last_error()
            if err in (2, 3):
                raise FileNotFoundError(full)
            raise PermissionError(f"파일 상태를 확인할 수 없습니다: {name}")
        try:
            info = BY_HANDLE_FILE_INFORMATION()
            if not k32.GetFileInformationByHandle(h, ctypes.byref(info)):
                raise PermissionError(f"파일 핸들 정보를 확인할 수 없습니다: {name}")
            if (info.dwFileAttributes & 0x400) != 0:
                raise PermissionError(f"심볼릭 링크 또는 정션 파일은 허용되지 않습니다: {name}")
            if (info.dwFileAttributes & 0x10) == 0 and info.nNumberOfLinks > 1:
                raise PermissionError(f"하드 링크 파일은 허용되지 않습니다: {name}")
            self._win_verify_handle_path(h, full)
            return info
        finally:
            k32.CloseHandle(h)

    def exists_leaf(self, name: str) -> bool:
        try:
            self.lstat_leaf(name)
            return True
        except FileNotFoundError:
            return False

    def _win_open_and_read_leaf(
        self, name: str, desired_access: int, share_mode: int, keep_open: bool
    ) -> Tuple[Any, bytes]:
        ctypes, wintypes, k32, BY_HANDLE_FILE_INFORMATION = _win32_api()
        full = str(self.clean_parent / name)
        h = k32.CreateFileW(full, desired_access, share_mode, None, 3, 0x00200000, None)
        if h == wintypes.HANDLE(-1).value:
            err = ctypes.get_last_error()
            if err in (2, 3):
                raise FileNotFoundError(full)
            raise PermissionError(f"파일을 열 수 없습니다({err}): {name}")
        try:
            info = BY_HANDLE_FILE_INFORMATION()
            if not k32.GetFileInformationByHandle(h, ctypes.byref(info)):
                raise PermissionError(f"파일 핸들 정보를 확인할 수 없습니다: {name}")
            if (info.dwFileAttributes & 0x400) != 0 or (info.dwFileAttributes & 0x10) != 0 or info.nNumberOfLinks > 1:
                raise PermissionError(f"안전하지 않은 파일입니다: {name}")
            self._win_verify_handle_path(h, full)
            chunks = []
            buf = ctypes.create_string_buffer(1024 * 1024)
            read = wintypes.DWORD(0)
            while True:
                if not k32.ReadFile(h, buf, len(buf), ctypes.byref(read), None):
                    raise OSError(f"파일 읽기 실패: {name}")
                if read.value == 0:
                    break
                chunks.append(buf.raw[: read.value])
            data = b"".join(chunks)
            if keep_open:
                return h, data
            k32.CloseHandle(h)
            return None, data
        except BaseException:
            k32.CloseHandle(h)
            raise

    def read_leaf_bytes(self, name: str) -> bytes:
        _validate_leaf_name(name)
        if callable(TEST_BEFORE_LEAF_READ_HOOK):
            TEST_BEFORE_LEAF_READ_HOOK(self.clean_parent, name)
        if os.name != "nt":
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(name, flags, dir_fd=self._fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise PermissionError(f"안전하지 않은 파일입니다: {name}") from exc
                raise
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
                    raise PermissionError(f"일반 단일 링크 파일이 아닙니다: {name}")
                chunks: List[bytes] = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                os.close(fd)
        _, data = self._win_open_and_read_leaf(name, desired_access=0x80000000, share_mode=3, keep_open=False)
        return data

    def open_win_locked_existing(self, name: str) -> Tuple[Any, bytes]:
        _validate_leaf_name(name)
        return self._win_open_and_read_leaf(name, desired_access=0xC0000000, share_mode=0, keep_open=True)

    def overwrite_win_locked_handle(self, h: Any, data: bytes, label: str, allow_fault: bool = True) -> None:
        _, _, k32, _ = _win32_api()
        if k32.SetFilePointer(h, 0, None, 0) == 0xFFFFFFFF:
            raise OSError(f"파일 포인터 초기화 실패: {label}")
        if not k32.SetEndOfFile(h):
            raise OSError(f"파일 길이 초기화 실패: {label}")
        if allow_fault and TEST_FAIL_MID_WRITE:
            raise OSError(f"테스트용 부분 쓰기 중단(SetEndOfFile 직후): {label}")
        self._win_write_and_verify_handle(h, bytes(data), label)

    def acquire_posix_leaf_lock(self, name: str):
        _validate_leaf_name(name)
        import fcntl

        lock_name = f".toi-lock-{name}"
        fd = -1
        while True:
            fd = os.open(
                lock_name,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._fd,
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                st_fd = os.fstat(fd)
                st_path = os.stat(lock_name, dir_fd=self._fd, follow_symlinks=False)
                if (st_fd.st_dev, st_fd.st_ino) == (st_path.st_dev, st_path.st_ino):
                    break
            except FileNotFoundError:
                pass
            except BaseException:
                os.close(fd)
                raise
            os.close(fd)
            fd = -1

        def release() -> None:
            nonlocal fd
            if fd < 0:
                return
            try:
                st_cur = os.stat(lock_name, dir_fd=self._fd, follow_symlinks=False)
                if stat.S_ISREG(st_cur.st_mode) and (st_cur.st_dev, st_cur.st_ino) == (st_fd.st_dev, st_fd.st_ino) and st_cur.st_nlink == 1:
                    os.unlink(lock_name, dir_fd=self._fd)
            except (FileNotFoundError, OSError):
                pass
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
                fd = -1

        return release

    def _win_verify_handle_sha256(
        self,
        h: Any,
        expected_len: int,
        expected_sha256: str,
        label: str,
    ) -> None:
        ctypes, wintypes, k32, _ = _win32_api()
        if k32.SetFilePointer(h, 0, None, 0) == 0xFFFFFFFF:
            raise OSError(f"파일 포인터 이동 실패: {label}")
        chunks: List[bytes] = []
        rbuf = ctypes.create_string_buffer(1024 * 1024)
        read = wintypes.DWORD(0)
        total = 0
        while True:
            if not k32.ReadFile(h, rbuf, len(rbuf), ctypes.byref(read), None):
                raise OSError(f"파일 검증 읽기 실패: {label}")
            if read.value == 0:
                break
            total += read.value
            chunks.append(rbuf.raw[: read.value])
        if total != expected_len:
            raise OSError(f"파일 무결성 검증 실패(크기 불일치): {label}")
        if _sha256_bytes(b"".join(chunks)) != expected_sha256:
            raise OSError(f"파일 무결성 검증 실패: {label}")

    def _win_write_and_verify_handle(self, h: Any, data: bytes, label: str) -> None:
        ctypes, wintypes, k32, _ = _win32_api()
        if data:
            written = wintypes.DWORD(0)
            buf = ctypes.create_string_buffer(data, len(data))
            if not k32.WriteFile(h, buf, len(data), ctypes.byref(written), None) or written.value != len(data):
                raise OSError(f"파일 쓰기 실패: {label}")
        if not k32.FlushFileBuffers(h):
            raise OSError(f"파일 플러시 실패: {label}")
        self._win_verify_handle_sha256(h, len(data), _sha256_bytes(data), label)

    @staticmethod
    def _posix_verify_fd_sha256(
        fd: int,
        expected_len: int,
        expected_sha256: str,
        label: str,
    ) -> None:
        st_cur = os.fstat(fd)
        if not stat.S_ISREG(st_cur.st_mode) or st_cur.st_size != expected_len:
            raise PermissionError(f"임시 파일 무결성 검증 실패(크기 불일치): {label}")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: List[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        read_bytes = b"".join(chunks)
        if len(read_bytes) != expected_len or _sha256_bytes(read_bytes) != expected_sha256:
            raise PermissionError(f"임시 파일이 게시 직전 외부에서 변조되었습니다: {label}")

    @staticmethod
    def _posix_write_and_verify_fd(fd: int, raw: bytes, label: str, state: Optional[Dict[str, int]] = None) -> None:
        view = memoryview(raw)
        off = 0
        if state is not None:
            state["written_bytes"] = 0
        while off < len(view):
            n = os.write(fd, view[off:])
            if n <= 0:
                raise OSError(errno.EIO, f"파일 부분 쓰기 중단(0바이트 반환): {label}")
            off += n
            if state is not None:
                state["written_bytes"] = off
        os.fsync(fd)
        PinnedDirectory._posix_verify_fd_sha256(fd, len(raw), _sha256_bytes(raw), label)

    def write_exclusive_leaf(self, name: str, data: bytes, keep_win_handle: bool = False) -> Tuple[Optional[Tuple[int, int]], Any]:
        _validate_leaf_name(name)
        raw = bytes(data)
        if os.name != "nt":
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = -1
            leaf_created = False
            st_fd: Optional[os.stat_result] = None
            write_state: Dict[str, int] = {"written_bytes": 0}
            try:
                fd = os.open(name, flags, 0o600, dir_fd=self._fd)
                leaf_created = True
                st_fd = os.fstat(fd)
                self._posix_write_and_verify_fd(fd, raw, name, state=write_state)
                st_entry = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
                if not (stat.S_ISREG(st_entry.st_mode) and (st_entry.st_dev, st_entry.st_ino) == (st_fd.st_dev, st_fd.st_ino) and st_entry.st_nlink == 1):
                    raise PermissionError(f"배타 백업 파일이 외부에서 교체되었습니다: {name}")
                try:
                    os.fsync(self._fd)
                except OSError:
                    pass
                try:
                    os.close(fd)
                except OSError:
                    pass
                fd = -1
                return (st_fd.st_dev, st_fd.st_ino), None
            except Exception as orig_exc:
                written_n = write_state.get("written_bytes", 0)
                exp_sha = _sha256_bytes(raw[:written_n]) if st_fd is not None else None
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    fd = -1
                if leaf_created:
                    c_err = self._cleanup_posix_owned_entry(
                        self._fd,
                        name,
                        self.clean_parent / name,
                        (st_fd.st_dev, st_fd.st_ino) if st_fd is not None else None,
                        exp_sha,
                        allow_stage_link=False,
                    )
                    if c_err is not None:
                        raise RuntimeError(f"배타 파일 생성 실패 정리 오류(잔존 경로 확인 필요): {c_err}") from orig_exc
                raise
            finally:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    fd = -1

        ctypes, wintypes, k32, _ = _win32_api()
        full = str(self.clean_parent / name)
        h = k32.CreateFileW(full, 0xC0010000, 0, None, 1, 0x80, None)
        if h == wintypes.HANDLE(-1).value:
            raise OSError(f"배타 파일을 생성할 수 없습니다: {name}")
        owned_id = _win_get_handle_file_id(h)
        closed_or_transferred = False
        try:
            self._win_write_and_verify_handle(h, raw, name)
            if keep_win_handle:
                closed_or_transferred = True
                return None, h
            closed_or_transferred = True
            _win_close_handle(h, delete_on_close=False)
            return None, None
        except Exception as orig_exc:
            if not closed_or_transferred:
                closed_or_transferred = True
                c_err = self._cleanup_win_owned_handle(h, name, Path(full), owned_id)
                if c_err is not None:
                    raise RuntimeError(f"배타 파일 생성 실패 정리 오류(잔존 경로 확인 필요): {c_err}") from orig_exc
            raise
        finally:
            if not closed_or_transferred:
                try:
                    _win_close_handle(h, delete_on_close=True)
                except OSError:
                    pass

    def publish_atomic_leaf(
        self,
        tmp_name: str,
        dst_name: str,
        data: bytes,
        replace_existing: bool = True,
        out_state: Optional[Dict[str, Any]] = None,
        allow_fault: bool = True,
        keep_win_handle: bool = False,
        expected_dst_owner: Optional[Tuple[Optional[Tuple[int, int]], str]] = None,
    ) -> None:
        _validate_leaf_name(tmp_name)
        _validate_leaf_name(dst_name)
        if out_state is not None:
            out_state["published"] = False
        raw = bytes(data)
        raw_sha256 = _sha256_bytes(raw)
        if os.name != "nt":
            stage_dir = f".toi-stage-{os.getpid()}-{secrets.token_hex(6)}"
            stage_fd = -1
            fd = -1
            linked_dst = False
            stage_unlinked = False
            tmp_created = False
            st_fd: Optional[os.stat_result] = None
            st_dir: Optional[os.stat_result] = None
            write_state: Dict[str, int] = {"written_bytes": 0}
            rmdir_attempted = False
            stage_removed = False
            os.mkdir(stage_dir, 0o700, dir_fd=self._fd)
            try:
                st_mkdir = os.stat(stage_dir, dir_fd=self._fd, follow_symlinks=False)
                if not stat.S_ISDIR(st_mkdir.st_mode) or st_mkdir.st_uid != os.geteuid():
                    raise PermissionError("임시 게시 디렉터리 초기 상태 검증에 실패했습니다.")
                stage_fd = os.open(
                    stage_dir,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=self._fd,
                )
                st_open = os.fstat(stage_fd)
                st_path_open = os.stat(stage_dir, dir_fd=self._fd, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(st_open.st_mode)
                    or not stat.S_ISDIR(st_path_open.st_mode)
                    or st_open.st_uid != os.geteuid()
                    or (st_open.st_dev, st_open.st_ino) != (st_mkdir.st_dev, st_mkdir.st_ino)
                    or (st_path_open.st_dev, st_path_open.st_ino) != (st_mkdir.st_dev, st_mkdir.st_ino)
                    or os.listdir(stage_fd)
                ):
                    raise PermissionError("임시 게시 디렉터리가 초기 준비 중 외부에서 교체되었습니다.")
                os.fchmod(stage_fd, 0o700)
                st_chmod = os.fstat(stage_fd)
                if not stat.S_ISDIR(st_chmod.st_mode) or st_chmod.st_uid != os.geteuid() or (st_chmod.st_mode & 0o077) != 0:
                    raise PermissionError("임시 게시 디렉터리 권한 검증에 실패했습니다.")
                st_dir = st_chmod

                fd = os.open(
                    tmp_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=stage_fd,
                )
                tmp_created = True
                st_fd = os.fstat(fd)
                self._posix_write_and_verify_fd(fd, raw, tmp_name, state=write_state)

                if callable(TEST_BEFORE_PUBLISH_HOOK):
                    TEST_BEFORE_PUBLISH_HOOK(self.clean_parent / stage_dir / tmp_name)

                try:
                    st_dir_pre = os.stat(stage_dir, dir_fd=self._fd, follow_symlinks=False)
                except FileNotFoundError as fnf_exc:
                    raise PermissionError("임시 게시 디렉터리가 게시 직전 외부에서 이동·삭제되었습니다.") from fnf_exc
                if (
                    not stat.S_ISDIR(st_dir_pre.st_mode)
                    or (st_dir_pre.st_dev, st_dir_pre.st_ino) != (st_dir.st_dev, st_dir.st_ino)
                ):
                    raise PermissionError("임시 게시 디렉터리가 게시 직전 외부에서 교체되었습니다.")

                st_pre = os.stat(tmp_name, dir_fd=stage_fd, follow_symlinks=False)
                if (
                    not stat.S_ISREG(st_pre.st_mode)
                    or (st_pre.st_dev, st_pre.st_ino) != (st_fd.st_dev, st_fd.st_ino)
                    or st_pre.st_nlink != 1
                ):
                    raise PermissionError("임시 파일이 게시 직전 외부에서 교체되었습니다.")

                self._posix_verify_fd_sha256(fd, len(raw), raw_sha256, tmp_name)

                if self.exists_leaf(dst_name):
                    if not replace_existing:
                        raise FileExistsError(f"대상 파일이 이미 존재합니다: {dst_name}")
                    st_dst = self.lstat_leaf(dst_name)
                    if not stat.S_ISREG(st_dst.st_mode):
                        raise PermissionError(f"대상 경로가 일반 파일이 아닙니다: {dst_name}")

                if replace_existing:
                    if expected_dst_owner is not None:
                        exp_stat, exp_sha = expected_dst_owner
                        if not self.has_owned_leaf_state(dst_name, exp_stat, exp_sha):
                            raise RuntimeError(f"대상 파일이 게시 직전 외부에서 변경·교체되었습니다: {dst_name}")
                    os.replace(tmp_name, dst_name, src_dir_fd=stage_fd, dst_dir_fd=self._fd)
                    stage_unlinked = True
                    if out_state is not None:
                        out_state["published"] = True
                        out_state["published_stat"] = (st_fd.st_dev, st_fd.st_ino)
                        out_state["published_sha256"] = raw_sha256
                        out_state["stage_link_retained"] = False
                else:
                    os.link(tmp_name, dst_name, src_dir_fd=stage_fd, dst_dir_fd=self._fd)
                    linked_dst = True
                    if out_state is not None:
                        out_state["published"] = True
                        out_state["published_stat"] = (st_fd.st_dev, st_fd.st_ino)
                        out_state["published_sha256"] = raw_sha256
                        out_state["stage_link_retained"] = True
                    st_tmp_pre = os.stat(tmp_name, dir_fd=stage_fd, follow_symlinks=False)
                    if (st_tmp_pre.st_dev, st_tmp_pre.st_ino) != (st_fd.st_dev, st_fd.st_ino):
                        raise PermissionError("임시 파일이 링크 직후 외부에서 교체되었습니다.")
                    os.unlink(tmp_name, dir_fd=stage_fd)
                    stage_unlinked = True
                    if out_state is not None:
                        out_state["stage_link_retained"] = False

                if allow_fault and TEST_FAIL_MID_WRITE:
                    raise OSError(f"테스트용 게시 직후 중단: {dst_name}")

                st_post = os.stat(dst_name, dir_fd=self._fd, follow_symlinks=False)
                if (st_post.st_dev, st_post.st_ino) != (st_fd.st_dev, st_fd.st_ino) or st_post.st_nlink != 1:
                    raise PermissionError("게시된 대상 파일의 아이노드 또는 링크 수가 일치하지 않습니다.")
                if st_post.st_size != len(raw):
                    raise PermissionError("게시된 대상 파일의 크기가 일치하지 않습니다.")
                self._posix_verify_fd_sha256(fd, len(raw), raw_sha256, dst_name)
                try:
                    os.fsync(self._fd)
                except OSError:
                    pass

                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    fd = -1
                if stage_fd >= 0:
                    try:
                        os.close(stage_fd)
                    except OSError:
                        pass
                    stage_fd = -1
                if allow_fault and callable(TEST_BEFORE_STAGE_RMDIR_HOOK):
                    TEST_BEFORE_STAGE_RMDIR_HOOK(self.clean_parent / stage_dir)
                rmdir_attempted = True
                rm_err = self._cleanup_posix_owned_stage_dir(
                    stage_dir,
                    (st_dir.st_dev, st_dir.st_ino) if st_dir is not None else None,
                )
                if rm_err is not None:
                    raise RuntimeError(f"임시 파일 정리 실패(잔존 경로 확인 필요): {rm_err}")
                stage_removed = True
            except Exception as orig_exc:
                written_n = write_state.get("written_bytes", 0)
                exp_sha = (raw_sha256 if written_n == len(raw) else _sha256_bytes(raw[:written_n])) if st_fd is not None else None
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    fd = -1
                c_err: Optional[str] = None
                if stage_fd >= 0:
                    if tmp_created and not stage_unlinked:
                        c_err = self._cleanup_posix_owned_entry(
                            stage_fd,
                            tmp_name,
                            self.clean_parent / stage_dir / tmp_name,
                            (st_fd.st_dev, st_fd.st_ino) if st_fd is not None else None,
                            exp_sha,
                            allow_stage_link=linked_dst,
                        )
                        if c_err is None:
                            stage_unlinked = True
                            if out_state is not None and linked_dst:
                                out_state["stage_link_retained"] = False
                    try:
                        os.close(stage_fd)
                    except OSError:
                        pass
                    stage_fd = -1
                if c_err is None and not stage_removed and not rmdir_attempted:
                    c_err = self._cleanup_posix_owned_stage_dir(
                        stage_dir,
                        (st_dir.st_dev, st_dir.st_ino) if st_dir is not None else None,
                    )
                    if c_err is None:
                        stage_removed = True
                if c_err is not None:
                    raise RuntimeError(f"임시 파일 정리 실패(잔존 경로 확인 필요): {c_err}") from orig_exc
                raise
            finally:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if stage_fd >= 0:
                    try:
                        os.close(stage_fd)
                    except OSError:
                        pass
            return

        ctypes, wintypes, k32, _ = _win32_api()
        tmp_full = str(self.clean_parent / tmp_name)
        dst_full = str(self.clean_parent / dst_name)
        if self.exists_leaf(dst_name):
            if not replace_existing:
                raise FileExistsError(f"대상 파일이 이미 존재합니다: {dst_name}")
            info = self.lstat_leaf(dst_name)
            if (info.dwFileAttributes & 0x10) != 0:
                raise PermissionError(f"대상 경로가 디렉터리입니다: {dst_name}")
        h_tmp = k32.CreateFileW(tmp_full, 0xC0010000, 0, None, 1, 0x80, None)
        if h_tmp == wintypes.HANDLE(-1).value:
            raise OSError(f"임시 파일을 생성할 수 없습니다: {tmp_name}")
        owned_tmp_id = _win_get_handle_file_id(h_tmp)
        renamed = False
        closed_or_transferred = False
        try:
            self._win_write_and_verify_handle(h_tmp, raw, tmp_name)
            if callable(TEST_BEFORE_PUBLISH_HOOK):
                TEST_BEFORE_PUBLISH_HOOK(Path(tmp_full))
            self._win_verify_handle_sha256(h_tmp, len(raw), raw_sha256, tmp_name)
            target_utf16 = (dst_full + "\x00").encode("utf-16-le")
            byte_len = len(dst_full.encode("utf-16-le"))

            class FILE_RENAME_INFO(ctypes.Structure):
                _fields_ = [
                    ("ReplaceIfExists", wintypes.BOOLEAN),
                    ("RootDirectory", wintypes.HANDLE),
                    ("FileNameLength", wintypes.DWORD),
                    ("FileName", ctypes.c_ubyte * len(target_utf16)),
                ]

            rinfo = FILE_RENAME_INFO()
            rinfo.ReplaceIfExists = 1 if replace_existing else 0
            rinfo.RootDirectory = None
            rinfo.FileNameLength = byte_len
            ctypes.memmove(rinfo.FileName, target_utf16, len(target_utf16))
            if not k32.SetFileInformationByHandle(h_tmp, 3, ctypes.byref(rinfo), ctypes.sizeof(rinfo)):
                err_code = ctypes.get_last_error()
                if not replace_existing and err_code in (5, 80, 183):
                    raise FileExistsError(f"대상 파일이 외부에서 생성되어 덮어쓰기가 거부되었습니다({err_code}): {dst_name}")
                raise OSError(f"원자적 핸들 이름 변경 실패({err_code}): {dst_name}")
            renamed = True
            if out_state is not None:
                out_state["published"] = True
                out_state["published_sha256"] = raw_sha256
                if keep_win_handle:
                    out_state["win_handle"] = h_tmp
                    closed_or_transferred = True
            self._win_verify_handle_sha256(h_tmp, len(raw), raw_sha256, dst_name)
            if allow_fault and TEST_FAIL_MID_WRITE:
                raise OSError(f"테스트용 게시 직후 중단: {dst_name}")
            if not closed_or_transferred:
                closed_or_transferred = True
                _win_close_handle(h_tmp, delete_on_close=False)
        except Exception as orig_exc:
            if not closed_or_transferred:
                closed_or_transferred = True
                if not renamed:
                    c_err = self._cleanup_win_owned_handle(h_tmp, tmp_name, Path(tmp_full), owned_tmp_id)
                    if c_err is not None:
                        raise RuntimeError(f"임시 파일 정리 실패(잔존 경로 확인 필요): {c_err}") from orig_exc
                else:
                    try:
                        _win_close_handle(h_tmp, delete_on_close=False)
                    except OSError:
                        pass
            raise
        finally:
            if not closed_or_transferred:
                try:
                    _win_close_handle(h_tmp, delete_on_close=(not renamed))
                except OSError:
                    pass

    def unlink_leaf(self, name: str) -> None:
        _validate_leaf_name(name)
        try:
            if os.name != "nt":
                os.unlink(name, dir_fd=self._fd)
            else:
                os.unlink(str(self.clean_parent / name))
        except FileNotFoundError:
            pass

    def has_owned_leaf_state(
        self,
        name: str,
        expected_stat: Optional[Tuple[int, int]],
        expected_sha256: str,
        allow_stage_link: bool = False,
        dir_fd: Optional[int] = None,
    ) -> bool:
        _validate_leaf_name(name)
        if os.name == "nt" or expected_stat is None or not expected_sha256:
            return False
        eff_dir_fd = self._fd if dir_fd is None else dir_fd
        try:
            lst = os.stat(name, dir_fd=eff_dir_fd, follow_symlinks=False)
        except (FileNotFoundError, PermissionError, OSError):
            return False
        max_nlink = 2 if allow_stage_link else 1
        if not stat.S_ISREG(lst.st_mode) or (lst.st_dev, lst.st_ino) != expected_stat:
            return False
        if not (1 <= lst.st_nlink <= max_nlink):
            return False
        fd = -1
        try:
            fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=eff_dir_fd,
            )
            st_f = os.fstat(fd)
            if (st_f.st_dev, st_f.st_ino) != expected_stat:
                return False
            if not (1 <= st_f.st_nlink <= max_nlink):
                return False
            chunks: List[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            cur_bytes = b"".join(chunks)
        except (FileNotFoundError, PermissionError, OSError):
            return False
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        return _sha256_bytes(cur_bytes) == expected_sha256

    def _cleanup_posix_owned_entry(
        self,
        dir_fd: int,
        name: str,
        display_path: Path,
        expected_stat: Optional[Tuple[int, int]],
        expected_sha256: Optional[str],
        allow_stage_link: bool = False,
    ) -> Optional[str]:
        try:
            os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as st_exc:
            return f"{display_path}: 상태 확인 실패({st_exc})"
        if not (bool(expected_sha256) and self.has_owned_leaf_state(name, expected_stat, expected_sha256, allow_stage_link=allow_stage_link, dir_fd=dir_fd)):
            return f"{display_path}: 임시·배타 파일 소유권 불일치로 삭제 중단(외부 파일 보존)"
        try:
            os.unlink(name, dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        except OSError as ul_exc:
            return f"{display_path}: 파일 삭제 실패({ul_exc})"
        return None

    def _cleanup_posix_owned_stage_dir(
        self,
        stage_dir: str,
        expected_dir_stat: Optional[Tuple[int, int]],
    ) -> Optional[str]:
        display_path = self.clean_parent / stage_dir
        try:
            st_cur = os.stat(stage_dir, dir_fd=self._fd, follow_symlinks=False)
        except FileNotFoundError:
            return f"{display_path}: 임시 스테이징 디렉터리가 외부에서 이동·삭제되어 정리를 완료하지 못했습니다"
        except OSError as st_exc:
            return f"{display_path}: 스테이징 디렉터리 상태 확인 실패({st_exc})"
        if expected_dir_stat is None:
            return f"{display_path}: 임시 스테이징 디렉터리 소유권 미확인으로 삭제 중단(외부 디렉터리 보존)"
        if (
            not stat.S_ISDIR(st_cur.st_mode)
            or (st_cur.st_dev, st_cur.st_ino) != expected_dir_stat
        ):
            return f"{display_path}: 임시 스테이징 디렉터리 소유권 불일치로 삭제 중단(외부 디렉터리 보존)"
        try:
            os.rmdir(stage_dir, dir_fd=self._fd)
        except FileNotFoundError:
            return f"{display_path}: 임시 스테이징 디렉터리가 삭제 직전 외부에서 이동·삭제되었습니다"
        except OSError as rm_exc:
            return f"{display_path}: 임시 스테이징 디렉터리 삭제 실패({rm_exc})"
        return None

    def _cleanup_win_owned_handle(
        self,
        h: Any,
        leaf_name: str,
        display_path: Path,
        owned_id: Optional[Tuple[int, int, int]],
        residual_msg: str = "핸들 닫기 후 잔존 파일 감지",
    ) -> Optional[str]:
        try:
            _win_close_handle(h, delete_on_close=True)
        except Exception as del_exc:
            return f"{display_path}: {del_exc}"
        try:
            cur = self.lstat_leaf(leaf_name)
        except FileNotFoundError:
            return None
        except Exception as st_exc:
            return f"{display_path}: 삭제 후 상태 확인 실패({st_exc})"
        cur_id = (
            int(cur.dwVolumeSerialNumber),
            int(cur.nFileIndexHigh),
            int(cur.nFileIndexLow),
        )
        if owned_id is None or cur_id == owned_id:
            return f"{display_path}: {residual_msg}"
        return None

    def unlink_if_owned_leaf(
        self,
        name: str,
        expected_stat: Optional[Tuple[int, int]],
        expected_sha256: str,
        allow_stage_link: bool = False,
    ) -> bool:
        _validate_leaf_name(name)
        if os.name == "nt":
            return False
        try:
            os.stat(name, dir_fd=self._fd, follow_symlinks=False)
        except FileNotFoundError:
            return True
        except (PermissionError, OSError):
            return False
        if not self.has_owned_leaf_state(name, expected_stat, expected_sha256, allow_stage_link=allow_stage_link):
            return False
        self.unlink_leaf(name)
        return True


def _win_close_handle(h: Any, delete_on_close: bool = False) -> None:
    ctypes, wintypes, k32, _ = _win32_api()

    class FILE_DISPOSITION_INFO(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

    try:
        if delete_on_close:
            dinfo = FILE_DISPOSITION_INFO()
            dinfo.DeleteFile = 1
            if not k32.SetFileInformationByHandle(h, 4, ctypes.byref(dinfo), ctypes.sizeof(dinfo)):
                raise OSError(f"핸들 삭제 표시 실패({ctypes.get_last_error()})")
    finally:
        k32.CloseHandle(h)


def _read_pinned_bytes(path: Path, root_anchor: Optional[Path] = None) -> bytes:
    clean = assert_safe_path(Path(path), root_anchor=root_anchor)
    with PinnedDirectory(clean.parent, root_anchor=root_anchor) as pin:
        return pin.read_leaf_bytes(clean.name)


def _win_get_handle_file_id(wh: Any) -> Optional[Tuple[int, int, int]]:
    try:
        ctypes, _, k32, BY_HANDLE_FILE_INFORMATION = _win32_api()
        info = BY_HANDLE_FILE_INFORMATION()
        if not k32.GetFileInformationByHandle(wh, ctypes.byref(info)):
            return None
        return (
            int(info.dwVolumeSerialNumber),
            int(info.nFileIndexHigh),
            int(info.nFileIndexLow),
        )
    except Exception:
        return None


def _rollback_published_new_leaf(pin: PinnedDirectory, dst_path: Path, state: Dict[str, Any]) -> Optional[str]:
    leaf_name = dst_path.name
    try:
        if os.name == "nt":
            wh = state.pop("win_handle", None)
            if wh is None:
                try:
                    pin.lstat_leaf(leaf_name)
                except FileNotFoundError:
                    return None
                except Exception:
                    pass
                return f"{dst_path}: 검증된 배타 핸들이 없어 경로 기반 삭제를 중단했습니다(외부 파일 보존)"

            return pin._cleanup_win_owned_handle(
                wh,
                leaf_name,
                dst_path,
                _win_get_handle_file_id(wh),
                "신규 게시 파일이 삭제되지 않았습니다",
            )

        removed = pin.unlink_if_owned_leaf(
            leaf_name,
            state.get("published_stat"),
            state.get("published_sha256", ""),
            allow_stage_link=bool(state.get("stage_link_retained")),
        )
        if not removed:
            return f"{dst_path}: 신규 게시 파일이 외부에서 변경·교체되어 삭제를 중단했습니다(외부 파일 보존)"
        return None
    except Exception as rb_exc:
        return f"{dst_path}: {rb_exc}"


def _write_output_atomic(
    dst: Path,
    data: bytes,
    root_anchor: Optional[Path] = None,
    replace_existing: bool = True,
    out_state: Optional[Dict[str, Any]] = None,
    keep_win_handle: bool = False,
) -> None:
    clean_dst = assert_safe_path(Path(dst), root_anchor=root_anchor)
    clean_dst.parent.mkdir(parents=True, exist_ok=True)
    with PinnedDirectory(clean_dst.parent, root_anchor=root_anchor) as pin:
        tmp_name = f"{clean_dst.name}.tmp-{uuid.uuid4().hex[:12]}"
        local_state: Dict[str, Any] = out_state if out_state is not None else {}
        standalone_win_new = os.name == "nt" and out_state is None and not replace_existing
        effective_keep = bool(keep_win_handle or standalone_win_new)
        try:
            pin.publish_atomic_leaf(
                tmp_name,
                clean_dst.name,
                data,
                replace_existing=replace_existing,
                out_state=local_state,
                keep_win_handle=effective_keep,
            )
        except Exception as exc:
            if out_state is None and not replace_existing and local_state.get("published"):
                rb_err = _rollback_published_new_leaf(pin, clean_dst, local_state)
                if rb_err is not None:
                    if isinstance(exc, RuntimeError) and "정리" in str(exc):
                        raise RuntimeError(f"{exc}; 단일 출력 저장 롤백 실패(잔존 경로 확인 필요): {rb_err}") from (exc.__cause__ or exc)
                    raise RuntimeError(f"단일 출력 저장 롤백 실패(잔존 경로 확인 필요): {rb_err}") from exc
            raise
        finally:
            if out_state is None:
                wh = local_state.pop("win_handle", None)
                if wh is not None:
                    try:
                        _win_close_handle(wh, delete_on_close=False)
                    except Exception:
                        if sys.exc_info()[0] is None:
                            raise




def replace_batch_safely(
    items: Sequence[Dict[str, Any]],
    force: bool = False,
    root_anchor: Optional[Path] = None,
) -> Dict[str, Any]:
    with SAVE_IO_LOCK:
        if not force and is_game_running():
            raise RuntimeError("귀곡팔황(guigubahuang)이 실행 중입니다. 게임을 종료하거나 --force를 지정하세요.")

        prepared: List[Dict[str, Any]] = []
        seen_targets = set()
        for raw in items:
            item_anchor = raw.get("root_anchor", root_anchor)
            target = assert_safe_path(Path(raw["path"]), root_anchor=item_anchor)
            if not is_valid_cache_filename(target.name) or target.name == "CacheFixVer":
                raise ValueError(f"허용되지 않는 세이브 파일 이름입니다: {target.name}")
            key = os.path.normcase(str(target))
            if key in seen_targets:
                raise ValueError(f"중복된 저장 대상 파일이 포함되어 있습니다: {target.name}")
            seen_targets.add(key)
            prepared.append({
                "path": target,
                "data": bytes(raw["data"]),
                "expected": raw.get("expected_sha256"),
                "anchor": item_anchor,
                "must_not_exist": bool(raw.get("must_not_exist", False)),
            })

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        pins: Dict[Tuple[str, str], PinnedDirectory] = {}
        posix_releases: List[Any] = []
        win_locks: List[Any] = []
        staged: List[Dict[str, Any]] = []
        touched_list: List[Dict[str, Any]] = []
        committed: List[Dict[str, Any]] = []
        try:
            for entry in sorted(prepared, key=lambda e: os.path.normcase(str(e["path"]))):
                target = entry["path"]
                item_anchor = entry["anchor"]
                target.parent.mkdir(parents=True, exist_ok=True)
                pkey = (str(target.parent), str(item_anchor) if item_anchor is not None else "")
                if pkey not in pins:
                    pin = PinnedDirectory(target.parent, root_anchor=item_anchor)
                    pin.__enter__()
                    pins[pkey] = pin
                entry["pin"] = pins[pkey]
                if os.name == "nt":
                    if entry["pin"].exists_leaf(target.name):
                        if entry["must_not_exist"]:
                            raise FileExistsError(f"출력 대상 파일이 이미 존재합니다: {target.name}")
                        h_lock, locked_bytes = entry["pin"].open_win_locked_existing(target.name)
                        win_locks.append(h_lock)
                        entry["win_lock"] = h_lock
                        entry["win_orig_bytes"] = locked_bytes
                else:
                    posix_releases.append(entry["pin"].acquire_posix_leaf_lock(target.name))

            for entry in prepared:
                target = entry["path"]
                pin = entry["pin"]
                orig_stat = None
                win_lock_handle = entry.get("win_lock")
                if os.name == "nt":
                    if win_lock_handle is not None:
                        existed = True
                        orig_bytes = entry["win_orig_bytes"]
                        orig_hash = _sha256_bytes(orig_bytes)
                    else:
                        existed = False
                        orig_bytes = None
                        orig_hash = None
                else:
                    existed = pin.exists_leaf(target.name)
                    if existed:
                        lst = pin.lstat_leaf(target.name)
                        orig_stat = (lst.st_dev, lst.st_ino)
                        orig_bytes = pin.read_leaf_bytes(target.name)
                        orig_hash = _sha256_bytes(orig_bytes)
                    else:
                        orig_bytes = None
                        orig_hash = None

                if entry["must_not_exist"] and existed:
                    raise FileExistsError(f"출력 대상 파일이 이미 존재합니다: {target.name}")

                if entry["expected"] is not None and orig_hash != entry["expected"]:
                    raise RuntimeError(f"세이브 파일이 외부에서 변경되었습니다: {target.name}")

                tmp_name = f"{target.name}.tmp-{uuid.uuid4().hex[:12]}"
                bak_name = f"{target.name}.backup-{stamp}-{secrets.token_hex(4)}.bak"
                bak_created = False
                bak_stat = None
                bak_win_h = None
                if existed and orig_bytes is not None:
                    bak_stat, bak_win_h = pin.write_exclusive_leaf(bak_name, orig_bytes, keep_win_handle=(os.name == "nt"))
                    bak_created = True
                staged.append({
                    "pin": pin,
                    "path": target,
                    "data": entry["data"],
                    "tmp_name": tmp_name,
                    "bak_name": bak_name,
                    "bak_path": target.with_name(bak_name),
                    "existed": existed,
                    "orig_hash": orig_hash,
                    "orig_stat": orig_stat,
                    "win_lock": win_lock_handle,
                    "publish_state": {"published": False},
                    "touched": False,
                    "committed": False,
                    "restored_ok": False,
                    "must_not_exist": entry["must_not_exist"],
                    "orig_bytes": orig_bytes,
                    "bak_created": bak_created,
                    "bak_state": {"published": bak_created, "published_stat": bak_stat, "published_sha256": orig_hash or "", "stage_link_retained": False, "win_handle": bak_win_h},
                })
                if bak_created and callable(TEST_AFTER_BACKUP_CREATED_HOOK):
                    TEST_AFTER_BACKUP_CREATED_HOOK(len(staged) - 1, staged[-1]["bak_path"], staged[-1]["bak_state"])

            for idx, st in enumerate(staged):
                if callable(TEST_BEFORE_COMMIT_HOOK):
                    TEST_BEFORE_COMMIT_HOOK(idx, st["path"])
                if TEST_FAIL_AT_COMMIT_INDEX >= 0 and idx == TEST_FAIL_AT_COMMIT_INDEX:
                    raise OSError("테스트용 배치 커밋 중단")
                pin = st["pin"]
                name = st["path"].name
                if st["existed"]:
                    if os.name != "nt":
                        if not pin.exists_leaf(name):
                            raise RuntimeError(f"세이브 파일이 커밋 직전 외부에서 삭제되었습니다: {name}")
                        lst_now = pin.lstat_leaf(name)
                        if (lst_now.st_dev, lst_now.st_ino) != st["orig_stat"]:
                            raise RuntimeError(f"세이브 파일이 커밋 직전 외부에서 교체되었습니다: {name}")
                        if _sha256_bytes(pin.read_leaf_bytes(name)) != st["orig_hash"]:
                            raise RuntimeError(f"세이브 파일이 커밋 직전 외부에서 변경되었습니다: {name}")
                    if os.name == "nt" and st["win_lock"] is not None:
                        st["touched"] = True
                        touched_list.append(st)
                        pin.overwrite_win_locked_handle(st["win_lock"], st["data"], name, allow_fault=True)
                    else:
                        try:
                            pin.publish_atomic_leaf(
                                st["tmp_name"],
                                name,
                                st["data"],
                                replace_existing=True,
                                out_state=st["publish_state"],
                                allow_fault=True,
                                expected_dst_owner=(st["orig_stat"], st["orig_hash"] or ""),
                            )
                        finally:
                            if st["publish_state"].get("published"):
                                st["touched"] = True
                                touched_list.append(st)
                else:
                    if pin.exists_leaf(name):
                        if st.get("must_not_exist"):
                            raise FileExistsError(f"출력 대상 파일이 커밋 직전 외부에서 생성되었습니다: {name}")
                        raise RuntimeError(f"세이브 파일이 커밋 직전 외부에서 생성되었습니다: {name}")
                    try:
                        pin.publish_atomic_leaf(
                            st["tmp_name"],
                            name,
                            st["data"],
                            replace_existing=False,
                            out_state=st["publish_state"],
                            allow_fault=True,
                            keep_win_handle=(os.name == "nt"),
                        )
                    finally:
                        if st["publish_state"].get("published"):
                            st["touched"] = True
                            touched_list.append(st)

                st["committed"] = True
                committed.append(st)

            return {
                "written": [str(st["path"]) for st in committed],
                "backups": [str(st["bak_path"]) for st in committed if st["existed"]],
                "hashes": {str(st["path"]): _sha256_bytes(st["data"]) for st in committed},
            }
        except Exception as exc:
            rollback_errors: List[str] = []
            for st in reversed(touched_list):
                try:
                    if TEST_FAIL_ROLLBACK:
                        raise OSError("테스트용 롤백 복원 실패")
                    pin = st["pin"]
                    if st["existed"]:
                        if os.name == "nt":
                            bwh = st["bak_state"].get("win_handle")
                            if bwh is None or st.get("orig_bytes") is None:
                                raise OSError(f"복구 백업 배타 핸들 누락: {st['bak_name']}")
                            pin._win_verify_handle_sha256(bwh, len(st["orig_bytes"]), st["orig_hash"] or "", st["bak_name"])
                            bak_bytes = st["orig_bytes"]
                            if st["win_lock"] is None:
                                raise OSError(f"원본 잠금 핸들 누락: {st['path'].name}")
                            pin.overwrite_win_locked_handle(st["win_lock"], bak_bytes, st["path"].name, allow_fault=False)
                        else:
                            if not pin.has_owned_leaf_state(st["bak_name"], st["bak_state"].get("published_stat"), st["orig_hash"] or ""):
                                raise OSError(f"복구 백업 파일 누락 또는 외부 교체 감지: {st['bak_name']}")
                            bak_bytes = pin.read_leaf_bytes(st["bak_name"])
                            if _sha256_bytes(bak_bytes) != st["orig_hash"]:
                                raise OSError(f"복구 백업 파일 해시 불일치: {st['bak_name']}")
                            pub_stat = st["publish_state"].get("published_stat")
                            pub_sha = st["publish_state"].get("published_sha256", "")
                            if not pin.has_owned_leaf_state(st["path"].name, pub_stat, pub_sha):
                                raise RuntimeError(
                                    f"커밋된 세이브 파일이 외부에서 변경·교체되어 복구를 중단했습니다(외부 파일 및 .bak 보존): {st['path'].name}"
                                )
                            rb_tmp = f"{st['path'].name}.rb-{uuid.uuid4().hex[:12]}"
                            pin.publish_atomic_leaf(
                                rb_tmp,
                                st["path"].name,
                                bak_bytes,
                                replace_existing=True,
                                allow_fault=False,
                                expected_dst_owner=(pub_stat, pub_sha),
                            )
                            if _sha256_bytes(pin.read_leaf_bytes(st["path"].name)) != st["orig_hash"]:
                                raise OSError(f"복구 후 해시 불일치: {st['path'].name}")
                        st["restored_ok"] = True
                    else:
                        rb_err = _rollback_published_new_leaf(pin, st["path"], st["publish_state"])
                        if rb_err is not None:
                            raise RuntimeError(rb_err)
                        st["restored_ok"] = True

                except Exception as rb_exc:
                    rollback_errors.append(f"{st['path'].name}: {rb_exc}")

            for st in staged:
                if st.get("bak_created") and ((not st["touched"]) or bool(st["restored_ok"])):
                    bak_err = _rollback_published_new_leaf(st["pin"], st["bak_path"], st["bak_state"])
                    if bak_err is not None:
                        rollback_errors.append(bak_err)

            if rollback_errors:
                if isinstance(exc, RuntimeError) and "정리" in str(exc):
                    raise RuntimeError(
                        f"{exc}; 배치 저장 롤백 중 복원 실패(원본 .bak 보존됨): {'; '.join(rollback_errors)}"
                    ) from (exc.__cause__ or exc)
                raise RuntimeError(
                    f"배치 저장 롤백 중 복원 실패(원본 .bak 보존됨): {'; '.join(rollback_errors)}"
                ) from exc
            raise
        finally:
            for st in staged:
                wh_rem = st["publish_state"].pop("win_handle", None)
                if wh_rem is not None:
                    try:
                        _win_close_handle(wh_rem, delete_on_close=False)
                    except Exception:
                        pass
                bh_rem = st["bak_state"].pop("win_handle", None)
                if bh_rem is not None:
                    try:
                        _win_close_handle(bh_rem, delete_on_close=False)
                    except Exception:
                        pass
            for h_rem in list(win_locks):
                try:
                    _, _, k32, _ = _win32_api()
                    k32.CloseHandle(h_rem)
                except Exception:
                    pass
            for rel in reversed(posix_releases):
                try:
                    rel()
                except Exception:
                    pass
            for pin in reversed(list(pins.values())):
                pin.__exit__(None, None, None)


def _gen_sole_id(used: set) -> str:
    for _ in range(10000):
        cand = "".join(secrets.choice(_ALNUM) for _ in range(6))
        if cand not in used:
            used.add(cand)
            return cand
    n = 0
    while f"{n:06d}" in used:
        n += 1
    cand = f"{n:06d}"[-6:]
    used.add(cand)
    return cand


class SlotSession:
    def __init__(self) -> None:
        self.slot_dir: Optional[Path] = None
        self.files: Dict[str, Dict[str, Any]] = {}
        self.extra_files: List[Path] = []

    @classmethod
    def load(cls, target: Path, include_parent_global: bool = True) -> "SlotSession":
        sess = cls()
        p = assert_safe_path(Path(target))
        if p.is_file() and not p.is_dir():
            sess.slot_dir = p.parent
            role = classify_file_role(p.name)
            if role not in EDITABLE_ROLES:
                raise ValueError(f"편집 대상 세이브 파일이 아닙니다: {p.name}")
            raw = _read_pinned_bytes(p, root_anchor=p.parent)
            mode, data = decode_cache_bytes(raw, allow_plain_json=True)
            sess.files[role] = {
                "name": p.name,
                "path": p,
                "sha256": _sha256_bytes(raw),
                "mode": mode,
                "data": data,
                "dirty": False,
            }
            return sess

        if not p.is_dir():
            raise FileNotFoundError(f"세이브 경로를 찾을 수 없습니다: {p}")
        sess.slot_dir = p

        with PinnedDirectory(p, root_anchor=p) as slot_pin:
            for name in slot_pin.list_leaf_names():
                if not is_valid_cache_filename(name):
                    continue
                try:
                    st = slot_pin.lstat_leaf(name)
                except FileNotFoundError:
                    continue
                is_reg = stat.S_ISREG(st.st_mode) if os.name != "nt" else ((st.dwFileAttributes & 0x10) == 0)
                if not is_reg:
                    continue
                child = p / name
                role = classify_file_role(name)
                if role in EDITABLE_ROLES and role not in sess.files:
                    raw = slot_pin.read_leaf_bytes(name)
                    mode, data = decode_cache_bytes(raw, allow_plain_json=True)
                    sess.files[role] = {
                        "name": name,
                        "path": child,
                        "sha256": _sha256_bytes(raw),
                        "mode": mode,
                        "data": data,
                        "dirty": False,
                    }
                else:
                    sess.extra_files.append(child)

        if include_parent_global and "global" not in sess.files:
            gp_parent = p.parent
            gname = FILE_NAMES["global"]
            gp = gp_parent / gname
            with PinnedDirectory(gp_parent, root_anchor=gp_parent) as gpin:
                if gpin.exists_leaf(gname):
                    gst = gpin.lstat_leaf(gname)
                    is_reg = stat.S_ISREG(gst.st_mode) if os.name != "nt" else ((gst.dwFileAttributes & 0x10) == 0)
                    if is_reg:
                        raw = gpin.read_leaf_bytes(gname)
                        mode, data = decode_cache_bytes(raw, allow_plain_json=True)
                        sess.files["global"] = {
                            "name": gname,
                            "path": gp,
                            "sha256": _sha256_bytes(raw),
                            "mode": mode,
                            "data": data,
                            "dirty": False,
                        }

        if not sess.files:
            raise ValueError(f"편집 가능한 귀곡팔황 세이브 파일이 없습니다: {p}")
        return sess

    def resolve_player(self) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        w_data = self.files.get("world", {}).get("data") or {}
        u_data = self.files.get("unit", {}).get("data") or {}
        all_unit = u_data.get("allUnit") if isinstance(u_data, dict) else {}
        if not isinstance(all_unit, dict):
            all_unit = {}
        pid = w_data.get("playerUnitID") if isinstance(w_data, dict) else None
        if not pid or pid not in all_unit:
            pid = None
            for k, u in all_unit.items():
                if isinstance(u, dict) and isinstance(u.get("q"), dict) and isinstance(u["q"].get("qb"), list):
                    pid = k
                    break
            if pid is None and all_unit:
                pid = next(iter(all_unit.keys()))
        pu = all_unit.get(pid) if pid else None
        pq = pu.get("q") if isinstance(pu, dict) else None
        return pid, pu, pq

    def sync_header(self) -> bool:
        h_info = self.files.get("header")
        if not h_info or not isinstance(h_info.get("data"), dict):
            return False
        hd = h_info["data"]
        _, _, pq = self.resolve_player()
        wd = self.files.get("world", {}).get("data")
        changed = False
        if isinstance(pq, dict):
            if isinstance(pq.get("q"), list):
                full_name = "".join(str(x) for x in pq["q"])
                if hd.get("name") != full_name:
                    hd["name"] = full_name
                    changed = True
            if "d" in pq and hd.get("gradeID") != pq["d"]:
                hd["gradeID"] = pq["d"]
                changed = True
        if isinstance(wd, dict):
            if "worldDay" in wd and hd.get("worldDay") != wd["worldDay"]:
                hd["worldDay"] = wd["worldDay"]
                changed = True
            if "gameLevel" in wd and hd.get("gameLevel") != wd["gameLevel"]:
                hd["gameLevel"] = wd["gameLevel"]
                changed = True
        if changed:
            h_info["dirty"] = True
        return changed

    def _used_sole_ids(self, pu: Dict[str, Any]) -> set:
        used = set()
        for p in pu.get("z", {}).get("allProps", []) or []:
            if isinstance(p, dict) and p.get("q") is not None:
                used.add(str(p["q"]))
        for k in (pu.get("k") or {}).keys():
            used.add(str(k))
        return used

    def get_currency(self, item_id: int) -> int:
        _, pu, _ = self.resolve_player()
        if not pu:
            return 0
        total = 0
        for p in pu.get("z", {}).get("allProps", []) or []:
            w = p.get("w") if isinstance(p, dict) else None
            if isinstance(w, list) and len(w) >= 3 and int(w[1]) == int(item_id):
                total += int(w[2])
        return total

    def set_currency(self, item_id: int, count: int) -> None:
        _, pu, _ = self.resolve_player()
        if not pu:
            raise ValueError("플레이어 유닛 데이터(DataUnit)가 로드되지 않았습니다.")
        c = max(0, min(999_999_999, int(count)))
        iid = int(item_id)
        props = pu.setdefault("z", {}).setdefault("allProps", [])
        used = self._used_sole_ids(pu)
        matches = [
            idx for idx, p in enumerate(props)
            if isinstance(p, dict) and isinstance(p.get("w"), list) and len(p["w"]) >= 3 and int(p["w"][1]) == iid
        ]
        if c == 0:
            for idx in reversed(matches):
                props.pop(idx)
        elif matches:
            first = props[matches[0]]
            first["w"][1] = iid
            first["w"][2] = c
            for idx in reversed(matches[1:]):
                props.pop(idx)
        else:
            props.append({"q": _gen_sole_id(used), "w": [1, iid, c], "e": ""})
        self.files["unit"]["dirty"] = True

    def add_item(self, item_id: int, count: int) -> None:
        _, pu, _ = self.resolve_player()
        if not pu:
            raise ValueError("플레이어 유닛 데이터(DataUnit)가 로드되지 않았습니다.")
        iid = int(item_id)
        c = max(1, min(999_999_999, int(count)))
        props = pu.setdefault("z", {}).setdefault("allProps", [])
        used = self._used_sole_ids(pu)
        for p in props:
            w = p.get("w") if isinstance(p, dict) else None
            if isinstance(w, list) and len(w) == 3 and int(w[1]) == iid:
                w[2] = min(999_999_999, int(w[2]) + c)
                self.files["unit"]["dirty"] = True
                return
        props.append({"q": _gen_sole_id(used), "w": [1, iid, c], "e": ""})
        self.files["unit"]["dirty"] = True

    def set_identity(
        self,
        surname: Optional[str] = None,
        given_name: Optional[str] = None,
        grade: Optional[int] = None,
        exp: Optional[int] = None,
        world_day: Optional[int] = None,
        difficulty: Optional[int] = None,
    ) -> None:
        _, _, pq = self.resolve_player()
        if pq is not None:
            if surname is not None or given_name is not None:
                cur = pq.get("q") if isinstance(pq.get("q"), list) and len(pq["q"]) >= 2 else ["", ""]
                pq["q"] = [
                    str(surname) if surname is not None else str(cur[0]),
                    str(given_name) if given_name is not None else str(cur[1]),
                ]
                self.files["unit"]["dirty"] = True
            if grade is not None:
                pq["d"] = max(1, min(44, int(grade)))
                self.files["unit"]["dirty"] = True
            if exp is not None:
                pq["s"] = max(0, min(999_999_999, int(exp)))
                self.files["unit"]["dirty"] = True
        if "world" in self.files and isinstance(self.files["world"]["data"], dict):
            wd = self.files["world"]["data"]
            if world_day is not None:
                wd["worldDay"] = max(0, min(3_600_000, int(world_day)))
                self.files["world"]["dirty"] = True
            if difficulty is not None:
                wd["gameLevel"] = max(1, min(5, int(difficulty)))
                self.files["world"]["dirty"] = True
        self.sync_header()

    def set_prop(self, key: str, val: int) -> None:
        _, _, pq = self.resolve_player()
        if pq is None:
            raise ValueError("플레이어 속성 데이터(pq)가 없습니다.")
        pq[str(key)] = int(val)
        self.files["unit"]["dirty"] = True
        if key == "d":
            self.sync_header()

    def max_martials(self) -> int:
        _, pu, _ = self.resolve_player()
        if not pu or not isinstance(pu.get("k"), dict):
            return 0
        count = 0
        for entry in pu["k"].values():
            if not isinstance(entry, dict):
                continue
            q = entry.get("q")
            w = q.get("w") if isinstance(q, dict) else None
            if isinstance(w, list) and len(w) >= 7:
                if int(w[5] or 0) < 1:
                    w[5] = 1
                w[6] = 6
                entry["w"] = max(int(entry.get("w") or 0), 999_999)
                count += 1
        if count > 0:
            self.files["unit"]["dirty"] = True
        return count

    def update_sect(self, **kw: int) -> bool:
        _, pu, _ = self.resolve_player()
        s_info = self.files.get("school")
        if not pu or not s_info or not isinstance(s_info.get("data"), dict):
            return False
        school_id = str(pu.get("u") or "")
        sc = (s_info["data"].get("allBuild") or {}).get(school_id)
        if not isinstance(sc, dict):
            return False
        pd = sc.setdefault("propertyData", {})
        for k, v in kw.items():
            iv = max(0, min(999_999_999, int(v)))
            if k in ("money", "reputation", "totalMember"):
                sc[k] = iv
            elif k == "loyal":
                pd["loyal"] = iv
                pd["Loyal"] = iv
            else:
                pd[k] = iv
        s_info["dirty"] = True
        return True

    def unlock_achievements(self) -> int:
        g_info = self.files.get("global")
        if not g_info or not isinstance(g_info.get("data"), dict):
            return 0
        ach = g_info["data"].setdefault("achievement", {}).setdefault("allAchievement", {})
        if not isinstance(ach, dict):
            return 0
        for v in ach.values():
            if isinstance(v, dict):
                v["achieved"] = True
                v["count"] = max(1, int(v.get("count") or 1))
        g_info["dirty"] = True
        return len(ach)

    def apply_preset(self, preset_id: str) -> None:
        if preset_id not in PRESET_IDS:
            raise ValueError(f"알 수 없는 프리셋 ID입니다: {preset_id}")
        _, pu, pq = self.resolve_player()
        if preset_id == "rich-cultivator":
            self.set_currency(10001, 9_999_999)
            self.set_currency(10011, 999_999)
            self.set_currency(10041, 9_999)
        elif preset_id == "full-recovery":
            if pq is not None:
                for cur_k, max_k, min_v in (
                    ("x", "c", 1000),
                    ("v", "b", 1000),
                    ("n", "m", 1000),
                    ("l", "z", 500),
                    ("5", "6", 500),
                    ("qx", "qc", 500),
                ):
                    mx = max(int(pq.get(max_k) or 0), min_v)
                    pq[max_k] = mx
                    pq[cur_k] = mx
                if pu and isinstance(pu.get("qe"), dict):
                    pu["qe"]["o"] = False
                self.files["unit"]["dirty"] = True
        elif preset_id == "omni-aptitude":
            for k in ROOT_KEYS + WEAPON_KEYS + ARTISAN_KEYS:
                self.set_prop(k, 999)
        elif preset_id == "immortal-stat":
            if pq is not None:
                self.set_prop("u", 119_988)
                self.set_prop("k", 999)
                self.set_prop("i", 999)
                self.set_prop("j", 99_999)
                self.set_prop("c", max(int(pq.get("c") or 0), 9_999_999))
                self.set_prop("x", max(int(pq.get("x") or 0), 9_999_999))
                self.set_prop("1", max(int(pq.get("1") or 0), 999_999))
                self.set_prop("2", max(int(pq.get("2") or 0), 999_999))
        elif preset_id == "martial-perfection":
            self.max_martials()
        elif preset_id == "sect-prosperity":
            self.update_sect(
                money=9_999_999,
                reputation=999_999,
                prosperous=99_999,
                prosperousMax=99_999,
                loyal=1_000,
                medicina=999_999,
                mine=999_999,
                largeArrayHP=999_999,
                largeArrayHPMax=999_999,
            )

    def summary(self) -> Dict[str, Any]:
        pid, pu, pq = self.resolve_player()
        hd = self.files.get("header", {}).get("data") or {}
        wd = self.files.get("world", {}).get("data") or {}
        q = pq or {}
        name_arr = q.get("q") if isinstance(q.get("q"), list) else []
        full_name = "".join(str(x) for x in name_arr) if name_arr else str(hd.get("name") or "")
        wday = int(wd.get("worldDay") if "worldDay" in wd else (hd.get("worldDay") or 0))
        return {
            "slot": str(self.slot_dir) if self.slot_dir else None,
            "rolesLoaded": sorted(self.files.keys()),
            "playerUnitID": pid,
            "name": full_name,
            "gradeID": int(q.get("d") if "d" in q else (hd.get("gradeID") or 0)),
            "exp": int(q.get("s") or 0),
            "worldDay": wday,
            "calendar": {"year": wday // 360 + 1, "month": (wday % 360) // 30 + 1, "day": (wday % 30) + 1},
            "gameLevel": int(wd.get("gameLevel") if "gameLevel" in wd else (hd.get("gameLevel") or 0)),
            "createTicks": hd.get("createTicks"),
            "spiritStones": self.get_currency(10001),
            "sectContrib": self.get_currency(10011),
            "cityTokens": self.get_currency(10041),
            "schoolID": str(pu.get("u") or "") if pu else "",
            "dirtyRoles": sorted(r for r, info in self.files.items() if info.get("dirty")),
        }

    def validate(self) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        pid, _, pq = self.resolve_player()
        hd = self.files.get("header", {}).get("data")
        wd = self.files.get("world", {}).get("data")
        if "unit" in self.files and not pid:
            errors.append("DataUnit에서 플레이어 유닛(playerUnitID)을 찾을 수 없습니다.")
        if isinstance(pq, dict):
            if not isinstance(pq.get("q"), list) or len(pq["q"]) < 2:
                errors.append("플레이어 성명 배열(pq.q) 형식이 올바르지 않습니다.")
            if not (1 <= int(pq.get("d") or 0) <= 44):
                warnings.append(f"경지 ID(pq.d={pq.get('d')})가 기본 범위(1~44) 밖입니다.")
        if isinstance(hd, dict) and isinstance(pq, dict):
            full_name = "".join(str(x) for x in (pq.get("q") or []))
            if hd.get("name") != full_name:
                warnings.append("CacheData.name과 DataUnit 플레이어 성명이 불일치합니다.")
            if hd.get("gradeID") != pq.get("d"):
                warnings.append("CacheData.gradeID와 DataUnit 플레이어 경지가 불일치합니다.")
        if isinstance(hd, dict) and isinstance(wd, dict):
            if hd.get("worldDay") != wd.get("worldDay"):
                warnings.append("CacheData.worldDay와 DataWorld.worldDay가 불일치합니다.")
            if hd.get("gameLevel") != wd.get("gameLevel"):
                warnings.append("CacheData.gameLevel과 DataWorld.gameLevel이 불일치합니다.")
        return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}

    def save(self, output_dir: Optional[Path] = None, force: bool = False) -> Dict[str, Any]:
        if any(self.files.get(r, {}).get("dirty") for r in ("header", "world", "unit")):
            self.sync_header()

        in_place = output_dir is None or (
            self.slot_dir is not None and Path(os.path.abspath(str(output_dir))) == self.slot_dir
        )

        dirty_names = {info["name"] for info in self.files.values() if info.get("dirty")}
        out_root: Optional[Path] = None
        copied_untouched: List[Tuple[str, Dict[str, Any]]] = []
        try:
            if not in_place:
                out_root = assert_safe_path(Path(output_dir))
                if out_root.exists():
                    with PinnedDirectory(out_root, root_anchor=out_root) as out_pin:
                        if out_pin.list_leaf_names():
                            raise ValueError("출력 폴더가 비어 있지 않습니다. 다른 슬롯과의 데이터 혼합을 막기 위해 새 폴더나 빈 폴더를 지정하세요.")
                out_root.mkdir(parents=True, exist_ok=True)
                if self.slot_dir and self.slot_dir.is_dir():
                    with PinnedDirectory(self.slot_dir, root_anchor=self.slot_dir) as src_pin:
                        for name in src_pin.list_leaf_names():
                            if name in dirty_names or not is_valid_cache_filename(name):
                                continue
                            try:
                                st = src_pin.lstat_leaf(name)
                            except FileNotFoundError:
                                continue
                            is_reg = stat.S_ISREG(st.st_mode) if os.name != "nt" else ((st.dwFileAttributes & 0x10) == 0)
                            if is_reg:
                                raw_copy = src_pin.read_leaf_bytes(name)
                                cstate: Dict[str, Any] = {}
                                try:
                                    _write_output_atomic(
                                        out_root / name,
                                        raw_copy,
                                        root_anchor=out_root,
                                        replace_existing=False,
                                        out_state=cstate,
                                        keep_win_handle=(os.name == "nt"),
                                    )
                                finally:
                                    if cstate.get("published"):
                                        copied_untouched.append((name, cstate))
                if callable(TEST_AFTER_UNTOUCHED_COPY_HOOK):
                    TEST_AFTER_UNTOUCHED_COPY_HOOK(out_root)

            batch: List[Dict[str, Any]] = []
            for role, info in self.files.items():
                if not info.get("dirty"):
                    continue
                encoded = encode_cache_data(info["data"], mode=info["mode"], indent=None)
                if in_place:
                    target_path = info["path"]
                    expected = info["sha256"]
                    anchor = self.slot_dir if (self.slot_dir and target_path.parent == self.slot_dir) else target_path.parent
                else:
                    assert out_root is not None
                    target_path = out_root / info["name"]
                    expected = None
                    anchor = out_root
                batch.append({
                    "path": target_path,
                    "data": encoded,
                    "expected_sha256": expected,
                    "root_anchor": anchor,
                    "must_not_exist": not in_place,
                })

            if not batch:
                return {"written": [], "backups": []}

            res = replace_batch_safely(batch, force=force)
        except Exception as exc:
            copy_rb_errors: List[str] = []
            if not in_place and out_root is not None and copied_untouched:
                try:
                    with PinnedDirectory(out_root, root_anchor=out_root) as out_pin:
                        for name, cstate in reversed(copied_untouched):
                            err_msg = _rollback_published_new_leaf(out_pin, out_root / name, cstate)
                            if err_msg is not None:
                                copy_rb_errors.append(err_msg)
                except Exception as pin_exc:
                    for name, cstate in reversed(copied_untouched):
                        wh = cstate.pop("win_handle", None)
                        if wh is None:
                            copy_rb_errors.append(
                                f"{out_root / name}: 검증된 배타 핸들이 없어 경로 기반 삭제를 중단했습니다({pin_exc})"
                            )
                            continue
                        try:
                            _win_close_handle(wh, delete_on_close=True)
                        except Exception as h_exc:
                            copy_rb_errors.append(f"{out_root / name}: {h_exc}")
            if copy_rb_errors:
                joined = "; ".join(copy_rb_errors)
                if isinstance(exc, RuntimeError) and ("롤백" in str(exc) or "정리" in str(exc)):
                    raise RuntimeError(f"{exc}; 비편집 복사본 롤백 실패: {joined}") from (exc.__cause__ or exc)
                else:
                    raise RuntimeError(f"출력 슬롯 저장 롤백 실패(잔존 경로 확인 필요): {joined}") from exc
            raise
        finally:
            for _, cstate in copied_untouched:
                wh = cstate.pop("win_handle", None)
                if wh is not None:
                    try:
                        _win_close_handle(wh, delete_on_close=False)
                    except Exception:
                        pass
        if in_place:
            hashes_map = res.get("hashes", {})
            for role, info in self.files.items():
                if info.get("dirty"):
                    info["sha256"] = hashes_map.get(str(info["path"]), info["sha256"])
                    info["dirty"] = False
        return res


def _load_or_bundle_html(html_path: Optional[str]) -> str:
    if html_path:
        return _read_pinned_bytes(Path(html_path)).decode("utf-8")
    dist_html = SCRIPT_DIR / "dist" / "TaleOfImmortalSaveEditor-v1.0.html"
    if dist_html.is_file():
        return _read_pinned_bytes(dist_html, root_anchor=SCRIPT_DIR).decode("utf-8")
    page_path = SCRIPT_DIR / "src" / "editor-page.html"
    page = _read_pinned_bytes(page_path, root_anchor=SCRIPT_DIR).decode("utf-8")
    blocks = []
    for js_name in ("catalog-data.js", "cache-codec.js", "editor-core.js", "editor-ui.js"):
        code = _read_pinned_bytes(SCRIPT_DIR / "src" / js_name, root_anchor=SCRIPT_DIR).decode("utf-8")
        code = re.sub(r"(?i)</(script)", lambda m: "<\\/" + m.group(1), code)
        blocks.append(f"<script>\n{code}\n</script>")
    start = "<!-- BUNDLE_SCRIPTS_START -->"
    end = "<!-- BUNDLE_SCRIPTS_END -->"
    head, _, rest = page.partition(start)
    _, _, tail = rest.partition(end)
    return head + "\n".join(blocks) + tail


def _validate_slot_cache_bytes(name: str, raw: bytes) -> None:
    if name == FILE_NAMES["fixVer"]:
        if len(raw) == 0 or len(raw) > 64:
            raise ValueError("유효하지 않은 CacheFixVer 크기입니다.")
        try:
            txt = raw.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("유효하지 않은 CacheFixVer 인코딩입니다.") from exc
        if not txt or not all(32 <= ord(ch) <= 126 for ch in txt):
            raise ValueError("유효하지 않은 CacheFixVer 내용입니다.")
        return
    _, parsed_obj = decode_cache_bytes(raw, allow_plain_json=True)
    if not isinstance(parsed_obj, (dict, list)):
        raise ValueError(f"유효하지 않은 세이브 캐시 데이터입니다: {name}")


def _is_slot_dir(d: Path, root_anchor: Optional[Path] = None) -> bool:
    if _is_reparse_or_link(d) or not d.is_dir():
        return False
    try:
        with PinnedDirectory(d, root_anchor=root_anchor) as pin:
            names: List[str] = []
            for n in pin.list_leaf_names():
                if not is_valid_cache_filename(n):
                    continue
                try:
                    st = pin.lstat_leaf(n)
                except (FileNotFoundError, PermissionError):
                    continue
                is_reg = stat.S_ISREG(st.st_mode) if os.name != "nt" else ((st.dwFileAttributes & 0x10) == 0)
                if is_reg:
                    names.append(n)
    except (OSError, PermissionError):
        return False
    return "CacheData" in names or any(
        n != "DataGloble.cache" and n.lower().endswith(".cache")
        for n in names
    )


def create_http_server(
    save_dir: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    html_path: Optional[str] = None,
    allow_remote: bool = False,
):
    if host not in LOOPBACK_HOSTS and not allow_remote:
        raise ValueError(f"원격 바인딩은 --allow-remote 옵션 없이는 허용되지 않습니다: {host}")

    root = assert_safe_path(Path(save_dir) if save_dir else Path.cwd())
    csrf_token = secrets.token_hex(16)
    base_html = _load_or_bundle_html(html_path)
    cfg_script = f'<script>window.__TOI_SERVER_CONFIG__ = {json.dumps({"token": csrf_token})};</script>\n'
    if "</head>" in base_html:
        served_html = base_html.replace("</head>", cfg_script + "</head>", 1).encode("utf-8")
    else:
        served_html = (cfg_script + base_html).encode("utf-8")

    sessions: Dict[str, Dict[str, Any]] = {}
    sessions_lock = threading.RLock()

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "TaleOfImmortalEditor/1.0"

        def log_message(self, fmt: str, *a: Any) -> None:
            return

        def _send(self, status: int, ctype: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Vary", "Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site, Origin, Host")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            self._send(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def _guard(self, is_api: bool, is_post: bool) -> bool:
            actual_port = self.server.server_address[1]
            if not allow_remote:
                raw_host = (self.headers.get("Host") or "").strip().lower()
                allowed_hosts = {
                    "127.0.0.1",
                    f"127.0.0.1:{actual_port}",
                    "localhost",
                    f"localhost:{actual_port}",
                    "[::1]",
                    f"[::1]:{actual_port}",
                }
                if raw_host not in allowed_hosts:
                    self._json(403, {"ok": False, "error": "허용되지 않는 Host 헤더입니다."})
                    return False

                sec_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                if sec_site:
                    if is_api or is_post:
                        if sec_site not in ("same-origin", "none"):
                            self._json(403, {"ok": False, "error": "교차 사이트 요청이 차단되었습니다."})
                            return False
                    else:
                        sec_mode = (self.headers.get("Sec-Fetch-Mode") or "").strip().lower()
                        if sec_site == "cross-site" and sec_mode != "navigate":
                            self._json(403, {"ok": False, "error": "교차 사이트 탐색이 차단되었습니다."})
                            return False

            if is_post:
                ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if ctype != "application/json":
                    self._json(415, {"ok": False, "error": "Content-Type은 application/json이어야 합니다."})
                    return False

                if not allow_remote:
                    origin = (self.headers.get("Origin") or "").strip().lower()
                    if origin:
                        allowed_origins = {
                            f"http://127.0.0.1:{actual_port}",
                            f"http://localhost:{actual_port}",
                            f"http://[::1]:{actual_port}",
                        }
                        if origin not in allowed_origins:
                            self._json(403, {"ok": False, "error": "허용되지 않는 Origin 헤더입니다."})
                            return False

            if is_api:
                tok = (self.headers.get("X-Toi-Token") or "").strip()
                if not tok or not secrets.compare_digest(tok, csrf_token):
                    self._json(403, {"ok": False, "error": "유효하지 않은 보안 토큰(X-Toi-Token)입니다."})
                    return False

            return True

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            is_api = parsed.path.startswith("/api/")
            if not self._guard(is_api=is_api, is_post=False):
                return
            if parsed.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", served_html)
                return
            if parsed.path == "/api/slots":
                slots: List[Dict[str, str]] = []
                if _is_slot_dir(root, root_anchor=root):
                    slots.append({"slot": ".", "label": root.name})
                if root.is_dir():
                    try:
                        with PinnedDirectory(root, root_anchor=root) as rpin:
                            sub_names = rpin.list_leaf_names()
                    except (OSError, PermissionError):
                        sub_names = []
                    for sub_name in sub_names:
                        if sub_name == "cacheSimple" or sub_name.startswith("."):
                            continue
                        sub = root / sub_name
                        if _is_reparse_or_link(sub):
                            continue
                        if _is_slot_dir(sub, root_anchor=root):
                            slots.append({"slot": sub_name, "label": sub_name})
                self._json(200, {"ok": True, "slots": slots})
                return
            self._json(404, {"ok": False, "error": "알 수 없는 경로입니다."})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if not self._guard(is_api=True, is_post=True):
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                if length < 0 or length > 128 * 1024 * 1024:
                    raise ValueError("잘못된 요청 크기")
                req = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
                if not isinstance(req, dict):
                    raise ValueError("객체 본문 필요")
            except Exception:
                self._json(400, {"ok": False, "error": "JSON 본문이 올바르지 않습니다."})
                return

            if parsed.path == "/api/load-slot":
                slot_name = str(req.get("slot") or "")
                if not slot_name:
                    self._json(400, {"ok": False, "error": "슬롯 이름이 필요합니다."})
                    return
                if slot_name == ".":
                    slot_dir = root
                else:
                    if "/" in slot_name or "\\" in slot_name or ".." in slot_name or ":" in slot_name:
                        self._json(400, {"ok": False, "error": "허용되지 않는 슬롯 이름입니다."})
                        return
                    slot_dir = root / slot_name
                try:
                    slot_clean = assert_safe_path(slot_dir, root_anchor=root)
                    files_out: List[Dict[str, str]] = []
                    paths_by_key: Dict[str, Path] = {}
                    hashes_by_path: Dict[Path, str] = {}
                    anchors_by_path: Dict[Path, Optional[Path]] = {}
                    has_global = False
                    has_slot_marker = False
                    with PinnedDirectory(slot_clean, root_anchor=root) as slot_pin:
                        for name in slot_pin.list_leaf_names():
                            if not is_valid_cache_filename(name):
                                continue
                            try:
                                st = slot_pin.lstat_leaf(name)
                            except FileNotFoundError:
                                continue
                            is_reg = stat.S_ISREG(st.st_mode) if os.name != "nt" else ((st.dwFileAttributes & 0x10) == 0)
                            if not is_reg:
                                continue
                            raw = slot_pin.read_leaf_bytes(name)
                            _validate_slot_cache_bytes(name, raw)
                            child = slot_clean / name
                            files_out.append({
                                "name": name,
                                "relativePath": name,
                                "base64": base64.b64encode(raw).decode("ascii"),
                            })
                            paths_by_key[name] = child
                            hashes_by_path[child] = _sha256_bytes(raw)
                            anchors_by_path[child] = root
                            if name == FILE_NAMES["global"]:
                                has_global = True
                            if name == "CacheData" or (name != "DataGloble.cache" and name.lower().endswith(".cache")):
                                has_slot_marker = True
                    if not has_slot_marker:
                        self._json(404, {"ok": False, "error": "유효한 세이브 슬롯 폴더를 찾을 수 없습니다."})
                        return
                    if not has_global and slot_clean != root:
                        gname = FILE_NAMES["global"]
                        gp_parent = assert_safe_path(slot_clean.parent, root_anchor=root)
                        gp = gp_parent / gname
                        with PinnedDirectory(gp_parent, root_anchor=root) as gpin:
                            if gpin.exists_leaf(gname):
                                gst = gpin.lstat_leaf(gname)
                                is_reg = stat.S_ISREG(gst.st_mode) if os.name != "nt" else ((gst.dwFileAttributes & 0x10) == 0)
                                if is_reg:
                                    graw = gpin.read_leaf_bytes(gname)
                                    _validate_slot_cache_bytes(gname, graw)
                                    rel = "parent/" + gname
                                    files_out.append({
                                        "name": gname,
                                        "relativePath": rel,
                                        "base64": base64.b64encode(graw).decode("ascii"),
                                    })
                                    paths_by_key[rel] = gp
                                    paths_by_key[gname] = gp
                                    hashes_by_path[gp] = _sha256_bytes(graw)
                                    anchors_by_path[gp] = root
                    sid = secrets.token_hex(16)
                    with sessions_lock:
                        sessions[sid] = {"paths": paths_by_key, "hashes": hashes_by_path, "anchors": anchors_by_path}
                    self._json(200, {"ok": True, "session": sid, "label": slot_clean.name, "files": files_out})
                except PermissionError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                except Exception as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                return

            if parsed.path == "/api/save-slot":
                sid = str(req.get("session") or "")
                raw_files = req.get("files")
                if not isinstance(raw_files, list) or not raw_files:
                    self._json(400, {"ok": False, "error": "저장할 파일 목록이 비어 있습니다."})
                    return
                with sessions_lock, SAVE_IO_LOCK:
                    sess = sessions.get(sid)
                    if not sess:
                        self._json(409, {"ok": False, "error": "열린 세이브 세션이 만료되었거나 일치하지 않습니다."})
                        return
                    batch: List[Dict[str, Any]] = []
                    seen_targets = set()
                    try:
                        for item in raw_files:
                            if not isinstance(item, dict):
                                raise ValueError("잘못된 파일 항목")
                            key = str(item.get("relativePath") or item.get("name") or "")
                            target = sess["paths"].get(key) or sess["paths"].get(str(item.get("name") or ""))
                            if target is None:
                                raise PermissionError(f"세션에 등록되지 않은 파일입니다: {key}")
                            norm_target = os.path.normcase(str(target))
                            if norm_target in seen_targets:
                                raise ValueError(f"중복된 저장 대상 파일이 포함되어 있습니다: {key}")
                            seen_targets.add(norm_target)
                            data = base64.b64decode(str(item.get("base64") or ""), validate=True)
                            batch.append({
                                "path": target,
                                "data": data,
                                "expected_sha256": sess["hashes"].get(target),
                                "root_anchor": sess["anchors"].get(target, root),
                            })
                        res = replace_batch_safely(batch, force=bool(req.get("force")))
                    except (binascii.Error, ValueError) as exc:
                        self._json(400, {"ok": False, "error": f"잘못된 요청 데이터: {exc}"})
                        return
                    except PermissionError as exc:
                        self._json(400, {"ok": False, "error": str(exc)})
                        return
                    except RuntimeError as exc:
                        self._json(409, {"ok": False, "error": str(exc)})
                        return
                    except OSError as exc:
                        self._json(500, {"ok": False, "error": str(exc)})
                        return

                    committed_hashes = res.get("hashes", {})
                    for b in batch:
                        tpath = b["path"]
                        if str(tpath) in committed_hashes:
                            sess["hashes"][tpath] = committed_hashes[str(tpath)]
                    new_sid = secrets.token_hex(16)
                    sessions[new_sid] = sess
                    sessions.pop(sid, None)
                self._json(200, {"ok": True, "session": new_sid, "backups": res["backups"], "written": res["written"]})
                return

            self._json(404, {"ok": False, "error": "알 수 없는 API 경로입니다."})

    class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    srv = ThreadedServer((host, port), Handler)
    srv.csrf_token = csrf_token  # type: ignore[attr-defined]
    return srv


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tale_of_immortal_editor.py",
        description="귀곡팔황 (Tale of Immortal) 세이브 에디터 v1.0 CLI 및 로컬 서버",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_ins = sub.add_parser("inspect", help="세이브 슬롯 요약 조회")
    p_ins.add_argument("target")
    p_ins.add_argument("--json", action="store_true")

    p_val = sub.add_parser("validate", help="세이브 슬롯 무결성 및 동기화 검증")
    p_val.add_argument("target")
    p_val.add_argument("--json", action="store_true")

    p_dec = sub.add_parser("decrypt", help="암호화 .cache/CacheData 파일을 UTF-8 JSON으로 복호화")
    p_dec.add_argument("input_file")
    p_dec.add_argument("-o", "--output", required=True)
    p_dec.add_argument("--pretty", action="store_true")

    p_enc = sub.add_parser("encrypt", help="UTF-8 JSON 파일을 귀곡팔황 암호화 캐시로 인코딩")
    p_enc.add_argument("input_json")
    p_enc.add_argument("-o", "--output", required=True)

    p_pre = sub.add_parser("presets", help="원클릭 프리셋 목록 출력")
    p_pre.add_argument("--json", action="store_true")

    p_edt = sub.add_parser("edit", help="세이브 슬롯 편집 및 자동 백업 저장")
    p_edt.add_argument("slot_dir")
    p_edt.add_argument("-o", "--output", default=None)
    p_edt.add_argument("--force", "--ignore-running-game", dest="force", action="store_true")
    p_edt.add_argument("--json", action="store_true")
    p_edt.add_argument("--preset", action="append", default=[])
    p_edt.add_argument("--spirit-stones", type=int, default=None)
    p_edt.add_argument("--contrib", type=int, default=None)
    p_edt.add_argument("--city-tokens", type=int, default=None)
    p_edt.add_argument("--surname", default=None)
    p_edt.add_argument("--given-name", default=None)
    p_edt.add_argument("--grade", type=int, default=None)
    p_edt.add_argument("--exp", type=int, default=None)
    p_edt.add_argument("--world-day", type=int, default=None)
    p_edt.add_argument("--difficulty", type=int, default=None)
    p_edt.add_argument("--set-prop", action="append", default=[])
    p_edt.add_argument("--add-item", action="append", default=[])
    p_edt.add_argument("--max-martials", action="store_true")
    p_edt.add_argument("--unlock-achievements", action="store_true")

    p_srv = sub.add_parser("serve", help="로컬 루프백 웹 편집기 실행")
    p_srv.add_argument("--save-dir", default=None)
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8765)
    p_srv.add_argument("--html", default=None)
    p_srv.add_argument("--allow-remote", action="store_true")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "inspect":
            sess = SlotSession.load(Path(args.target))
            rep = sess.summary()
            if args.json:
                print(json.dumps(rep, ensure_ascii=False, indent=2))
            else:
                for k, v in rep.items():
                    print(f"{k}: {v}")
            return 0

        if args.command == "validate":
            sess = SlotSession.load(Path(args.target))
            rep = sess.validate()
            if args.json:
                print(json.dumps(rep, ensure_ascii=False, indent=2))
            else:
                print("검증 통과" if rep["ok"] else "검증 실패")
                for e in rep["errors"]:
                    print(f"  [오류] {e}")
                for w in rep["warnings"]:
                    print(f"  [경고] {w}")
            return 0 if rep["ok"] else 2

        if args.command == "decrypt":
            src = assert_safe_path(Path(args.input_file))
            dst = assert_safe_path(Path(args.output))
            if dst.exists() and os.path.samefile(str(src), str(dst)):
                raise ValueError("입력 파일과 출력 파일 경로가 동일할 수 없습니다.")
            if is_valid_cache_filename(dst.name):
                raise ValueError("복호화 출력 파일 이름으로 캐시 파일 이름을 사용할 수 없습니다.")
            if _is_slot_dir(dst.parent):
                raise ValueError("슬롯 디렉터리에는 복호화 출력 파일을 생성할 수 없습니다.")
            if dst.exists():
                raise FileExistsError(f"출력 파일이 이미 존재합니다: {dst}")
            _, data = decode_cache_bytes(_read_pinned_bytes(src, root_anchor=src.parent), allow_plain_json=True)
            out_bytes = encode_cache_data(data, mode="plain-json", indent=2 if args.pretty else None)
            _write_output_atomic(dst, out_bytes, replace_existing=False)
            return 0

        if args.command == "encrypt":
            src = assert_safe_path(Path(args.input_json))
            dst = assert_safe_path(Path(args.output))
            if dst.exists() and os.path.samefile(str(src), str(dst)):
                raise ValueError("입력 파일과 출력 파일 경로가 동일할 수 없습니다.")
            if dst.name == FILE_NAMES["fixVer"]:
                raise ValueError("암호화 출력 파일 이름으로 fixVer 파일 이름을 사용할 수 없습니다.")
            if _is_slot_dir(dst.parent):
                raise ValueError("슬롯 디렉터리에는 암호화 출력 파일을 생성할 수 없습니다.")
            if dst.exists():
                raise FileExistsError(f"출력 파일이 이미 존재합니다: {dst}")
            if is_valid_cache_filename(dst.name) and is_game_running():
                raise RuntimeError("게임 실행 중에는 캐시 파일을 덮어쓸 수 없습니다.")
            _, data = decode_cache_bytes(_read_pinned_bytes(src, root_anchor=src.parent), allow_plain_json=True)
            out_bytes = encode_cache_data(data, mode="cipher-gzip", indent=None)
            _write_output_atomic(dst, out_bytes, replace_existing=False)
            return 0

        if args.command == "presets":
            if args.json:
                print(json.dumps(PRESETS, ensure_ascii=False, indent=2))
            else:
                for p in PRESETS:
                    print(f"{p['id']:22s} {p['kr']} — {p['desc']}")
            return 0

        if args.command == "edit":
            sess = SlotSession.load(Path(args.slot_dir))
            for pid in args.preset or []:
                sess.apply_preset(pid)
            if args.spirit_stones is not None:
                sess.set_currency(10001, args.spirit_stones)
            if args.contrib is not None:
                sess.set_currency(10011, args.contrib)
            if args.city_tokens is not None:
                sess.set_currency(10041, args.city_tokens)
            if any(x is not None for x in (args.surname, args.given_name, args.grade, args.exp, args.world_day, args.difficulty)):
                sess.set_identity(
                    surname=args.surname,
                    given_name=args.given_name,
                    grade=args.grade,
                    exp=args.exp,
                    world_day=args.world_day,
                    difficulty=args.difficulty,
                )
            for kv in args.set_prop or []:
                if "=" not in kv:
                    raise ValueError(f"--set-prop 형식은 KEY=INT여야 합니다: {kv}")
                k, _, v = kv.partition("=")
                sess.set_prop(k.strip(), int(v))
            for spec in args.add_item or []:
                if ":" not in spec:
                    raise ValueError(f"--add-item 형식은 ID:COUNT여야 합니다: {spec}")
                i_str, _, c_str = spec.partition(":")
                sess.add_item(int(i_str), int(c_str))
            if args.max_martials:
                sess.max_martials()
            if args.unlock_achievements:
                sess.unlock_achievements()
            res = sess.save(output_dir=Path(args.output) if args.output else None, force=bool(args.force))
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"저장 완료: {len(res['written'])}개 파일")
                for w in res["written"]:
                    print(f"  파일: {w}")
                for b in res["backups"]:
                    print(f"  백업: {b}")
            return 0

        if args.command == "serve":
            srv = create_http_server(
                save_dir=args.save_dir,
                host=args.host,
                port=int(args.port),
                html_path=args.html,
                allow_remote=bool(args.allow_remote),
            )
            h, p = srv.server_address[0], srv.server_address[1]
            print(f"귀곡팔황 로컬 웹 에디터 실행 중: http://{h}:{p}/ (종료: Ctrl+C)")
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                print("\n서버를 종료합니다.")
            finally:
                srv.server_close()
            return 0
    except (ValueError, RuntimeError, PermissionError, FileNotFoundError, OSError) as exc:
        sys.stderr.write(f"오류: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
