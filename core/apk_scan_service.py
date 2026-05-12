from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


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
            raise RuntimeError(f"未找到 APK 扫描工具：{exe_path}")

        target_apk = Path(apk_path).expanduser().resolve()
        if not target_apk.is_file():
            raise RuntimeError(f"APK 文件不存在：{target_apk}")
        if target_apk.suffix.lower() != ".apk":
            raise RuntimeError(f"只能扫描 .apk 文件：{target_apk}")

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
