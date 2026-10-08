from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .controls import MidiService, OscInputService
from .native import DmxCore, MAX_UNIVERSES
from .output import OutputService

EFFECTS = {"Pulse": 0, "Chase": 1, "Wave": 2, "Strobe": 3, "Sine": 4}


def _default_project() -> dict[str, Any]:
    return {
        "universes": 100,
        "profiles": [],
        "fixtures": [],
        "effects": [
            {"name": name, "pattern": pattern, "speed": 1.0, "intensity": 255}
            for name, pattern in (
                ("Pulse", "Pulse"), ("Chase", "Chase"), ("Wave", "Wave"),
                ("Strobe", "Strobe"), ("Sine", "Sine"),
            )
        ],
        "output": {"protocol": "Disabled", "destination": "", "serial_port": ""},
        "osc": {"listen": False, "listen_port": 9000, "send_port": 9001, "universe": 1},
        "midi": {
            "input": "", "output": "", "channel": 1, "cc": 1, "universe": 1, "dmx_channel": 1,
        },
    }


def _project_path() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(location) / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class StatusRelay(QObject):
    message = Signal(str)


class FixtureProfileDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, profile: dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Fixture profile editor")
        self.setMinimumSize(520, 480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(profile.get("name", "") if profile else "")
        self.manufacturer = QLineEdit(profile.get("manufacturer", "") if profile else "")
        form.addRow("Fixture name", self.name)
        form.addRow("Manufacturer", self.manufacturer)
        layout.addLayout(form)
        layout.addWidget(QLabel("Define channel order and names (each row is one DMX slot):"))
        self.channels = QTableWidget(0, 1)
        self.channels.setHorizontalHeaderLabels(["Channel attribute"])
        self.channels.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.channels.verticalHeader().setDefaultSectionSize(40)
        layout.addWidget(self.channels)
        buttons = QHBoxLayout()
        add_channel = QPushButton("Add channel")
        remove_channel = QPushButton("Remove selected")
        add_channel.clicked.connect(self._add_channel)
        remove_channel.clicked.connect(self._remove_channel)
        buttons.addWidget(add_channel)
        buttons.addWidget(remove_channel)
        layout.addLayout(buttons)
        for channel in (profile or {}).get("channels", []):
            self._add_channel(channel)
        if self.channels.rowCount() == 0:
            self._add_channel("Dimmer")
        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

    def _add_channel(self, name: str = "") -> None:
        row = self.channels.rowCount()
        self.channels.insertRow(row)
        self.channels.setItem(row, 0, QTableWidgetItem(name))

    def _remove_channel(self) -> None:
        row = self.channels.currentRow()
        if row >= 0:
            self.channels.removeRow(row)

    def profile(self) -> dict[str, Any]:
        return {
            "name": self.name.text().strip(),
            "manufacturer": self.manufacturer.text().strip(),
            "channels": [
                (self.channels.item(row, 0).text().strip() if self.channels.item(row, 0) else "")
                or f"Channel {row + 1}"
                for row in range(self.channels.rowCount())
            ],
        }


class PatchFixtureDialog(QDialog):
    def __init__(self, profiles: list[dict[str, Any]], universes: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Patch fixture")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.profile = QComboBox()
        self.profile.addItems([profile["name"] for profile in profiles])
        self.name = QLineEdit()
        self.universe = QSpinBox()
        self.universe.setRange(1, universes)
        self.address = QSpinBox()
        self.address.setRange(1, 512)
        form.addRow("Fixture type", self.profile)
        form.addRow("Fixture label", self.name)
        form.addRow("Universe", self.universe)
        form.addRow("Start address", self.address)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self, project_path: Path, data: dict[str, Any]):
        super().__init__()
        self.project_path = project_path
        self.data = data
        self.core = DmxCore(int(data["universes"]))
        self.status_relay = StatusRelay()
        self.status_relay.message.connect(self.statusBar().showMessage)
        self.output = OutputService(
            self.core, self.status_relay.message.emit, lambda: self.core.universes
        )
        self.osc_input: OscInputService | None = None
        self.midi: MidiService | None = None
        self.effect_started = 0.0
        self.setWindowTitle("LumenDesk — DMX lighting control")
        self.resize(1180, 800)
        self.setMinimumSize(900, 650)
        self._build_ui()
        self._refresh_live()
        self._refresh_fixture_tables()
        self._refresh_effects()
        self._restore_connection_fields()
        self.live_refresh_timer = QTimer(self)
        self.live_refresh_timer.setInterval(100)
        self.live_refresh_timer.timeout.connect(self._refresh_live)
        self.live_refresh_timer.start()
        self.effect_timer = QTimer(self)
        self.effect_timer.setInterval(33)
        self.effect_timer.timeout.connect(self._effect_tick)
        self.effect_timer.start()
        self.statusBar().showMessage("Ready · 100 universes available")

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._live_tab(), "Live")
        tabs.addTab(self._fixtures_tab(), "Fixtures")
        tabs.addTab(self._effects_tab(), "Effects")
        tabs.addTab(self._connections_tab(), "Connections")
        self.setCentralWidget(tabs)

    def _live_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        header = QHBoxLayout()
        title = QLabel("LIVE OUTPUT")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("Universe"))
        self.live_universe = QSpinBox()
        self.live_universe.setRange(1, self.core.universes)
        self.live_universe.valueChanged.connect(self._refresh_live)
        header.addWidget(self.live_universe)
        layout.addLayout(header)
        layout.addWidget(QLabel("Select a channel value to edit. Values update the active DMX output immediately."))
        self.channel_table = QTableWidget(512, 2)
        self.channel_table.setHorizontalHeaderLabels(["DMX channel", "Value"])
        self.channel_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.channel_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.channel_table.verticalHeader().setVisible(False)
        self.channel_table.verticalHeader().setDefaultSectionSize(34)
        for row in range(512):
            number = QTableWidgetItem(str(row + 1))
            number.setFlags(number.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.channel_table.setItem(row, 0, number)
            self.channel_table.setItem(row, 1, QTableWidgetItem("0"))
        self.channel_table.itemChanged.connect(self._live_value_changed)
        layout.addWidget(self.channel_table)
        return page

    def _fixtures_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel("Create your own fixture channel maps, then patch instances into a universe.")
        layout.addWidget(intro)
        columns = QHBoxLayout()
        profile_box = QGroupBox("Fixture library")
        profile_layout = QVBoxLayout(profile_box)
        self.profile_table = QTableWidget(0, 3)
        self.profile_table.setHorizontalHeaderLabels(["Name", "Manufacturer", "Channels"])
        self.profile_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.profile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.profile_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        profile_layout.addWidget(self.profile_table)
        profile_buttons = QHBoxLayout()
        add_profile = QPushButton("New fixture profile")
        edit_profile = QPushButton("Edit profile")
        delete_profile = QPushButton("Delete profile")
        add_profile.clicked.connect(self._add_profile)
        edit_profile.clicked.connect(self._edit_profile)
        delete_profile.clicked.connect(self._delete_profile)
        for button in (add_profile, edit_profile, delete_profile):
            profile_buttons.addWidget(button)
        profile_layout.addLayout(profile_buttons)
        patch_box = QGroupBox("Patched fixtures")
        patch_layout = QVBoxLayout(patch_box)
        self.fixture_table = QTableWidget(0, 4)
        self.fixture_table.setHorizontalHeaderLabels(["Label", "Fixture type", "Universe", "Address"])
        self.fixture_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.fixture_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.fixture_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        patch_layout.addWidget(self.fixture_table)
        patch_buttons = QHBoxLayout()
        patch = QPushButton("Patch fixture")
        unpatch = QPushButton("Unpatch selected")
        patch.clicked.connect(self._patch_fixture)
        unpatch.clicked.connect(self._unpatch_fixture)
        patch_buttons.addWidget(patch)
        patch_buttons.addWidget(unpatch)
        patch_layout.addLayout(patch_buttons)
        columns.addWidget(profile_box)
        columns.addWidget(patch_box)
        layout.addLayout(columns)
        return page

    def _effects_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Choose a built-in or saved effect, target a fixture, and press Run."))
        self.effect_table = QTableWidget(0, 3)
        self.effect_table.setHorizontalHeaderLabels(["Effect", "Pattern", "Speed"])
        self.effect_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.effect_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.effect_table)
        target_form = QFormLayout()
        self.effect_fixture = QComboBox()
        self.effect_attributes = QListWidget()
        self.effect_attributes.setMaximumHeight(130)
        self.effect_attributes.itemChanged.connect(self._save_project)
        target_form.addRow("Target fixture", self.effect_fixture)
        target_form.addRow("Affected attributes", self.effect_attributes)
        layout.addLayout(target_form)
        editor = QGroupBox("Effect creator")
        form = QFormLayout(editor)
        self.effect_name = QLineEdit()
        self.effect_pattern = QComboBox()
        self.effect_pattern.addItems(EFFECTS)
        self.effect_speed = QDoubleSpinBox()
        self.effect_speed.setRange(0.05, 20.0)
        self.effect_speed.setSingleStep(0.1)
        self.effect_speed.setValue(1.0)
        self.effect_intensity = QSpinBox()
        self.effect_intensity.setRange(0, 255)
        self.effect_intensity.setValue(255)
        form.addRow("Effect name", self.effect_name)
        form.addRow("Pattern", self.effect_pattern)
        form.addRow("Speed (cycles/sec)", self.effect_speed)
        form.addRow("Intensity", self.effect_intensity)
        layout.addWidget(editor)
        buttons = QHBoxLayout()
        save_effect = QPushButton("Save effect")
        run_effect = QPushButton("Run selected effect")
        stop_effect = QPushButton("Stop")
        save_effect.clicked.connect(self._save_effect)
        run_effect.clicked.connect(self._run_effect)
        stop_effect.clicked.connect(self._stop_effect)
        buttons.addWidget(save_effect)
        buttons.addWidget(run_effect)
        buttons.addWidget(stop_effect)
        layout.addLayout(buttons)
        self.effect_table.itemSelectionChanged.connect(self._load_effect_editor)
        self.effect_fixture.currentIndexChanged.connect(self._refresh_effect_attributes)
        return page

    def _connections_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Select a DMX output protocol. Art-Net and sACN stream all configured universes at 30 Hz."))
        output_box = QGroupBox("DMX output")
        output_layout = QFormLayout(output_box)
        self.universe_count = QSpinBox()
        self.universe_count.setRange(1, MAX_UNIVERSES)
        self.universe_count.setValue(self.core.universes)
        apply_universes = QPushButton("Apply universe count")
        apply_universes.clicked.connect(self._resize_universes)
        output_layout.addRow("Configured universes", self.universe_count)
        output_layout.addRow(apply_universes)
        self.output_protocol = QComboBox()
        self.output_protocol.addItems(["Disabled", "Art-Net", "sACN", "OpenDMX", "OSC"])
        self.output_destination = QLineEdit()
        self.output_destination.setPlaceholderText("Broadcast or destination IP")
        self.serial_port = QLineEdit()
        self.serial_port.setPlaceholderText("COM3 or /dev/ttyUSB0")
        self.osc_send_port = QSpinBox()
        self.osc_send_port.setRange(1, 65535)
        self.osc_send_port.setValue(9001)
        self.osc_universe = QSpinBox()
        self.osc_universe.setRange(1, self.core.universes)
        self.osc_universe.setValue(1)
        output_layout.addRow("Protocol", self.output_protocol)
        output_layout.addRow("Destination / network", self.output_destination)
        output_layout.addRow("OpenDMX serial port", self.serial_port)
        output_layout.addRow("OSC destination port", self.osc_send_port)
        output_layout.addRow("OSC universe", self.osc_universe)
        self.output_button = QPushButton("Start output")
        self.output_button.setCheckable(True)
        self.output_button.toggled.connect(self._toggle_output)
        output_layout.addRow(self.output_button)
        layout.addWidget(output_box)

        osc_box = QGroupBox("OSC input")
        osc_layout = QFormLayout(osc_box)
        self.osc_listen = QCheckBox("Listen for OSC DMX channel messages")
        self.osc_listen_port = QSpinBox()
        self.osc_listen_port.setRange(1, 65535)
        self.osc_listen_port.setValue(9000)
        self.osc_listen.toggled.connect(self._toggle_osc_input)
        osc_layout.addRow(self.osc_listen)
        osc_layout.addRow("Listen UDP port", self.osc_listen_port)
        osc_layout.addRow(QLabel("Address format: /lumendesk/universe/1/channel/1 (integer 0–255, or float 0–1)."))
        layout.addWidget(osc_box)

        midi_box = QGroupBox("MIDI CC mapping")
        midi_layout = QFormLayout(midi_box)
        self.midi_input = QComboBox()
        self.midi_output = QComboBox()
        self.midi_channel = QSpinBox()
        self.midi_channel.setRange(1, 16)
        self.midi_cc = QSpinBox()
        self.midi_cc.setRange(0, 127)
        self.midi_universe = QSpinBox()
        self.midi_universe.setRange(1, self.core.universes)
        self.midi_dmx_channel = QSpinBox()
        self.midi_dmx_channel.setRange(1, 512)
        refresh_midi = QPushButton("Refresh MIDI devices")
        connect_midi = QPushButton("Connect MIDI")
        refresh_midi.clicked.connect(self._refresh_midi_devices)
        connect_midi.clicked.connect(self._connect_midi)
        midi_layout.addRow("MIDI input (optional)", self.midi_input)
        midi_layout.addRow("MIDI output (optional)", self.midi_output)
        midi_layout.addRow("MIDI channel", self.midi_channel)
        midi_layout.addRow("CC number", self.midi_cc)
        midi_layout.addRow("DMX target universe", self.midi_universe)
        midi_layout.addRow("DMX target channel", self.midi_dmx_channel)
        midi_layout.addRow(refresh_midi)
        midi_layout.addRow(connect_midi)
        layout.addWidget(midi_box)
        layout.addStretch()
        self._refresh_midi_devices()
        return page

    def _restore_connection_fields(self) -> None:
        output = self.data.get("output", {})
        self.output_protocol.setCurrentText(output.get("protocol", "Disabled"))
        self.output_destination.setText(output.get("destination", ""))
        self.serial_port.setText(output.get("serial_port", ""))
        osc = self.data.get("osc", {})
        self.osc_listen.setChecked(bool(osc.get("listen", False)))
        self.osc_listen_port.setValue(int(osc.get("listen_port", 9000)))
        self.osc_send_port.setValue(int(osc.get("send_port", 9001)))
        self.osc_universe.setValue(min(self.core.universes, int(osc.get("universe", 1))))
        midi = self.data.get("midi", {})
        self.midi_channel.setValue(int(midi.get("channel", 1)))
        self.midi_cc.setValue(int(midi.get("cc", 1)))
        self.midi_universe.setValue(min(self.core.universes, int(midi.get("universe", 1))))
        self.midi_dmx_channel.setValue(int(midi.get("dmx_channel", 1)))
        self._select_combo_text(self.midi_input, midi.get("input", ""))
        self._select_combo_text(self.midi_output, midi.get("output", ""))
        if self.osc_listen.isChecked():
            self._toggle_osc_input(True)

    @staticmethod
    def _select_combo_text(combo: QComboBox, text: str) -> None:
        if text and combo.findText(text) < 0:
            combo.addItem(text)
        combo.setCurrentText(text)

    def _refresh_live(self, *_: Any) -> None:
        if not hasattr(self, "channel_table"):
            return
        universe = self.live_universe.value() - 1
        self.channel_table.blockSignals(True)
        for channel in range(512):
            self.channel_table.item(channel, 1).setText(
                str(self.core.get_channel(universe, channel))
            )
        self.channel_table.blockSignals(False)

    def _live_value_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        try:
            value = int(item.text())
        except ValueError:
            self.statusBar().showMessage("DMX values must be whole numbers from 0 to 255.")
            self._refresh_live()
            return
        if not 0 <= value <= 255:
            self.statusBar().showMessage("DMX values must be between 0 and 255.")
            self._refresh_live()
            return
        channel = item.row()
        universe = self.live_universe.value()
        self.core.set_channel(universe - 1, channel, value)
        if (
            self.midi is not None
            and self.midi_universe.value() == universe
            and self.midi_dmx_channel.value() == channel + 1
        ):
            self.midi.send_value(value)

    def _refresh_fixture_tables(self) -> None:
        self.profile_table.setRowCount(len(self.data["profiles"]))
        for row, profile in enumerate(self.data["profiles"]):
            values = (profile["name"], profile.get("manufacturer", ""), str(len(profile["channels"])))
            for column, value in enumerate(values):
                self.profile_table.setItem(row, column, QTableWidgetItem(value))
        self.fixture_table.setRowCount(len(self.data["fixtures"]))
        for row, fixture in enumerate(self.data["fixtures"]):
            profile = self._profile(fixture["profile"])
            values = (
                fixture["name"], profile["name"] if profile else "Missing profile",
                str(fixture["universe"]), str(fixture["address"]),
            )
            for column, value in enumerate(values):
                self.fixture_table.setItem(row, column, QTableWidgetItem(value))
        self._refresh_effect_targets()

    def _profile(self, name: str) -> dict[str, Any] | None:
        return next((profile for profile in self.data["profiles"] if profile["name"] == name), None)

    def _add_profile(self) -> None:
        dialog = FixtureProfileDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            profile = dialog.profile()
            if not profile["name"] or not profile["channels"]:
                QMessageBox.warning(self, "Incomplete fixture", "Enter a fixture name and at least one channel.")
                return
            if self._profile(profile["name"]):
                QMessageBox.warning(self, "Duplicate name", "Fixture profile names must be unique.")
                return
            self.data["profiles"].append(profile)
            self._save_project()
            self._refresh_fixture_tables()

    def _edit_profile(self) -> None:
        row = self.profile_table.currentRow()
        if row < 0:
            return
        old_profile = self.data["profiles"][row]
        dialog = FixtureProfileDialog(self, old_profile)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = dialog.profile()
        if not profile["name"] or not profile["channels"]:
            QMessageBox.warning(self, "Incomplete fixture", "Enter a fixture name and at least one channel.")
            return
        if any(item["name"] == profile["name"] for index, item in enumerate(self.data["profiles"]) if index != row):
            QMessageBox.warning(self, "Duplicate name", "Fixture profile names must be unique.")
            return
        old_name = old_profile["name"]
        candidate_profiles = list(self.data["profiles"])
        candidate_profiles[row] = profile
        candidate_fixtures = [
            {
                **fixture,
                "profile": profile["name"] if fixture["profile"] == old_name else fixture["profile"],
            }
            for fixture in self.data["fixtures"]
        ]
        layout_error = self._patch_layout_error(candidate_profiles, candidate_fixtures)
        if layout_error:
            QMessageBox.warning(self, "Invalid fixture layout", layout_error)
            return
        self.data["profiles"] = candidate_profiles
        self.data["fixtures"] = candidate_fixtures
        self._save_project()
        self._refresh_fixture_tables()

    def _delete_profile(self) -> None:
        row = self.profile_table.currentRow()
        if row < 0:
            return
        name = self.data["profiles"][row]["name"]
        if any(fixture["profile"] == name for fixture in self.data["fixtures"]):
            QMessageBox.warning(self, "Profile in use", "Unpatch its fixtures before deleting this profile.")
            return
        del self.data["profiles"][row]
        self._save_project()
        self._refresh_fixture_tables()

    def _patch_fixture(self) -> None:
        if not self.data["profiles"]:
            QMessageBox.information(self, "No fixture profiles", "Create a fixture profile before patching fixtures.")
            return
        dialog = PatchFixtureDialog(self.data["profiles"], self.core.universes, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = self.data["profiles"][dialog.profile.currentIndex()]
        name = dialog.name.text().strip() or f"{profile['name']} {len(self.data['fixtures']) + 1}"
        if any(fixture["name"] == name for fixture in self.data["fixtures"]):
            QMessageBox.warning(self, "Duplicate fixture label", "Patched fixture labels must be unique.")
            return
        universe = dialog.universe.value()
        fixture = {
            "name": name, "profile": profile["name"], "universe": universe,
            "address": dialog.address.value(),
        }
        candidate_fixtures = [*self.data["fixtures"], fixture]
        layout_error = self._patch_layout_error(self.data["profiles"], candidate_fixtures)
        if layout_error:
            QMessageBox.warning(self, "Invalid fixture patch", layout_error)
            return
        self.data["fixtures"] = candidate_fixtures
        self._save_project()
        self._refresh_fixture_tables()

    @staticmethod
    def _patch_layout_error(
        profiles: list[dict[str, Any]], fixtures: list[dict[str, Any]]
    ) -> str | None:
        profile_by_name = {profile["name"]: profile for profile in profiles}
        occupied: list[tuple[int, int, int, str]] = []
        for fixture in fixtures:
            profile = profile_by_name.get(fixture["profile"])
            if profile is None:
                return f"{fixture['name']} refers to missing profile {fixture['profile']}."
            first = int(fixture["address"])
            last = first + len(profile["channels"]) - 1
            if first < 1 or last > 512:
                return f"{fixture['name']} extends outside channels 1–512."
            for universe, other_first, other_last, other_name in occupied:
                if (
                    universe == fixture["universe"]
                    and first <= other_last
                    and other_first <= last
                ):
                    return (
                        f"{fixture['name']} overlaps {other_name} "
                        f"on channels {max(first, other_first)}–{min(last, other_last)}."
                    )
            occupied.append((fixture["universe"], first, last, fixture["name"]))
        return None

    def _unpatch_fixture(self) -> None:
        row = self.fixture_table.currentRow()
        if row >= 0:
            del self.data["fixtures"][row]
            self._save_project()
            self._refresh_fixture_tables()

    def _refresh_effect_targets(self) -> None:
        if not hasattr(self, "effect_fixture"):
            return
        selected = self.effect_fixture.currentText()
        self.effect_fixture.blockSignals(True)
        self.effect_fixture.clear()
        self.effect_fixture.addItems([fixture["name"] for fixture in self.data["fixtures"]])
        if selected:
            self.effect_fixture.setCurrentText(selected)
        self.effect_fixture.blockSignals(False)
        self._refresh_effect_attributes()

    def _refresh_effect_attributes(self, *_: Any) -> None:
        if not hasattr(self, "effect_attributes"):
            return
        fixture = next(
            (item for item in self.data["fixtures"] if item["name"] == self.effect_fixture.currentText()),
            None,
        )
        profile = self._profile(fixture["profile"]) if fixture else None
        self.effect_attributes.clear()
        if profile:
            for name in profile["channels"]:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.effect_attributes.addItem(item)

    def _refresh_effects(self) -> None:
        self.effect_table.setRowCount(len(self.data["effects"]))
        for row, effect in enumerate(self.data["effects"]):
            for column, value in enumerate((effect["name"], effect["pattern"], str(effect["speed"]))):
                self.effect_table.setItem(row, column, QTableWidgetItem(value))

    def _load_effect_editor(self) -> None:
        row = self.effect_table.currentRow()
        if 0 <= row < len(self.data["effects"]):
            effect = self.data["effects"][row]
            self.effect_name.setText(effect["name"])
            self.effect_pattern.setCurrentText(effect["pattern"])
            self.effect_speed.setValue(float(effect["speed"]))
            self.effect_intensity.setValue(int(effect.get("intensity", 255)))

    def _save_effect(self) -> None:
        name = self.effect_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Effect name required", "Give this effect a name before saving.")
            return
        effect = {
            "name": name, "pattern": self.effect_pattern.currentText(),
            "speed": self.effect_speed.value(), "intensity": self.effect_intensity.value(),
        }
        found = next((i for i, saved in enumerate(self.data["effects"]) if saved["name"] == name), None)
        if found is None:
            self.data["effects"].append(effect)
        else:
            self.data["effects"][found] = effect
        self._save_project()
        self._refresh_effects()
        self.statusBar().showMessage(f"Saved effect “{name}”.")

    def _run_effect(self) -> None:
        fixture = next(
            (item for item in self.data["fixtures"] if item["name"] == self.effect_fixture.currentText()),
            None,
        )
        row = self.effect_table.currentRow()
        if fixture is None or row < 0:
            QMessageBox.information(self, "Select a target", "Choose an effect and a patched target fixture.")
            return
        profile = self._profile(fixture["profile"])
        if profile is None:
            QMessageBox.warning(self, "Missing fixture profile", "Re-create the fixture profile for this patch.")
            return
        selected = [
            index for index in range(self.effect_attributes.count())
            if self.effect_attributes.item(index).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            selected = list(range(len(profile["channels"])))
        self.active_effect = dict(self.data["effects"][row])
        self.active_fixture = dict(fixture)
        self.active_attributes = selected
        self.effect_started = time.monotonic()
        self.statusBar().showMessage(f"Running {self.active_effect['name']} on {fixture['name']}.")

    def _stop_effect(self) -> None:
        self.active_effect = None
        self.statusBar().showMessage("Effect stopped; last DMX values are held.")

    def _effect_tick(self) -> None:
        effect = getattr(self, "active_effect", None)
        fixture = getattr(self, "active_fixture", None)
        if not effect or not fixture:
            return
        profile = self._profile(fixture["profile"])
        if not profile:
            return
        pattern = EFFECTS.get(effect["pattern"])
        attributes = self.active_attributes
        elapsed = time.monotonic() - self.effect_started
        for position, attribute_index in enumerate(attributes):
            value = self.core.effect_value(
                pattern, position, len(attributes), elapsed,
                float(effect["speed"]), int(effect["intensity"]),
            )
            self.core.set_channel(
                fixture["universe"] - 1,
                fixture["address"] - 1 + attribute_index,
                value,
            )
            if (
                self.midi is not None
                and fixture["universe"] == self.midi_universe.value()
                and fixture["address"] + attribute_index == self.midi_dmx_channel.value()
            ):
                self.midi.send_value(value)
        if fixture["universe"] == self.live_universe.value():
            self._refresh_live()

    def _toggle_output(self, enabled: bool) -> None:
        self.output_button.setText("Stop output" if enabled else "Start output")
        if enabled:
            protocol = self.output_protocol.currentText()
            self.data["output"] = {
                "protocol": protocol,
                "destination": self.output_destination.text().strip(),
                "serial_port": self.serial_port.text().strip(),
            }
            self.data["osc"].update(
                send_port=self.osc_send_port.value(), universe=self.osc_universe.value()
            )
            try:
                self.output.start(
                    protocol,
                    self.output_destination.text().strip(),
                    self.serial_port.text().strip(),
                    self.osc_send_port.value(),
                    self.osc_universe.value(),
                )
            except (OSError, ValueError, RuntimeError) as error:
                self.output_button.setChecked(False)
                QMessageBox.critical(self, "Could not start output", str(error))
        else:
            self.output.stop()
        self._save_project()

    def _resize_universes(self) -> None:
        new_count = self.universe_count.value()
        old_count = self.core.universes
        if new_count == old_count:
            return
        if any(fixture["universe"] > new_count for fixture in self.data["fixtures"]):
            QMessageBox.warning(
                self, "Fixtures outside range",
                "Unpatch fixtures above the new universe count before reducing universes.",
            )
            self.universe_count.setValue(old_count)
            return
        if QMessageBox.question(
            self, "Change universe count",
            f"Change from {old_count} to {new_count} universes? Current DMX values will be preserved.",
        ) != QMessageBox.StandardButton.Yes:
            self.universe_count.setValue(old_count)
            return
        running_output = self.output_button.isChecked()
        listen_osc = self.osc_input is not None
        values = [self.core.copy_universe(index) for index in range(old_count)]
        self.output.stop()
        if self.midi is not None:
            self.midi.close()
            self.midi = None
        if self.osc_input is not None:
            self.osc_input.stop()
            self.osc_input = None
        self.core = DmxCore(new_count)
        for universe, packet in enumerate(values):
            for channel, value in enumerate(packet):
                self.core.set_channel(universe, channel, value)
        self.output = OutputService(
            self.core, self.status_relay.message.emit, lambda: self.core.universes
        )
        self.data["universes"] = new_count
        self.data["osc"]["universe"] = min(new_count, int(self.data["osc"].get("universe", 1)))
        self.data["midi"]["universe"] = min(new_count, int(self.data["midi"].get("universe", 1)))
        self.live_universe.setRange(1, new_count)
        self.osc_universe.setRange(1, new_count)
        self.midi_universe.setRange(1, new_count)
        self._refresh_live()
        if listen_osc:
            self._toggle_osc_input(True)
        if running_output:
            self.output.start(
                self.output_protocol.currentText(),
                self.output_destination.text().strip(),
                self.serial_port.text().strip(),
                self.osc_send_port.value(),
                self.osc_universe.value(),
            )
        if self.data["midi"]["input"] or self.data["midi"]["output"]:
            self.statusBar().showMessage("Universe count updated. Reconnect MIDI to resume its mapping.")
        else:
            self.statusBar().showMessage(f"Universe count updated to {new_count}.")
        self._save_project()

    def _toggle_osc_input(self, enabled: bool) -> None:
        if self.osc_input is not None:
            self.osc_input.stop()
            self.osc_input = None
        self.data["osc"].update(listen=enabled, listen_port=self.osc_listen_port.value())
        if enabled:
            try:
                self.osc_input = OscInputService(
                    self.core, self.status_relay.message.emit, self.osc_listen_port.value()
                )
            except (OSError, ValueError) as error:
                self.osc_listen.blockSignals(True)
                self.osc_listen.setChecked(False)
                self.osc_listen.blockSignals(False)
                QMessageBox.critical(self, "Could not start OSC input", str(error))
        self._save_project()

    def _refresh_midi_devices(self) -> None:
        try:
            inputs, outputs = MidiService.port_names()
        except RuntimeError as error:
            self.statusBar().showMessage(str(error))
            return
        current_input, current_output = self.midi_input.currentText(), self.midi_output.currentText()
        self.midi_input.clear()
        self.midi_output.clear()
        self.midi_input.addItem("")
        self.midi_output.addItem("")
        self.midi_input.addItems(inputs)
        self.midi_output.addItems(outputs)
        self._select_combo_text(self.midi_input, current_input)
        self._select_combo_text(self.midi_output, current_output)

    def _connect_midi(self) -> None:
        if self.midi is not None:
            self.midi.close()
            self.midi = None
        self.data["midi"] = {
            "input": self.midi_input.currentText(), "output": self.midi_output.currentText(),
            "channel": self.midi_channel.value(), "cc": self.midi_cc.value(),
            "universe": self.midi_universe.value(), "dmx_channel": self.midi_dmx_channel.value(),
        }
        if not self.data["midi"]["input"] and not self.data["midi"]["output"]:
            QMessageBox.information(self, "Choose a MIDI device", "Select at least one MIDI input or output device.")
            return
        try:
            self.midi = MidiService(
                self.core, self.status_relay.message.emit,
                self.data["midi"]["input"], self.data["midi"]["output"],
                self.midi_channel.value() - 1, self.midi_cc.value(),
                self.midi_universe.value(), self.midi_dmx_channel.value(),
            )
            self._save_project()
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.critical(self, "Could not connect MIDI", str(error))

    def _save_project(self, *_: Any) -> None:
        try:
            temporary = self.project_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            temporary.replace(self.project_path)
        except OSError as error:
            self.statusBar().showMessage(f"Could not save project settings: {error}")

    def closeEvent(self, event: Any) -> None:
        self.live_refresh_timer.stop()
        self.effect_timer.stop()
        self.output.stop()
        if self.osc_input is not None:
            self.osc_input.stop()
        if self.midi is not None:
            self.midi.close()
        event.accept()


def _load_project(path: Path) -> dict[str, Any]:
    if not path.exists():
        data = _default_project()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not load project file {path}: {error}") from error
    defaults = _default_project()
    for key, value in defaults.items():
        loaded.setdefault(key, value)
    if not isinstance(loaded["universes"], int) or not 1 <= loaded["universes"] <= MAX_UNIVERSES:
        raise ValueError(f"Saved universe count must be between 1 and {MAX_UNIVERSES}.")
    return loaded


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("LumenDesk")
    app.setApplicationName("LumenDesk")
    app.setFont(QFont("Segoe UI", 11))
    app.setStyleSheet(
        """
        QWidget { background: #171a20; color: #e7eaf0; }
        QTabWidget::pane { border: 1px solid #343a46; }
        QTabBar::tab { min-height: 42px; padding: 5px 18px; background: #242a33; }
        QTabBar::tab:selected { background: #34445a; color: #ffffff; }
        QPushButton { min-height: 42px; padding: 4px 14px; background: #293443;
                      border: 1px solid #46556a; border-radius: 5px; }
        QPushButton:hover { background: #35465d; }
        QPushButton:checked { background: #187b85; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: 40px; padding: 2px 8px;
                      background: #20252d; border: 1px solid #414957; }
        QTableWidget, QListWidget { background: #1e232b; alternate-background-color: #252c36;
                      gridline-color: #353c48; }
        QHeaderView::section { min-height: 38px; background: #29313d; padding: 4px; }
        QGroupBox { border: 1px solid #414957; border-radius: 5px; margin-top: 12px; padding: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QLabel#sectionTitle { font-size: 18px; font-weight: bold; color: #6fd3d4; }
        """
    )
    try:
        path = _project_path()
        window = MainWindow(path, _load_project(path))
        window.show()
        return app.exec()
    except (OSError, RuntimeError, ValueError) as error:
        QMessageBox.critical(None, "LumenDesk startup failed", str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
