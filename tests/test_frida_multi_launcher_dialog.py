
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from ui import ui_messages
from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption


def _build_dialog(owner_widget) -> FridaMultiLauncherDialog:
    options = [
        FridaScriptOption(
            label='[工作区] alpha.js',
            path=Path('/tmp/alpha.js'),
            source_kind='workspace',
            display_name='alpha.js',
            is_pinned=True,
            last_used_at='2026-06-08T10:30:00+08:00',
            tags=('network',),
        ),
        FridaScriptOption(
            label='[参数化] [内置源] jni_method_trace.js',
            path=Path('/tmp/jni_method_trace.js'),
            kind='jni_method_trace',
            source_kind='builtin_source',
            display_name='jni_method_trace.js',
            summary='libfoo.so',
            template_path=Path('/templates/jni_method_trace.js'),
            tags=('jni', 'native'),
        ),
        FridaScriptOption(
            label='[工作区内置副本] 内置-okhttp.js',
            path=Path('/tmp/内置-okhttp.js'),
            source_kind='workspace_builtin_copy',
            display_name='内置-okhttp.js',
        ),
    ]
    return FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='spawn',
        options=options,
    )


def test_dialog_search_matches_summary_and_updates_count(qapp, owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    dialog.search_input.setText('libfoo')
    qapp.processEvents()

    assert dialog.available_list.count() == 1
    assert dialog.available_summary_label.text() == ui_messages.ADVANCED_FRIDA_RESULTS_LABEL.format(visible=1, total=3)
    assert dialog.available_empty_label.isHidden()
    dialog.deleteLater()


def test_dialog_search_empty_state_uses_search_message(qapp, owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    dialog.show()
    qapp.processEvents()
    dialog.search_input.setText('missing-keyword')
    qapp.processEvents()

    assert dialog.available_list.count() == 0
    assert dialog.available_empty_label.text() == ui_messages.ADVANCED_FRIDA_EMPTY_SEARCH
    assert dialog.available_empty_label.isVisible()
    dialog.deleteLater()


def test_dialog_source_filter_empty_state_uses_filter_message(qapp, owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    dialog.show()
    qapp.processEvents()

    original_matches_filter = dialog._matches_filter

    def _filter_excludes_everything(option):
        return False

    dialog._matches_filter = _filter_excludes_everything
    dialog.source_filter_combo.setCurrentText(ui_messages.ADVANCED_FRIDA_FILTER_PARAMETERIZED)
    dialog._rebuild_available_list()
    qapp.processEvents()

    assert dialog.available_list.count() == 0
    assert dialog.available_empty_label.text() == ui_messages.ADVANCED_FRIDA_EMPTY_FILTER
    assert dialog.available_empty_label.isVisible()

    dialog._matches_filter = original_matches_filter
    dialog.deleteLater()


def test_dialog_details_include_template_runtime_and_hint(owner_widget) -> None:
    option = FridaScriptOption(
        label='[参数化] jni_method_trace.runtime.js (libfoo.so)',
        path=Path('/tmp/jni_method_trace.demo.runtime.js'),
        kind='jni_method_trace',
        source_kind='workspace',
        display_name='jni_method_trace.runtime.js',
        summary='libfoo.so',
        template_path=Path('/templates/jni_method_trace.js'),
        runtime_key='demo-key',
    )
    dialog = FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='attach',
        options=[],
    )
    lines = dialog._detail_lines_for_option(option, selected_index=0)

    assert ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_OVERVIEW in lines
    assert ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_LOCATION in lines
    assert ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_RUNTIME in lines
    assert ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_ACTION in lines
    assert ui_messages.ADVANCED_FRIDA_DETAIL_TEMPLATE_PATH.format(value=str(option.template_path)) in lines
    assert ui_messages.ADVANCED_FRIDA_DETAIL_RUNTIME_KEY in lines
    assert ui_messages.ADVANCED_FRIDA_DETAIL_HINT in lines
    dialog.deleteLater()


def test_dialog_available_summary_is_shown_in_available_column(owner_widget) -> None:
    dialog = _build_dialog(owner_widget)

    assert dialog.available_summary_label.parent() is dialog.available_list.parentWidget()
    dialog.deleteLater()


def test_dialog_tooltip_uses_same_details_as_detail_panel(owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    option = dialog._all_options[1]

    tooltip = dialog._tooltip_for_option(option)

    assert ui_messages.ADVANCED_FRIDA_DETAIL_NAME.format(value=option.display_name or option.path.name) in tooltip
    assert ui_messages.ADVANCED_FRIDA_DETAIL_SUMMARY.format(value=option.summary) in tooltip
    assert ui_messages.ADVANCED_FRIDA_DETAIL_HINT in tooltip
    dialog.deleteLater()




def test_dialog_selected_item_tooltip_is_set_immediately(qapp, owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    dialog.show()
    qapp.processEvents()

    dialog.available_list.setCurrentRow(1)
    qapp.processEvents()

    dialog._add_selected_items()

    assert dialog.selected_list.count() == 1
    tooltip = dialog.selected_list.item(0).toolTip()
    assert tooltip
    assert ui_messages.ADVANCED_FRIDA_DETAIL_ORDER.format(index=1) in tooltip
    assert ui_messages.ADVANCED_FRIDA_DETAIL_ACTION_SELECTED in tooltip
    dialog.deleteLater()

def test_dialog_cancelled_parameterized_add_stops_remaining_batch(qapp, owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    dialog._all_options = [dialog._all_options[1], dialog._all_options[2]]
    dialog._rebuild_available_list()
    dialog.show()
    qapp.processEvents()

    def resolver(option: FridaScriptOption) -> FridaScriptOption | None:
        if option.kind == 'jni_method_trace':
            return None
        return option

    dialog._add_option_resolver = resolver
    dialog.available_list.setSelectionMode(dialog.available_list.SelectionMode.MultiSelection)
    dialog.available_list.item(0).setSelected(True)
    dialog.available_list.item(1).setSelected(True)
    qapp.processEvents()

    dialog._add_selected_items()

    assert dialog.had_add_cancelled() is True
    assert dialog.selected_list.count() == 0
    dialog.deleteLater()


def test_dialog_empty_details_explain_detail_fields(owner_widget) -> None:
    dialog = _build_dialog(owner_widget)

    assert dialog.details_label.text() == ui_messages.ADVANCED_FRIDA_DETAIL_EMPTY
    dialog.deleteLater()



def test_dialog_view_filter_recent_shows_only_recent(qapp, owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    dialog.view_filter_combo.setCurrentText(ui_messages.ADVANCED_FRIDA_VIEW_RECENT)
    qapp.processEvents()
    assert dialog.available_list.count() == 1
    assert 'alpha.js' in dialog.available_list.item(0).text()
    dialog.deleteLater()


def test_dialog_search_matches_tags(qapp, owner_widget) -> None:
    dialog = _build_dialog(owner_widget)
    dialog.search_input.setText('native')
    qapp.processEvents()
    assert dialog.available_list.count() == 1
    assert 'jni_method_trace.js' in dialog.available_list.item(0).text()
    dialog.deleteLater()


def test_dialog_initial_selected_options_restore_into_selected_list(qapp, owner_widget) -> None:
    preset_option = FridaScriptOption(
        label='[工作区] restored.js',
        path=Path('/tmp/restored.js'),
        source_kind='workspace',
        display_name='restored.js',
        summary='restored summary',
    )
    dialog = FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='attach',
        options=[],
        initial_selected_options=[preset_option],
    )
    dialog.show()
    qapp.processEvents()

    assert dialog.selected_list.count() == 1
    assert dialog.selected_list.item(0).text() == preset_option.label
    assert dialog.selected_list.item(0).toolTip()
    assert dialog.start_button.isEnabled() is True
    dialog.deleteLater()


def test_dialog_detail_lines_include_item_note_when_present(owner_widget) -> None:
    dialog = FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='attach',
        options=[],
    )
    option = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path('/tmp/alpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
        note='仅首页阶段执行',
    )

    lines = dialog._detail_lines_for_option(option)

    assert ui_messages.ADVANCED_FRIDA_DETAIL_ITEM_NOTE.format(value='仅首页阶段执行') in lines
    dialog.deleteLater()


def test_dialog_detail_lines_include_item_strategy_when_present(owner_widget) -> None:
    dialog = FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='attach',
        options=[],
    )
    option = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path('/tmp/alpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
        mode_strategy='spawn',
        auto_stop=True,
    )

    lines = dialog._detail_lines_for_option(option)

    assert ui_messages.ADVANCED_FRIDA_DETAIL_ITEM_STRATEGY.format(
        mode=ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_SPAWN,
        auto_stop=ui_messages.ADVANCED_FRIDA_AUTO_STOP_YES,
    ) in lines
    dialog.deleteLater()


def test_dialog_selected_option_note_updates_tooltip_and_details(qapp, owner_widget) -> None:
    option = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path('/tmp/alpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
    )
    dialog = FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='attach',
        options=[],
        initial_selected_options=[option],
    )
    dialog.show()
    qapp.processEvents()

    item = dialog.selected_list.item(0)
    updated = FridaScriptOption(
        label=option.label,
        path=option.path,
        source_kind=option.source_kind,
        display_name=option.display_name,
        note='第二步：补 JNI',
    )
    item.setData(Qt.ItemDataRole.UserRole, updated)
    dialog._refresh_selected_item_tooltips()
    dialog.selected_list.setCurrentRow(0)
    dialog._update_details()
    qapp.processEvents()

    assert ui_messages.ADVANCED_FRIDA_DETAIL_ITEM_NOTE.format(value='第二步：补 JNI') in item.toolTip()
    assert ui_messages.ADVANCED_FRIDA_DETAIL_ITEM_NOTE.format(value='第二步：补 JNI') in dialog.details_label.text()
    dialog.deleteLater()


def test_dialog_strategy_button_exists_and_follows_selection(qapp, owner_widget) -> None:
    option = FridaScriptOption(label='[工作区] alpha.js', path=Path('C:/demo/alpha.js'))
    dialog = FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='attach',
        options=[option],
        initial_selected_options=[option],
    )
    dialog.show()
    qapp.processEvents()

    assert dialog.edit_item_strategy_button.isEnabled() is True
    dialog.selected_list.setCurrentRow(-1)
    dialog.selected_list.clearSelection()
    dialog._sync_button_state()

    assert dialog.edit_item_strategy_button.isEnabled() is False
    dialog.deleteLater()


def test_dialog_edit_selected_item_strategy_updates_item(qapp, owner_widget, monkeypatch) -> None:
    option = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path('C:/demo/alpha.js'),
        mode_strategy='inherit',
        auto_stop=False,
    )
    dialog = FridaMultiLauncherDialog(
        owner_widget,
        package_name='pkg.demo',
        mode='attach',
        options=[option],
        initial_selected_options=[option],
    )
    dialog.show()
    qapp.processEvents()
    dialog.selected_list.setCurrentRow(0)

    calls = iter([
        (ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_SPAWN, True),
        (ui_messages.ADVANCED_FRIDA_AUTO_STOP_YES, True),
    ])
    monkeypatch.setattr('ui.frida_multi_launcher_dialog.QInputDialog.getItem', lambda *args, **kwargs: next(calls))

    dialog._edit_selected_item_strategy()

    updated = dialog.selected_list.item(0).data(Qt.ItemDataRole.UserRole)
    assert updated.mode_strategy == 'spawn'
    assert updated.auto_stop is True
    assert ui_messages.ADVANCED_FRIDA_DETAIL_ITEM_STRATEGY.format(
        mode=ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_SPAWN,
        auto_stop=ui_messages.ADVANCED_FRIDA_AUTO_STOP_YES,
    ) in dialog.selected_list.item(0).toolTip()
    dialog.deleteLater()

