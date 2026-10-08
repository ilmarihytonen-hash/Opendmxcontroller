from __future__ import annotations

import ctypes
import os
from pathlib import Path

CHANNELS_PER_UNIVERSE = 512
MAX_UNIVERSES = 63999


def _library_candidates() -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    names = ("lumendesk_core.dll", "liblumendesk_core.dylib", "liblumendesk_core.so")
    directories = (root / "build", root / "build" / "Release", root / "native" / "build")
    return [root / name for name in names] + [
        directory / name for directory in directories for name in names
    ]


class DmxCore:
    def __init__(self, universes: int) -> None:
        library_path = next((path for path in _library_candidates() if path.is_file()), None)
        if library_path is None:
            searched = ", ".join(str(path) for path in _library_candidates())
            raise RuntimeError(
                "The C++ DMX engine is not built. Build it with CMake first "
                f"(searched: {searched})."
            )
        loader = ctypes.WinDLL if os.name == "nt" else ctypes.CDLL
        self._library = loader(str(library_path))
        self._library.dmx_initialize.argtypes = [ctypes.c_int]
        self._library.dmx_initialize.restype = ctypes.c_int
        self._library.dmx_set_channel.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self._library.dmx_get_channel.argtypes = [ctypes.c_int, ctypes.c_int]
        self._library.dmx_get_channel.restype = ctypes.c_int
        self._library.dmx_copy_universe.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int,
        ]
        self._library.dmx_copy_universe.restype = ctypes.c_int
        self._library.dmx_effect_value.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_double, ctypes.c_double, ctypes.c_int,
        ]
        self._library.dmx_effect_value.restype = ctypes.c_int
        if not self._library.dmx_initialize(universes):
            raise ValueError(f"Universe count must be between 1 and {MAX_UNIVERSES}.")
        self.universes = universes

    def set_channel(self, universe: int, channel: int, value: int) -> None:
        self._library.dmx_set_channel(universe, channel, value)

    def get_channel(self, universe: int, channel: int) -> int:
        return int(self._library.dmx_get_channel(universe, channel))

    def copy_universe(self, universe: int) -> bytes:
        buffer = (ctypes.c_uint8 * CHANNELS_PER_UNIVERSE)()
        copied = self._library.dmx_copy_universe(universe, buffer, len(buffer))
        if copied != CHANNELS_PER_UNIVERSE:
            raise RuntimeError(f"Could not read DMX universe {universe + 1}.")
        return bytes(buffer)

    def effect_value(
        self, effect: int, position: int, count: int,
        elapsed_seconds: float, speed: float, intensity: int,
    ) -> int:
        return int(
            self._library.dmx_effect_value(
                effect, position, count, elapsed_seconds, speed, intensity
            )
        )
