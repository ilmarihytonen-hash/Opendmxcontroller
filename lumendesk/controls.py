from __future__ import annotations

import socket
import struct
import threading
import os
from typing import Any, Callable

from .native import DmxCore


def make_osc_message(address: str, value: int | float) -> bytes:
    if not address.startswith("/"):
        raise ValueError("OSC addresses must begin with '/'.")
    encoded_address = address.encode("utf-8") + b"\x00"
    encoded_address += b"\x00" * (-len(encoded_address) % 4)
    if isinstance(value, int):
        tag, argument = b",i\x00\x00", struct.pack(">i", value)
    else:
        tag, argument = b",f\x00\x00", struct.pack(">f", value)
    return encoded_address + tag + argument


def parse_osc_message(packet: bytes) -> tuple[str, int | float]:
    def read_string(offset: int) -> tuple[str, int]:
        end = packet.find(b"\x00", offset)
        if end < 0:
            raise ValueError("Malformed OSC string.")
        text = packet[offset:end].decode("utf-8")
        return text, (end + 4) & ~3

    address, offset = read_string(0)
    tags, offset = read_string(offset)
    if len(tags) < 2 or tags[0] != ",":
        raise ValueError("OSC type tag is missing.")
    if tags[1] == "i" and len(packet) >= offset + 4:
        return address, struct.unpack_from(">i", packet, offset)[0]
    if tags[1] == "f" and len(packet) >= offset + 4:
        return address, struct.unpack_from(">f", packet, offset)[0]
    raise ValueError("Only OSC integer and float channel values are supported.")


class OscInputService:
    def __init__(
        self,
        core: DmxCore,
        status_callback: Callable[[str], None],
        port: int = 9000,
    ) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("OSC listen port must be between 1 and 65535.")
        self._core = core
        self._status_callback = status_callback
        self._port = port
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="LumenDeskOSC", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.25)
            sock.bind(("0.0.0.0", self._port))
            self._status_callback(f"OSC input listening on UDP {self._port}.")
            while not self._stop.is_set():
                try:
                    packet, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                try:
                    address, value = parse_osc_message(packet)
                    parts = address.strip("/").split("/")
                    if (
                        len(parts) != 5
                        or parts[0] != "lumendesk"
                        or parts[1] != "universe"
                        or parts[3] != "channel"
                    ):
                        continue
                    universe, channel = int(parts[2]), int(parts[4])
                    if not 1 <= universe <= self._core.universes or not 1 <= channel <= 512:
                        continue
                    numeric_value = round(value * 255) if isinstance(value, float) and 0 <= value <= 1 else round(value)
                    self._core.set_channel(universe - 1, channel - 1, numeric_value)
                except (ValueError, UnicodeDecodeError, struct.error) as error:
                    self._status_callback(f"Ignored invalid OSC input: {error}")
        except OSError as error:
            self._status_callback(f"OSC input stopped: {error}")
        finally:
            sock.close()


class _WindowsMidi:
    def __init__(
        self,
        input_name: str,
        output_name: str,
        message_callback: Callable[[int, int, int], None],
    ) -> None:
        import ctypes

        self._ctypes = ctypes
        self._winmm = ctypes.WinDLL("winmm", use_last_error=True)
        self._message_callback = message_callback
        self._input_handle = ctypes.c_void_p()
        self._output_handle = ctypes.c_void_p()
        self._callback_type = ctypes.WINFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
            ctypes.c_size_t, ctypes.c_size_t,
        )
        self._callback = self._callback_type(self._on_input)
        self._configure_functions()
        try:
            if output_name:
                self._check(
                    self._winmm.midiOutOpen(
                        ctypes.byref(self._output_handle), self._device_index(output_name),
                        0, 0, 0,
                    ),
                    "open MIDI output",
                )
            if input_name:
                self._check(
                    self._winmm.midiInOpen(
                        ctypes.byref(self._input_handle), self._device_index(input_name),
                        self._callback, 0, 0x00030000,
                    ),
                    "open MIDI input",
                )
                self._check(self._winmm.midiInStart(self._input_handle), "start MIDI input")
        except Exception:
            self.close()
            raise

    def _configure_functions(self) -> None:
        ctypes = self._ctypes
        uint = ctypes.c_uint
        handle = ctypes.c_void_p
        self._winmm.midiInOpen.argtypes = [
            ctypes.POINTER(handle), uint, self._callback_type, ctypes.c_size_t, uint,
        ]
        self._winmm.midiOutOpen.argtypes = [
            ctypes.POINTER(handle), uint, ctypes.c_size_t, ctypes.c_size_t, uint,
        ]
        self._winmm.midiInStart.argtypes = [handle]
        self._winmm.midiInStop.argtypes = [handle]
        self._winmm.midiInReset.argtypes = [handle]
        self._winmm.midiInClose.argtypes = [handle]
        self._winmm.midiOutClose.argtypes = [handle]
        self._winmm.midiOutShortMsg.argtypes = [handle, uint]
        for name in (
            "midiInOpen", "midiOutOpen", "midiInStart", "midiInStop",
            "midiInReset", "midiInClose", "midiOutClose", "midiOutShortMsg",
        ):
            getattr(self._winmm, name).restype = uint

    @staticmethod
    def _caps_type(ctypes: Any) -> type:
        class MidiCaps(ctypes.Structure):
            _fields_ = [
                ("manufacturer", ctypes.c_ushort),
                ("product", ctypes.c_ushort),
                ("driver_version", ctypes.c_uint),
                ("name", ctypes.c_wchar * 32),
                ("support", ctypes.c_uint),
            ]

        return MidiCaps

    @classmethod
    def port_names(cls) -> tuple[list[str], list[str]]:
        import ctypes

        winmm = ctypes.WinDLL("winmm", use_last_error=True)
        caps_type = cls._caps_type(ctypes)
        names: list[list[str]] = [[], []]
        for input_device, count_name, caps_name in (
            (True, "midiInGetNumDevs", "midiInGetDevCapsW"),
            (False, "midiOutGetNumDevs", "midiOutGetDevCapsW"),
        ):
            count_function = getattr(winmm, count_name)
            count_function.restype = ctypes.c_uint
            caps_function = getattr(winmm, caps_name)
            caps_function.argtypes = [ctypes.c_size_t, ctypes.POINTER(caps_type), ctypes.c_uint]
            caps_function.restype = ctypes.c_uint
            for index in range(count_function()):
                caps = caps_type()
                result = caps_function(index, ctypes.byref(caps), ctypes.sizeof(caps))
                if result:
                    raise RuntimeError(f"Could not read MIDI device {index} (MMRESULT {result}).")
                names[0 if input_device else 1].append(f"{index}: {caps.name}")
        return names[0], names[1]

    @staticmethod
    def _device_index(name: str) -> int:
        try:
            return int(name.split(":", 1)[0])
        except ValueError as error:
            raise ValueError(f"Invalid Windows MIDI device selection: {name}") from error

    def _check(self, result: int, operation: str) -> None:
        if result:
            raise RuntimeError(f"Could not {operation} (MMRESULT {result}).")

    def _on_input(
        self, _handle: object, message: int, _instance: int, packed: int, _timestamp: int
    ) -> None:
        if message == 0x3C3:
            status = packed & 0xFF
            if status & 0xF0 == 0xB0:
                self._message_callback((status & 0x0F), (packed >> 8) & 0x7F, (packed >> 16) & 0x7F)

    def send_cc(self, channel: int, control: int, value: int) -> None:
        if self._output_handle.value:
            packed = 0xB0 | channel | (control << 8) | (value << 16)
            self._check(
                self._winmm.midiOutShortMsg(self._output_handle, packed),
                "send MIDI Control Change",
            )

    def close(self) -> None:
        if self._input_handle.value:
            self._winmm.midiInReset(self._input_handle)
            self._winmm.midiInStop(self._input_handle)
            self._winmm.midiInClose(self._input_handle)
            self._input_handle = self._ctypes.c_void_p()
        if self._output_handle.value:
            self._winmm.midiOutClose(self._output_handle)
            self._output_handle = self._ctypes.c_void_p()


