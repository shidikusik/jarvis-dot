"""A user-local credential store, separate from settings and application files.

Windows uses DPAPI with the current user's identity. Linux stores a private
0600 file because a desktop keyring is not guaranteed on every distribution.
No credential is read from the repository, environment, or bundled resources.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from jarvis.storage import data_directory


class CredentialsError(ValueError):
    """An error whose message never includes a key or underlying exception."""


_WINDOWS_MAGIC = b"JARVISDOT-DPAPI\x00\x01"
_LOCAL_MAGIC = b"JARVISDOT-LOCAL\x00\x01"
_MAX_FILE_BYTES = 4096


def validate_gemini_key(key: str) -> str:
    if not isinstance(key, str):
        raise CredentialsError("Введите API-ключ Google AI Studio.")
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{20,256}", key):
        raise CredentialsError("Проверьте формат API-ключа Google AI Studio.")
    return key


def _key_path() -> Path:
    path = data_directory() / "credentials" / "gemini.key"
    # An accidentally overridden data directory must never put a secret in
    # application source or a PyInstaller extraction directory.
    application = Path(__file__).resolve().parents[1]
    if path.resolve().is_relative_to(application):
        raise CredentialsError("Хранилище ключа должно находиться в папке данных пользователя.")
    return path


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    """Call Windows DPAPI without adding a dependency to Linux installations."""
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DataBlob()
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p,
                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.DWORD, ctypes.POINTER(DataBlob)]
        operation.restype = wintypes.BOOL
        success = operation(ctypes.byref(source), None, None, None, None,
                            0x01, ctypes.byref(target))
    else:
        operation = crypt32.CryptProtectData
        operation.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR,
                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.DWORD, ctypes.POINTER(DataBlob)]
        operation.restype = wintypes.BOOL
        success = operation(ctypes.byref(source), "JarvisDot Gemini API key",
                            None, None, None, 0x01, ctypes.byref(target))
    if not success:
        raise CredentialsError("Windows не смог защитить или открыть сохранённый ключ.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def save_gemini_key(key: str) -> Path:
    key = validate_gemini_key(key)
    path = _key_path()
    encoded = key.encode("utf-8")
    try:
        payload = (_WINDOWS_MAGIC + _dpapi(encoded, decrypt=False)
                   if sys.platform == "win32" else _LOCAL_MAGIC + encoded)
        if path.parent.is_symlink() or path.is_symlink():
            raise CredentialsError("Хранилище ключа не может быть символической ссылкой.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            path.parent.chmod(0o700)
        fd, temporary = tempfile.mkstemp(prefix=".key-", dir=path.parent)
        try:
            if sys.platform != "win32":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except CredentialsError:
        raise
    except (OSError, ValueError, AttributeError):
        raise CredentialsError("Не удалось сохранить API-ключ в защищённой папке пользователя.") from None
    return path


def load_gemini_key() -> str:
    path = _key_path()
    try:
        if path.is_symlink() or path.parent.is_symlink():
            raise CredentialsError("Хранилище ключа не может быть символической ссылкой.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            return ""
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise CredentialsError("Файл ключа повреждён. Сохраните ключ повторно.")
            if sys.platform != "win32":
                if info.st_mode & 0o077 or (hasattr(os, "getuid") and info.st_uid != os.getuid()):
                    raise CredentialsError("К файлу ключа должны иметь доступ только вы. Сохраните ключ повторно.")
            payload = source.read(_MAX_FILE_BYTES + 1)
        if len(payload) > _MAX_FILE_BYTES:
            raise CredentialsError("Файл ключа повреждён. Сохраните ключ повторно.")
        magic = _WINDOWS_MAGIC if sys.platform == "win32" else _LOCAL_MAGIC
        if not payload.startswith(magic):
            raise CredentialsError("Файл ключа повреждён. Сохраните ключ повторно.")
        encoded = payload[len(magic):]
        if sys.platform == "win32":
            encoded = _dpapi(encoded, decrypt=True)
        return validate_gemini_key(encoded.decode("utf-8"))
    except CredentialsError:
        raise
    except (OSError, ValueError, AttributeError):
        raise CredentialsError("Не удалось открыть сохранённый API-ключ. Сохраните ключ повторно.") from None


def has_gemini_key() -> bool:
    try:
        return bool(load_gemini_key())
    except CredentialsError:
        return False


def delete_gemini_key() -> None:
    """Remove the user's local key when they choose to disconnect Google."""
    path = _key_path()
    try:
        if path.is_symlink() or path.parent.is_symlink():
            raise CredentialsError("Хранилище ключа не может быть символической ссылкой.")
        path.unlink(missing_ok=True)
    except OSError:
        raise CredentialsError("Не удалось удалить сохранённый API-ключ.") from None
