"""Encrypted, per-user secret storage for the Windows desktop edition."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path


CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DesktopSecretError(RuntimeError):
    """Raised when a desktop secret cannot be protected or read safely."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(value, len(value))
    blob = _DataBlob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _windows_libraries():
    if os.name != "nt":
        raise DesktopSecretError("Windows DPAPI is unavailable on this operating system")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def protect_for_current_user(value: bytes) -> bytes:
    """Encrypt bytes with Windows DPAPI for the signed-in Windows user."""
    if not value:
        raise DesktopSecretError("Cannot protect an empty secret")

    crypt32, kernel32 = _windows_libraries()
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    succeeded = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "InternTrack OpenAI API key",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer
    if not succeeded:
        error = ctypes.WinError(ctypes.get_last_error())
        raise DesktopSecretError("Windows could not protect the API key") from error

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def unprotect_for_current_user(value: bytes) -> bytes:
    """Decrypt bytes previously protected for the signed-in Windows user."""
    if not value:
        raise DesktopSecretError("Encrypted secret file is empty")

    crypt32, kernel32 = _windows_libraries()
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    succeeded = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer
    if not succeeded:
        error = ctypes.WinError(ctypes.get_last_error())
        raise DesktopSecretError("Windows could not decrypt the saved API key") from error

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


class DesktopSecretStore:
    """Persist one OpenAI API key as an encrypted DPAPI blob."""

    def __init__(
        self,
        data_directory: Path,
        protect: Callable[[bytes], bytes] = protect_for_current_user,
        unprotect: Callable[[bytes], bytes] = unprotect_for_current_user,
    ) -> None:
        self.path = data_directory / "openai-api-key.dpapi"
        self._protect = protect
        self._unprotect = unprotect

    def save(self, api_key: str) -> None:
        cleaned = api_key.strip()
        if not cleaned:
            raise DesktopSecretError("API key cannot be empty")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self._protect(cleaned.encode("utf-8"))
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_bytes(encrypted)
        os.replace(temporary_path, self.path)

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            decrypted = self._unprotect(self.path.read_bytes()).decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise DesktopSecretError("Saved API key could not be read") from exc
        if not decrypted.strip():
            raise DesktopSecretError("Saved API key is empty")
        return decrypted

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
