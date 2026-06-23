from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from . import ui_messages
from .widgets import NoWheelComboBox


@dataclass(frozen=True)
class FridaScriptOption:
    label: str
    path: Path
    kind: str = "plain"
    source_kind: str = "workspace"
    display_name: str | None = None
    summary: str | None = None
    template_path: Path | None = None
    config_payload: object | None = None
    runtime_key: str | None = None
    is_pinned: bool = False
    last_used_at: str | None = None
    tags: tuple[str, ...] = ()
    note: str = ""
    mode_strategy: str = "inherit"
    auto_stop: bool = False


class FridaMultiLauncherDialog(QDialog):
    def __init__(
        self,
        owner: QWidget | None,
        *,
        package_name: str,
        mode: str,
        options: list[FridaScriptOption],
        add_option_resolver: Callable[[FridaScriptOption], FridaScriptOption | None] | None = None,
        reconfigure_option_resolver: Callable[[FridaScriptOption], FridaScriptOption | None] | None = None,
        initial_selected_options: Iterable[FridaScriptOption] | None = None,
    ) -> None:
        super().__init__(owner)
        self.setWindowTitle(ui_messages.ADVANCED_FRIDA_DIALOG_TITLE)
        self.resize(760, 600)
        self._add_option_resolver = add_option_resolver
        self._reconfigure_option_resolver = reconfigure_option_resolver
        self._all_options = list(options)
        self._last_add_cancelled = False
        self._initial_selected_options = list(initial_selected_options or ())

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        summary_layout = QGridLayout()
        summary_layout.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_TARGET_APP_LABEL), 0, 0)
        summary_layout.addWidget(QLabel(package_name), 0, 1)
        summary_layout.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_MODE_LABEL), 1, 0)
        summary_layout.addWidget(QLabel(mode), 1, 1)
        layout.addLayout(summary_layout)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        layout.addLayout(content_row, 1)

        available_container = QVBoxLayout()
        available_container.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_AVAILABLE_SCRIPTS_LABEL))
        self.available_hint_label = QLabel(ui_messages.ADVANCED_FRIDA_AVAILABLE_HINT, self)
        self.available_hint_label.setWordWrap(True)
        self.available_hint_label.setObjectName("mutedLabel")
        available_container.addWidget(self.available_hint_label)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_SEARCH_LABEL))
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(ui_messages.ADVANCED_FRIDA_SEARCH_PLACEHOLDER)
        filter_row.addWidget(self.search_input, 1)
        filter_row.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_FILTER_LABEL))
        self.source_filter_combo = NoWheelComboBox(self)
        self.source_filter_combo.addItems([
            ui_messages.ADVANCED_FRIDA_FILTER_ALL,
            ui_messages.ADVANCED_FRIDA_FILTER_WORKSPACE,
            ui_messages.ADVANCED_FRIDA_FILTER_WORKSPACE_BUILTIN,
            ui_messages.ADVANCED_FRIDA_FILTER_BUILTIN,
            ui_messages.ADVANCED_FRIDA_FILTER_PARAMETERIZED,
        ])
        filter_row.addWidget(self.source_filter_combo)
        filter_row.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_VIEW_FILTER_LABEL))
        self.view_filter_combo = NoWheelComboBox(self)
        self.view_filter_combo.addItems([
            ui_messages.ADVANCED_FRIDA_VIEW_ALL,
            ui_messages.ADVANCED_FRIDA_VIEW_RECENT,
        ])
        filter_row.addWidget(self.view_filter_combo)
        available_container.addLayout(filter_row)
        self.available_summary_label = QLabel(ui_messages.ADVANCED_FRIDA_RESULTS_LABEL.format(visible=0, total=len(self._all_options)), self)
        self.available_summary_label.setObjectName("mutedLabel")
        available_container.addWidget(self.available_summary_label)

        self.available_list = QListWidget(self)
        self.available_list.setAlternatingRowColors(True)
        available_container.addWidget(self.available_list, 1)

        self.available_empty_label = QLabel(ui_messages.ADVANCED_FRIDA_EMPTY_AVAILABLE, self)
        self.available_empty_label.setWordWrap(True)
        self.available_empty_label.setObjectName("mutedLabel")
        available_container.addWidget(self.available_empty_label)
        content_row.addLayout(available_container, 1)

        middle_buttons = QVBoxLayout()
        middle_buttons.addStretch(1)
        self.add_button = QPushButton(ui_messages.ADVANCED_FRIDA_ADD_BUTTON, self)
        self.remove_button = QPushButton(ui_messages.ADVANCED_FRIDA_REMOVE_BUTTON, self)
        self.reconfigure_button = QPushButton(ui_messages.ADVANCED_FRIDA_RECONFIGURE_BUTTON, self)
        self.edit_item_note_button = QPushButton(ui_messages.ADVANCED_FRIDA_EDIT_ITEM_NOTE_BUTTON, self)
        self.edit_item_strategy_button = QPushButton(ui_messages.ADVANCED_FRIDA_EDIT_ITEM_STRATEGY_BUTTON, self)
        self.move_up_button = QPushButton(ui_messages.ADVANCED_FRIDA_MOVE_UP_BUTTON, self)
        self.move_down_button = QPushButton(ui_messages.ADVANCED_FRIDA_MOVE_DOWN_BUTTON, self)
        for button in (
            self.add_button,
            self.remove_button,
            self.reconfigure_button,
            self.edit_item_note_button,
            self.edit_item_strategy_button,
            self.move_up_button,
            self.move_down_button,
        ):
            middle_buttons.addWidget(button)
        middle_buttons.addStretch(1)
        content_row.addLayout(middle_buttons)

        selected_container = QVBoxLayout()
        selected_container.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_SELECTED_SCRIPTS_LABEL))
        self.selected_hint_label = QLabel(ui_messages.ADVANCED_FRIDA_SELECTED_HINT, self)
        self.selected_hint_label.setWordWrap(True)
        self.selected_hint_label.setObjectName("mutedLabel")
        selected_container.addWidget(self.selected_hint_label)
        self.selected_list = QListWidget(self)
        self.selected_list.setAlternatingRowColors(True)
        self.selected_list.setMinimumHeight(160)
        selected_container.addWidget(self.selected_list, 2)
        self.selected_empty_label = QLabel(ui_messages.ADVANCED_FRIDA_SELECTION_EMPTY, self)
        self.selected_empty_label.setWordWrap(True)
        self.selected_empty_label.setObjectName("mutedLabel")
        selected_container.addWidget(self.selected_empty_label)
        selected_container.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_DETAILS_LABEL))
        self.details_label = QLabel(ui_messages.ADVANCED_FRIDA_DETAIL_EMPTY, self)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details_label.setObjectName("statusValue")
        self.details_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        # 详情内容较长，放进可滚动区域并限高，避免把上方“启动顺序”列表挤窄。
        self.details_scroll = QScrollArea(self)
        self.details_scroll.setWidget(self.details_label)
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setMinimumHeight(120)
        self.details_scroll.setMaximumHeight(200)
        self.details_scroll.setObjectName("detailsScroll")
        selected_container.addWidget(self.details_scroll)
        content_row.addLayout(selected_container, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.start_button = QPushButton(ui_messages.ADVANCED_FRIDA_START_BUTTON, self)
        self.cancel_button = QPushButton(ui_messages.ADVANCED_FRIDA_CANCEL_BUTTON, self)
        self.start_button.setDefault(True)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self._rebuild_available_list()
        self._populate_initial_selected_items()

        self.search_input.textChanged.connect(self._rebuild_available_list)
        self.source_filter_combo.currentIndexChanged.connect(lambda _index: self._rebuild_available_list())
        self.view_filter_combo.currentIndexChanged.connect(lambda _index: self._rebuild_available_list())
        self.add_button.clicked.connect(self._add_selected_items)
        self.remove_button.clicked.connect(self._remove_selected_items)
        self.reconfigure_button.clicked.connect(self._reconfigure_selected_item)
        self.edit_item_note_button.clicked.connect(self._edit_selected_item_note)
        self.edit_item_strategy_button.clicked.connect(self._edit_selected_item_strategy)
        self.move_up_button.clicked.connect(self._move_selected_item_up)
        self.move_down_button.clicked.connect(self._move_selected_item_down)
        self.start_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.available_list.itemDoubleClicked.connect(lambda _item: self._add_selected_items())
        self.selected_list.itemDoubleClicked.connect(lambda _item: self._remove_selected_items())
        self.selected_list.itemSelectionChanged.connect(self._sync_button_state)
        self.available_list.itemSelectionChanged.connect(self._sync_button_state)
        self.available_list.itemSelectionChanged.connect(self._update_details)
        self.selected_list.itemSelectionChanged.connect(self._update_details)
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()


    def _populate_initial_selected_items(self) -> None:
        if not self._initial_selected_options:
            return
        last_added_item: QListWidgetItem | None = None
        for option in self._initial_selected_options:
            if not isinstance(option, FridaScriptOption):
                continue
            selected_item = QListWidgetItem(option.label)
            selected_item.setData(Qt.ItemDataRole.UserRole, option)
            selected_item.setToolTip(self._tooltip_for_option(option))
            self.selected_list.addItem(selected_item)
            last_added_item = selected_item
        if last_added_item is not None:
            self.selected_list.setCurrentItem(last_added_item)
        self._refresh_selected_item_tooltips()
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()

    def _matches_filter(self, option: FridaScriptOption) -> bool:
        keyword = self.search_input.text().strip().lower()
        if keyword:
            haystacks = [
                option.label.lower(),
                (option.display_name or option.path.name).lower(),
                option.source_kind.lower(),
                str(option.path).lower(),
                (option.summary or "").lower(),
                " ".join(option.tags).lower(),
                str(option.template_path).lower() if option.template_path is not None else "",
            ]
            if keyword not in " ".join(haystacks):
                return False
        current_view = self.view_filter_combo.currentText()
        if current_view == ui_messages.ADVANCED_FRIDA_VIEW_RECENT and not option.last_used_at:
            return False
        current_filter = self.source_filter_combo.currentText()
        if current_filter == ui_messages.ADVANCED_FRIDA_FILTER_ALL:
            return True
        if current_filter == ui_messages.ADVANCED_FRIDA_FILTER_WORKSPACE:
            return option.source_kind == "workspace" and option.kind == "plain"
        if current_filter == ui_messages.ADVANCED_FRIDA_FILTER_WORKSPACE_BUILTIN:
            return option.source_kind == "workspace_builtin_copy"
        if current_filter == ui_messages.ADVANCED_FRIDA_FILTER_BUILTIN:
            return option.source_kind == "builtin_source"
        if current_filter == ui_messages.ADVANCED_FRIDA_FILTER_PARAMETERIZED:
            return option.kind in {"jni_method_trace", "trace_init_proc"}
        return True

    def _rebuild_available_list(self) -> None:
        self.available_list.clear()
        visible_count = 0
        for option in self._all_options:
            if not self._matches_filter(option):
                continue
            item = QListWidgetItem(self._display_label_for_option(option))
            item.setData(Qt.ItemDataRole.UserRole, option)
            item.setToolTip(self._tooltip_for_option(option))
            self.available_list.addItem(item)
            visible_count += 1
        self.available_summary_label.setText(
            ui_messages.ADVANCED_FRIDA_RESULTS_LABEL.format(visible=visible_count, total=len(self._all_options))
        )
        self._update_available_empty_state(visible_count)
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()

    def _detail_lines_for_option(self, option: FridaScriptOption, *, selected_index: int | None = None) -> list[str]:
        detail_type = ui_messages.ADVANCED_FRIDA_TYPE_SCRIPT
        if option.kind in {"jni_method_trace", "trace_init_proc"} and option.runtime_key:
            detail_type = ui_messages.ADVANCED_FRIDA_TYPE_RUNTIME
        elif option.kind in {"jni_method_trace", "trace_init_proc"}:
            detail_type = ui_messages.ADVANCED_FRIDA_TYPE_TEMPLATE
        source_map = {
            "workspace": ui_messages.ADVANCED_FRIDA_WORKSPACE_SOURCE,
            "workspace_builtin_copy": ui_messages.ADVANCED_FRIDA_WORKSPACE_COPY_SOURCE,
            "builtin_source": ui_messages.ADVANCED_FRIDA_BUILTIN_SOURCE,
        }
        lines = [
            ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_OVERVIEW,
            ui_messages.ADVANCED_FRIDA_DETAIL_NAME.format(value=option.display_name or option.path.name),
            ui_messages.ADVANCED_FRIDA_DETAIL_TYPE.format(value=detail_type),
        ]
        if option.summary:
            lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_SUMMARY.format(value=option.summary))
        if option.note:
            lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_ITEM_NOTE.format(value=option.note))
        lines.append(
            ui_messages.ADVANCED_FRIDA_DETAIL_ITEM_STRATEGY.format(
                mode=self._mode_strategy_label(option.mode_strategy),
                auto_stop=self._auto_stop_label(option.auto_stop),
            )
        )
        if option.last_used_at:
            lines.append(ui_messages.ADVANCED_FRIDA_LAST_USED_AT.format(value=option.last_used_at))
        lines.extend([
            "",
            ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_LOCATION,
            ui_messages.ADVANCED_FRIDA_DETAIL_SOURCE.format(value=source_map.get(option.source_kind, option.source_kind)),
            ui_messages.ADVANCED_FRIDA_DETAIL_PATH.format(value=str(option.path)),
        ])
        runtime_lines: list[str] = []
        if option.template_path is not None:
            runtime_lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_TEMPLATE_PATH.format(value=str(option.template_path)))
        if option.runtime_key:
            runtime_lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_RUNTIME_KEY)
        if selected_index is not None:
            runtime_lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_ORDER.format(index=selected_index + 1))
        if runtime_lines:
            lines.extend(["", ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_RUNTIME, *runtime_lines])
        lines.extend(["", ui_messages.ADVANCED_FRIDA_DETAIL_SECTION_ACTION])
        if selected_index is not None:
            lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_ACTION_SELECTED)
        else:
            lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_ACTION_AVAILABLE)
        lines.append(ui_messages.ADVANCED_FRIDA_DETAIL_HINT)
        return lines

    def _update_details(self) -> None:
        selected_item = self.selected_list.currentItem()
        if selected_item is not None:
            option = selected_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(option, FridaScriptOption):
                self.details_label.setText("\n".join(self._detail_lines_for_option(option, selected_index=self.selected_list.currentRow())))
                return
        available_item = self.available_list.currentItem()
        if available_item is not None:
            option = available_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(option, FridaScriptOption):
                self.details_label.setText("\n".join(self._detail_lines_for_option(option)))
                return
        self.details_label.setText(ui_messages.ADVANCED_FRIDA_DETAIL_EMPTY)

    def selected_options(self) -> list[FridaScriptOption]:
        options: list[FridaScriptOption] = []
        for index in range(self.selected_list.count()):
            item = self.selected_list.item(index)
            option = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(option, FridaScriptOption):
                options.append(option)
        return options

    def had_add_cancelled(self) -> bool:
        return self._last_add_cancelled

    def _add_selected_items(self) -> None:
        self._last_add_cancelled = False
        last_added_item: QListWidgetItem | None = None
        for item in self.available_list.selectedItems():
            option = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(option, FridaScriptOption):
                continue
            selected_option = option
            if self._add_option_resolver is not None:
                selected_option = self._add_option_resolver(option)
            if selected_option is None:
                self._last_add_cancelled = True
                break
            selected_item = QListWidgetItem(selected_option.label)
            selected_item.setData(Qt.ItemDataRole.UserRole, selected_option)
            selected_item.setToolTip(self._tooltip_for_option(selected_option))
            self.selected_list.addItem(selected_item)
            last_added_item = selected_item
        if last_added_item is not None:
            self.selected_list.setCurrentItem(last_added_item)
        self._refresh_selected_item_tooltips()
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()

    def _remove_selected_items(self) -> None:
        selected_rows = sorted(
            {self.selected_list.row(item) for item in self.selected_list.selectedItems()},
            reverse=True,
        )
        if not selected_rows:
            return
        next_row = min(selected_rows)
        for row in selected_rows:
            self.selected_list.takeItem(row)
        if self.selected_list.count() > 0:
            self.selected_list.setCurrentRow(min(next_row, self.selected_list.count() - 1))
        else:
            self.selected_list.setCurrentRow(-1)
        self._refresh_selected_item_tooltips()
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()

    def _move_selected_item_up(self) -> None:
        row = self.selected_list.currentRow()
        if row <= 0:
            return
        item = self.selected_list.takeItem(row)
        self.selected_list.insertItem(row - 1, item)
        self.selected_list.setCurrentRow(row - 1)
        self._refresh_selected_item_tooltips()
        self._update_details()

    def _move_selected_item_down(self) -> None:
        row = self.selected_list.currentRow()
        if row < 0 or row >= self.selected_list.count() - 1:
            return
        item = self.selected_list.takeItem(row)
        self.selected_list.insertItem(row + 1, item)
        self.selected_list.setCurrentRow(row + 1)
        self._refresh_selected_item_tooltips()
        self._update_details()

    def _reconfigure_selected_item(self) -> None:
        if self._reconfigure_option_resolver is None:
            return
        item = self.selected_list.currentItem()
        if item is None:
            return
        option = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(option, FridaScriptOption):
            return
        updated_option = self._reconfigure_option_resolver(option)
        if updated_option is None:
            return
        item.setText(updated_option.label)
        item.setData(Qt.ItemDataRole.UserRole, updated_option)
        self._refresh_selected_item_tooltips()
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()


    def _edit_selected_item_note(self) -> None:
        item = self.selected_list.currentItem()
        if item is None:
            return
        option = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(option, FridaScriptOption):
            return
        note, accepted = QInputDialog.getText(
            self,
            ui_messages.ADVANCED_FRIDA_ITEM_NOTE_DIALOG_TITLE,
            ui_messages.ADVANCED_FRIDA_ITEM_NOTE_DIALOG_LABEL,
            text=option.note,
        )
        if not accepted:
            return
        updated_option = FridaScriptOption(
            label=option.label,
            path=option.path,
            kind=option.kind,
            source_kind=option.source_kind,
            display_name=option.display_name,
            summary=option.summary,
            template_path=option.template_path,
            config_payload=option.config_payload,
            runtime_key=option.runtime_key,
            is_pinned=option.is_pinned,
            last_used_at=option.last_used_at,
            tags=option.tags,
            note=str(note or '').strip()[:120],
            mode_strategy=option.mode_strategy,
            auto_stop=option.auto_stop,
        )
        item.setData(Qt.ItemDataRole.UserRole, updated_option)
        self._refresh_selected_item_tooltips()
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()

    @staticmethod
    def _mode_strategy_label(value: str) -> str:
        normalized = str(value or "inherit").strip().lower()
        mapping = {
            "inherit": ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_INHERIT,
            "attach": ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_ATTACH,
            "spawn": ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_SPAWN,
        }
        return mapping.get(normalized, ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_INHERIT)

    @staticmethod
    def _auto_stop_label(value: bool) -> str:
        return ui_messages.ADVANCED_FRIDA_AUTO_STOP_YES if value else ui_messages.ADVANCED_FRIDA_AUTO_STOP_NO

    def _edit_selected_item_strategy(self) -> None:
        item = self.selected_list.currentItem()
        if item is None:
            return
        option = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(option, FridaScriptOption):
            return
        strategy_choices = [
            ("inherit", ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_INHERIT),
            ("attach", ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_ATTACH),
            ("spawn", ui_messages.ADVANCED_FRIDA_MODE_STRATEGY_SPAWN),
        ]
        current_strategy_label = self._mode_strategy_label(option.mode_strategy)
        selected_strategy_label, accepted = QInputDialog.getItem(
            self,
            ui_messages.ADVANCED_FRIDA_ITEM_STRATEGY_DIALOG_TITLE,
            ui_messages.ADVANCED_FRIDA_ITEM_STRATEGY_DIALOG_MODE_LABEL,
            [label for _, label in strategy_choices],
            max(0, next((index for index, (_value, label) in enumerate(strategy_choices) if label == current_strategy_label), 0)),
            False,
        )
        if not accepted:
            return
        next_mode_strategy = next(
            (value for value, label in strategy_choices if label == selected_strategy_label),
            "inherit",
        )
        selected_auto_stop_label, accepted = QInputDialog.getItem(
            self,
            ui_messages.ADVANCED_FRIDA_ITEM_STRATEGY_DIALOG_TITLE,
            ui_messages.ADVANCED_FRIDA_ITEM_STRATEGY_DIALOG_AUTO_STOP_LABEL,
            [
                ui_messages.ADVANCED_FRIDA_AUTO_STOP_NO,
                ui_messages.ADVANCED_FRIDA_AUTO_STOP_YES,
            ],
            1 if option.auto_stop else 0,
            False,
        )
        if not accepted:
            return
        updated_option = FridaScriptOption(
            label=option.label,
            path=option.path,
            kind=option.kind,
            source_kind=option.source_kind,
            display_name=option.display_name,
            summary=option.summary,
            template_path=option.template_path,
            config_payload=option.config_payload,
            runtime_key=option.runtime_key,
            is_pinned=option.is_pinned,
            last_used_at=option.last_used_at,
            tags=option.tags,
            note=option.note,
            mode_strategy=next_mode_strategy,
            auto_stop=selected_auto_stop_label == ui_messages.ADVANCED_FRIDA_AUTO_STOP_YES,
        )
        item.setData(Qt.ItemDataRole.UserRole, updated_option)
        self._refresh_selected_item_tooltips()
        self._sync_button_state()
        self._update_details()
        self._update_selected_empty_state()

    def _tooltip_for_option(
        self,
        option: FridaScriptOption,
        *,
        selected_index: int | None = None,
    ) -> str:
        return "\n".join(self._detail_lines_for_option(option, selected_index=selected_index))

    def _display_label_for_option(self, option: FridaScriptOption) -> str:
        return option.label

    def _refresh_selected_item_tooltips(self) -> None:
        for index in range(self.selected_list.count()):
            item = self.selected_list.item(index)
            option = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(option, FridaScriptOption):
                item.setToolTip(self._tooltip_for_option(option, selected_index=index))

    def _update_available_empty_state(self, visible_count: int) -> None:
        if visible_count > 0:
            self.available_empty_label.setText("")
            self.available_empty_label.setVisible(False)
            return
        has_keyword = bool(self.search_input.text().strip())
        filtered = self.source_filter_combo.currentText() != ui_messages.ADVANCED_FRIDA_FILTER_ALL
        if has_keyword:
            empty_text = ui_messages.ADVANCED_FRIDA_EMPTY_SEARCH
        elif filtered:
            empty_text = ui_messages.ADVANCED_FRIDA_EMPTY_FILTER
        else:
            empty_text = ui_messages.ADVANCED_FRIDA_EMPTY_AVAILABLE
        self.available_empty_label.setText(empty_text)
        self.available_empty_label.setVisible(True)

    def _update_selected_empty_state(self) -> None:
        has_selected = self.selected_list.count() > 0
        self.selected_empty_label.setText(ui_messages.ADVANCED_FRIDA_SELECTION_EMPTY)
        self.selected_empty_label.setVisible(not has_selected)

    def _sync_button_state(self) -> None:
        self.start_button.setEnabled(self.selected_list.count() > 0)
        current_item = self.selected_list.currentItem()
        current_option = (
            current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else None
        )
        self.edit_item_note_button.setEnabled(isinstance(current_option, FridaScriptOption))
        self.edit_item_strategy_button.setEnabled(isinstance(current_option, FridaScriptOption))
        self.reconfigure_button.setEnabled(
            self._reconfigure_option_resolver is not None
            and isinstance(current_option, FridaScriptOption)
            and current_option.kind != "plain"
        )
