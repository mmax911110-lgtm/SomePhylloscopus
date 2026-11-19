"""Small offline Windows player; audio is selected by the local species catalogue."""
from pathlib import Path
import os
import uuid


class BirdAudioPlayer:
    def __init__(self, app_root):
        self.app_root = Path(app_root).resolve()
        self.path = None
        self.alias = "willow_" + uuid.uuid4().hex
        self._dll = None

    def _command(self, text):
        import ctypes
        from ctypes import wintypes
        if os.name != "nt":
            raise RuntimeError("本地叫声播放器目前支持 Windows。")
        if self._dll is None:
            self._dll = ctypes.WinDLL("winmm")
            self._dll.mciSendStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                               wintypes.UINT, wintypes.HWND]
            self._dll.mciSendStringW.restype = wintypes.DWORD
            self._dll.mciGetErrorStringW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.UINT]
        buffer = ctypes.create_unicode_buffer(1024)
        error = self._dll.mciSendStringW(text, buffer, len(buffer), None)
        if error:
            self._dll.mciGetErrorStringW(error, buffer, len(buffer))
            raise RuntimeError(buffer.value or f"音频播放错误 {error}")
        return buffer.value

    def play(self, path):
        candidate = Path(path)
        candidate = (self.app_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if (not candidate.is_relative_to(self.app_root / "assets") or
                not candidate.is_file() or candidate.suffix.lower() not in {".mp3", ".wav"} or
                any(c in str(candidate) for c in ('"', '\n', '\r'))):
            raise ValueError("没有可播放的本地叫声文件。")
        self.stop()
        device = "waveaudio" if candidate.suffix.lower() == ".wav" else "mpegvideo"
        self._command(f'open "{candidate}" type {device} alias {self.alias}')
        self.path = candidate
        try:
            self._command(f"play {self.alias} from 0")
        except Exception:
            self.stop()
            raise

    @property
    def playing(self):
        if self.path is None:
            return False
        try:
            running = self._command(f"status {self.alias} mode") == "playing"
            if not running:
                self.stop()
            return running
        except RuntimeError:
            self.stop()
            return False

    def stop(self):
        if self.path is not None:
            try:
                self._command(f"close {self.alias}")
            except RuntimeError:
                pass
        self.path = None

    close = stop
