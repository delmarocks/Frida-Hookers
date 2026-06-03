from __future__ import annotations

from pathlib import Path

from ui import ui_messages


def test_state_text_wraps_message() -> None:
    assert ui_messages.state_text("空闲") == "状态：空闲"


def test_generated_script_body_contains_path() -> None:
    script_path = Path("demo.js")
    body = ui_messages.generated_script_body(script_path)
    assert "脚本已保存到" in body
    assert "demo.js" in body


def test_result_title_helpers_are_stable() -> None:
    assert ui_messages.object_info_title("Foo.bar") == "对象信息 - Foo.bar"
    assert ui_messages.object_explain_title("Foo.bar") == "对象解释 - Foo.bar"
    assert ui_messages.view_info_title("0x1234") == "View 信息 - 0x1234"
