from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.errors import ApkScanExecutionError
from core.apk_scan_service import ApkScanService


class DummyScanContext:
    def __init__(self, exe_path: Path) -> None:
        self.local_apk_check_pack_exe = exe_path


def test_decode_output_prefers_utf8(tmp_path: Path) -> None:
    service = ApkScanService(DummyScanContext(tmp_path / "tool.exe"))
    assert service._decode_output("你好".encode("utf-8")) == "你好"


def test_decode_output_falls_back_to_gbk(tmp_path: Path) -> None:
    service = ApkScanService(DummyScanContext(tmp_path / "tool.exe"))
    assert service._decode_output("中文".encode("gbk")) == "中文"


def test_scan_apk_requires_existing_tool(tmp_path: Path) -> None:
    service = ApkScanService(DummyScanContext(tmp_path / "missing.exe"))
    apk_path = tmp_path / "demo.apk"
    apk_path.write_bytes(b"apk")
    with pytest.raises(ApkScanExecutionError, match="未找到 APK 扫描工具"):
        service.scan_apk(apk_path)


def test_scan_apk_requires_apk_suffix(tmp_path: Path) -> None:
    exe_path = tmp_path / "tool.exe"
    exe_path.write_bytes(b"exe")
    service = ApkScanService(DummyScanContext(exe_path))
    target = tmp_path / "demo.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ApkScanExecutionError, match="只能扫描 .apk 文件"):
        service.scan_apk(target)


def test_scan_apk_returns_decoded_stdout_and_stderr(tmp_path: Path, monkeypatch) -> None:
    exe_path = tmp_path / "tool.exe"
    exe_path.write_bytes(b"exe")
    apk_path = tmp_path / "demo.apk"
    apk_path.write_bytes(b"apk")
    service = ApkScanService(DummyScanContext(exe_path))

    def fake_run(args, capture_output, check):
        assert args == [str(exe_path), "-f", str(apk_path.resolve())]
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(
            args=args,
            returncode=7,
            stdout="结果输出\n".encode("utf-8"),
            stderr="错误输出".encode("gbk"),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.scan_apk(apk_path)
    assert result["exe_path"] == str(exe_path)
    assert result["apk_path"] == str(apk_path.resolve())
    assert result["returncode"] == 7
    assert result["stdout"] == "结果输出"
    assert result["stderr"] == "错误输出"