class MidiService:
    def __init__(
        self,
        core: DmxCore,
        status_callback: Callable[[str], None],
        input_name: str,
        output_name: str,
        midi_channel: int,
        cc_number: int,
        universe: int,
        channel: int,
    ) -> None:
        if not 0 <= midi_channel <= 15 or not 0 <= cc_number <= 127:
            raise ValueError("MIDI channel and CC number are out of range.")
        if not 1 <= universe <= core.universes or not 1 <= channel <= 512:
            raise ValueError("MIDI target must be within the configured DMX universes.")
        self._core = core
        self._status_callback = status_callback
        self._midi_channel = midi_channel
        self._cc_number = cc_number
        self._universe = universe - 1
        self._channel = channel - 1
        self._mido = None
        self._output = None
        self._input = None
        self._windows_backend = None
        if os.name == "nt":
            self._windows_backend = _WindowsMidi(
                input_name, output_name, self._on_control_change
            )
        else:
            try:
                import mido
            except ImportError as error:
                raise RuntimeError(
                    "MIDI support requires mido and python-rtmidi; install requirements.txt."
                ) from error
            self._mido = mido
            self._output = mido.open_output(output_name) if output_name else None
            try:
                self._input = (
                    mido.open_input(input_name, callback=self._on_message)
                    if input_name else None
                )
            except Exception:
                if self._output is not None:
                    self._output.close()
                raise
        self._status_callback("MIDI input/output connected.")

    @staticmethod
    def port_names() -> tuple[list[str], list[str]]:
        if os.name == "nt":
            return _WindowsMidi.port_names()
        try:
            import mido
        except ImportError as error:
            raise RuntimeError("MIDI support requires mido and python-rtmidi; install requirements.txt.") from error
        return mido.get_input_names(), mido.get_output_names()

    def _on_message(self, message: object) -> None:
        if (
            getattr(message, "type", None) == "control_change"
            and getattr(message, "channel", None) == self._midi_channel
            and getattr(message, "control", None) == self._cc_number
        ):
            self._on_control_change(
                int(message.channel), int(message.control), int(message.value)
            )

    def _on_control_change(self, channel: int, control: int, value: int) -> None:
        if channel == self._midi_channel and control == self._cc_number:
            self._core.set_channel(
                self._universe, self._channel, round(value * 255 / 127)
            )

    def send_value(self, value: int) -> None:
        scaled = round(max(0, min(255, value)) * 127 / 255)
        try:
            if self._windows_backend is not None:
                self._windows_backend.send_cc(self._midi_channel, self._cc_number, scaled)
            elif self._output is not None:
                message = self._mido.Message(
                    "control_change",
                    channel=self._midi_channel,
                    control=self._cc_number,
                    value=scaled,
                )
                self._output.send(message)
        except (OSError, RuntimeError) as error:
            self._status_callback(f"MIDI output error: {error}")

    def close(self) -> None:
        if self._windows_backend is not None:
            self._windows_backend.close()
        else:
            if self._input is not None:
                self._input.close()
            if self._output is not None:
                self._output.close()
