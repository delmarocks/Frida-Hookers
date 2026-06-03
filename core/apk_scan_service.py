from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .errors import ApkScanExecutionError


class ApkScanService:
    # 本地 APK 扫描服务。
    # 只负责两件事：
    # 1. 校验 ApkCheckPack.exe 和目标 APK 路径
    # 2. 调用外部 exe 并返回 stdout/stderr/returncode
    def __init__(self, context: Any) -> None:
        self.context = context

    def _decode_output(self, data: bytes) -> str:
        if not data:
            return ""
        for encoding in ("utf-8", "gbk", "cp936"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def scan_apk(self, apk_path: str | Path) -> dict[str, Any]:
        exe_path = self.context.local_apk_check_pack_exe
        if not exe_path.is_file():
            raise ApkScanExecutionError(
                f"未找到 APK 扫描工具：{exe_path}",
                hint="请检查 mobile-deploy 目录中的 ApkCheckPack.exe 是否存在。",
            )

        target_apk = Path(apk_path).expanduser().resolve()
        if not target_apk.is_file():
            raise ApkScanExecutionError(
                f"APK 文件不存在：{target_apk}",
                hint="请确认所选文件仍存在且路径可访问后重试。",
            )
        if target_apk.suffix.lower() != ".apk":
            raise ApkScanExecutionError(
                f"只能扫描 .apk 文件：{target_apk}",
                hint="请重新选择一个以 .apk 结尾的本地文件。",
            )

        completed = subprocess.run(
            [str(exe_path), "-f", str(target_apk)],
            capture_output=True,
            check=False,
        )
        return {
            "exe_path": str(exe_path),
            "apk_path": str(target_apk),
            "returncode": completed.returncode,
            "stdout": self._decode_output(completed.stdout).strip(),
            "stderr": self._decode_output(completed.stderr).strip(),
        }
