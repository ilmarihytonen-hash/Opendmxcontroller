from __future__ import annotations

import socket
import threading
import time
from typing import Callable

from .native import DmxCore
from .controls import make_osc_message
from .protocols import make_artnet_packet, make_sacn_packet, sacn_multicast_address


class OutputService:
    def __init__(
        self,
        core: DmxCore,
        status_callback: Callable[[str], None],
        universes_callback: Callable[[], int],
    ) -> None:
        self._core = core
        self._status_callback = status_callback
        self._universes_callback = universes_callback
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._configuration: dict[str, str] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        protocol: str,
        destination: str,
        serial_port: str,
        osc_port: int = 9001,
        osc_universe: int = 1,
    ) -> None:
        self.stop()
        if protocol == "Disabled":
            return
        with self._lock:
            self._configuration = {
                "protocol": protocol,
                "destination": destination,
                "serial_port": serial_port,
                "osc_port": str(osc_port),
                "osc_universe": str(osc_universe),
            }
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="LumenDeskOutput", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                self._status_callback("Output worker did not stop within 2 seconds.")
            self._thread = None

    def _run(self) -> None:
        sock: socket.socket | None = None
        serial = None
        sequence = 1
        try:
            with self._lock:
                config = dict(self._configuration)
            protocol = config["protocol"]
            if protocol in ("Art-Net", "sACN"):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                if protocol == "Art-Net":
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    destination = config["destination"] or "255.255.255.255"
                    port = 6454
                else:
                    destination = config["destination"]
                    multicast = not destination
                    port = 5568
            elif protocol == "OSC":
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                destination = config["destination"] or "127.0.0.1"
                port = int(config.get("osc_port", "9001"))
                previous: dict[tuple[int, int], int] = {}
            elif protocol == "OpenDMX":
                if not config["serial_port"].strip():
                    raise ValueError("Enter a serial port for OpenDMX (for example COM3 or /dev/ttyUSB0).")
                try:
                    import serial
                except ImportError as error:
                    raise RuntimeError("OpenDMX output requires pyserial; install requirements.txt.") from error
                serial = serial.Serial(
                    config["serial_port"], baudrate=250000, bytesize=8,
                    parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                    timeout=0.1, write_timeout=1,
                )
            else:
                raise ValueError(f"Unsupported output protocol: {protocol}")

            self._status_callback(f"{protocol} output is running.")
            if protocol == "Art-Net" and self._universes_callback() > 32768:
                self._status_callback(
                    "Art-Net supports universes 1–32768; higher configured universes are not sent."
                )
            while not self._stop.is_set():
                started = time.monotonic()
                universe_count = self._universes_callback()
                if protocol == "OpenDMX":
                    serial.break_condition = True
                    time.sleep(0.0001)
                    serial.break_condition = False
                    serial.write(b"\x00" + self._core.copy_universe(0))
                elif protocol == "OSC":
                    selected_universe = max(
                        1, min(universe_count, int(config.get("osc_universe", "1")))
                    )
                    data = self._core.copy_universe(selected_universe - 1)
                    for channel, value in enumerate(data, start=1):
                        key = (selected_universe, channel)
                        if previous.get(key) != value:
                            sock.sendto(
                                make_osc_message(
                                    f"/lumendesk/universe/{selected_universe}/channel/{channel}",
                                    value,
                                ),
                                (destination, port),
                            )
                            previous[key] = value
                else:
                    send_count = min(universe_count, 32768) if protocol == "Art-Net" else universe_count
                    for index in range(send_count):
                        if self._stop.is_set():
                            break
                        data = self._core.copy_universe(index)
                        if protocol == "Art-Net":
                            packet = make_artnet_packet(index + 1, data, sequence)
                            target = destination
                        else:
                            packet = make_sacn_packet(index + 1, data, sequence)
                            target = (
                                sacn_multicast_address(index + 1)
                                if multicast else destination
                            )
                        sock.sendto(packet, (target, port))
                sequence = (sequence + 1) % 256 or 1
                self._stop.wait(max(0.0, 1.0 / 30.0 - (time.monotonic() - started)))
        except (OSError, ValueError, RuntimeError) as error:
            self._status_callback(f"Output stopped: {error}")
        finally:
            if serial is not None:
                serial.close()
            if sock is not None:
                sock.close()
