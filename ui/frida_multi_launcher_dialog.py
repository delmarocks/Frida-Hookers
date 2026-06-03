from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import ui_messages


@dataclass(frozen=True)
class FridaScriptOption:
    label: str
    path: Path
    kind: str = "plain"
    template_path: Path | None = None
    config_payload: object | None = None
    runtime_key: str | None = None


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
    ) -> None:
        super().__init__(owner)
        self.setWindowTitle(ui_messages.ADVANCED_FRIDA_DIALOG_TITLE)
        self.resize(760, 460)
        self._add_option_resolver = add_option_resolver
        self._reconfigure_option_resolver = reconfigure_option_resolver

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
        self.available_list = QListWidget(self)
        available_container.addWidget(self.available_list, 1)
        content_row.addLayout(available_container, 1)

        middle_buttons = QVBoxLayout()
        middle_buttons.addStretch(1)
        self.add_button = QPushButton(ui_messages.ADVANCED_FRIDA_ADD_BUTTON, self)
        self.remove_button = QPushButton(ui_messages.ADVANCED_FRIDA_REMOVE_BUTTON, self)
        self.reconfigure_button = QPushButton(ui_messages.ADVANCED_FRIDA_RECONFIGURE_BUTTON, self)
        self.move_up_button = QPushButton(ui_messages.ADVANCED_FRIDA_MOVE_UP_BUTTON, self)
        self.move_down_button = QPushButton(ui_messages.ADVANCED_FRIDA_MOVE_DOWN_BUTTON, self)
        for button in (
            self.add_button,
            self.remove_button,
            self.reconfigure_button,
            self.move_up_button,
            self.move_down_button,
        ):
            middle_buttons.addWidget(button)
        middle_buttons.addStretch(1)
        content_row.addLayout(middle_buttons)

        selected_container = QVBoxLayout()
        selected_container.addWidget(QLabel(ui_messages.ADVANCED_FRIDA_SELECTED_SCRIPTS_LABEL))
        self.selected_list = QListWidget(self)
        selected_container.addWidget(self.selected_list, 1)
        content_row.addLayout(selected_container, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.start_button = QPushButton(ui_messages.ADVANCED_FRIDA_START_BUTTON, self)
        self.cancel_button = QPushButton(ui_messages.ADVANCED_FRIDA_CANCEL_BUTTON, self)
        self.start_button.setDefault(True)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        for option in options:
            item = QListWidgetItem(option.label)
            item.setData(Qt.ItemDataRole.UserRole, option)
            self.available_list.addItem(item)

        self.add_button.clicked.connect(self._add_selected_items)
        self.remove_button.clicked.connect(self._remove_selected_items)
        self.reconfigure_button.clicked.connect(self._reconfigure_selected_item)
        self.move_up_button.clicked.connect(self._move_selected_item_up)
        self.move_down_button.clicked.connect(self._move_selected_item_down)
        self.start_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.available_list.itemDoubleClicked.connect(lambda _item: self._add_selected_items())
        self.selected_list.itemDoubleClicked.connect(lambda _item: self._remove_selected_items())
        self.selected_list.itemSelectionChanged.connect(self._sync_button_state)
        self._sync_button_state()

    def selected_options(self) -> list[FridaScriptOption]:
        options: list[FridaScriptOption] = []
        for index in range(self.selected_list.count()):
            item = self.selected_list.item(index)
            option = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(option, FridaScriptOption):
                options.append(option)
        return options

    def _add_selected_items(self) -> None:
        for item in self.available_list.selectedItems():
            option = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(option, FridaScriptOption):
                continue
            selected_option = option
            if self._add_option_resolver is not None:
                selected_option = self._add_option_resolver(option)
            if selected_option is None:
                continue
            selected_item = QListWidgetItem(selected_option.label)
            selected_item.setData(Qt.ItemDataRole.UserRole, selected_option)
            self.selected_list.addItem(selected_item)
        self._sync_button_state()

    def _remove_selected_items(self) -> None:
        for item in self.selected_list.selectedItems():
            row = self.selected_list.row(item)
            self.selected_list.takeItem(row)
        self._sync_button_state()

    def _move_selected_item_up(self) -> None:
        row = self.selected_list.currentRow()
        if row <= 0:
            return
        item = self.selected_list.takeItem(row)
        self.selected_list.insertItem(row - 1, item)
        self.selected_list.setCurrentRow(row - 1)

    def _move_selected_item_down(self) -> None:
        row = self.selected_list.currentRow()
        if row < 0 or row >= self.selected_list.count() - 1:
            return
        item = self.selected_list.takeItem(row)
        self.selected_list.insertItem(row + 1, item)
        self.selected_list.setCurrentRow(row + 1)

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
        self._sync_button_state()

    def _sync_button_state(self) -> None:
        self.start_button.setEnabled(self.selected_list.count() > 0)
        current_item = self.selected_list.currentItem()
        current_option = (
            current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else None
        )
        self.reconfigure_button.setEnabled(
            self._reconfigure_option_resolver is not None
            and isinstance(current_option, FridaScriptOption)
            and current_option.kind != "plain"
        )
