from __future__ import annotations
import asyncio
import json
import logging
import subprocess
import sys
import threading
from typing import AsyncGenerator
from scalesync_bridge.models import WeightReading, ScaleInfo
from scalesync_bridge.parsers.ohaus import OhausParser
from scalesync_bridge.config import BridgeConfig

logger = logging.getLogger(__name__)

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


class ScaleManager:
    def __init__(self, config: BridgeConfig | None = None):
        self.config = config or BridgeConfig()
        self.parser = OhausParser()
        self.serial_conn: serial.Serial | None = None if HAS_SERIAL else None
        self.scale_info: ScaleInfo | None = None
        self._connected = False
        self._closed = False
        self._latest_reading: WeightReading | None = None
        self._reading_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()

    # Known USB-serial adapter VIDs used with OHAUS scales
    KNOWN_VIDS = [
        0x1A86,  # CH340/CH341
        0x0403,  # FTDI
        0x067B,  # Prolific PL2303
        0x10C4,  # Silicon Labs CP210x
    ]

    async def auto_detect(self) -> ScaleInfo | None:
        if not HAS_SERIAL:
            logger.warning("pyserial not available — running in simulation mode")
            return None

        if self.config.serial_port:
            logger.info(f"Using configured port: {self.config.serial_port}")
            return await self._try_connect(self.config.serial_port)

        ports = list(serial.tools.list_ports.comports())
        if not ports:
            logger.warning("No serial ports found on this computer")
            return None

        # Split into priority (known USB-serial adapters) and other ports
        priority = []
        other = []
        for p in ports:
            if p.vid and p.vid in self.KNOWN_VIDS:
                priority.append(p)
            else:
                other.append(p)

        if priority:
            names = ", ".join(f"{p.device} ({p.description})" for p in priority)
            logger.info(f"Found USB-serial adapter(s): {names}")
        if other:
            names = ", ".join(p.device for p in other)
            logger.debug(f"Other serial ports (lower priority): {names}")

        # Try known adapters first, then everything else
        for p in priority + other:
            logger.info(f"Probing {p.device}...")
            result = await self._try_connect(p.device)
            if result:
                return result

        logger.warning("No OHAUS scale found on any port")
        return None

    async def _try_connect(self, port: str) -> ScaleInfo | None:
        try:
            self._close_serial()

            self.serial_conn = serial.Serial(
                port=port,
                baudrate=self.config.baud_rate,
                timeout=2,
            )
            self.serial_conn.reset_input_buffer()
            self.serial_conn.write(self.parser.request_weight())

            # Wait up to 2.5s total for the scale to respond (some scales are slow on first query)
            await asyncio.sleep(1.5)
            if self.serial_conn.in_waiting == 0:
                logger.debug(f"{port}: no response after 1.5s, waiting 1s more...")
                await asyncio.sleep(1.0)

            if self.serial_conn.in_waiting > 0:
                # Try reading up to 4 lines — first line may be garbled on initial handshake
                reading = None
                for attempt in range(4):
                    raw = self.serial_conn.readline()
                    line = raw.decode("ascii", errors="ignore").strip()
                    if not line:
                        continue
                    reading = self.parser.parse(line)
                    if reading is not None:
                        break
                    logger.debug(f"{port}: parse failed on line {attempt + 1}: {repr(line)}")

                if reading is not None:
                    self.scale_info = ScaleInfo(make="OHAUS", model="Ranger Count 3000", port=port)
                    self._connected = True
                    val = reading.piece_count if reading.piece_count is not None else reading.weight_g
                    logger.info(f"Scale connected on {port} — reading: {val} {reading.unit}")
                    return self.scale_info
                logger.debug(f"{port}: data present but no valid reading parsed — not an OHAUS scale")
            else:
                logger.debug(f"{port}: no response after 2.5s — skipping")

            self._close_serial()
        except serial.SerialException as e:
            logger.debug(f"Failed to connect on {port}: {e}")
            err_str = str(e)
            if "PermissionError(13" in err_str and ("5)" in err_str or "31)" in err_str):
                if await self._try_free_port(port):
                    return await self._try_connect_simple(port)
            self._close_serial()
        except Exception as e:
            logger.debug(f"Failed to connect on {port}: {e}")
            self._close_serial()
        return None

    async def _try_connect_simple(self, port: str) -> ScaleInfo | None:
        """Single connection attempt without USB reset fallback (prevents recursion)."""
        try:
            self._close_serial()
            logger.debug(f"Attempting connection to {port} after reset...")
            self.serial_conn = serial.Serial(
                port=port,
                baudrate=self.config.baud_rate,
                timeout=2,
            )
            self.serial_conn.reset_input_buffer()
            self.serial_conn.write(self.parser.request_weight())
            await asyncio.sleep(1.0)
            if self.serial_conn.in_waiting > 0:
                line = self.serial_conn.readline().decode("ascii", errors="ignore")
                reading = self.parser.parse(line)
                if reading is not None:
                    self.scale_info = ScaleInfo(make="OHAUS", model="Ranger Count 3000", port=port)
                    self._connected = True
                    val = reading.piece_count if reading.piece_count is not None else reading.weight_g
                    logger.info(f"Scale connected on {port} after USB reset — reading: {val} {reading.unit}")
                    return self.scale_info
            self._close_serial()
        except Exception as e:
            logger.debug(f"Failed to connect on {port} after USB reset: {e}")
            self._close_serial()
        return None

    async def _try_free_port(self, port: str) -> bool:
        """Try to free a stuck serial port via USB reset (Windows only)."""
        return await self._try_reset_usb(port)

    async def _try_reset_usb(self, port: str) -> bool:
        """Try to reset the USB-serial adapter by toggling the PnP device (Windows only)."""
        if sys.platform != "win32":
            return False

        logger.warning(f"USB-serial adapter on {port} appears stuck — attempting automatic reset...")
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-PnpDevice -Class Ports -ErrorAction SilentlyContinue | "
                 f"Where-Object {{ $_.FriendlyName -like '*{port}*' }}).InstanceId"],
                capture_output=True, text=True, timeout=10
            )
            instance_id = result.stdout.strip()
            if not instance_id:
                logger.warning(f"Could not find PnP device for {port}")
                return False

            logger.info(f"Resetting USB device: {instance_id}")

            subprocess.run(
                ["powershell", "-Command",
                 f'Disable-PnpDevice -InstanceId "{instance_id}" -Confirm:$false'],
                capture_output=True, timeout=10
            )
            await asyncio.sleep(1)

            subprocess.run(
                ["powershell", "-Command",
                 f'Enable-PnpDevice -InstanceId "{instance_id}" -Confirm:$false'],
                capture_output=True, timeout=10
            )
            await asyncio.sleep(3)

            logger.info(f"USB device reset complete for {port}")
            return True
        except Exception as e:
            logger.warning(f"USB reset failed: {e}")
            return False

    def _reader_loop(self):
        """Background thread: reads serial lines as fast as the scale sends them.

        Runs in its own thread so it never blocks the asyncio event loop.
        Only keeps the latest reading — stale data is discarded.
        If the scale stops sending data, triggers async reconnection.
        """
        conn = self.serial_conn
        if not conn:
            return

        buf = b""
        import time

        no_data_seconds = 0.0

        while not self._stop_reader.is_set() and self._connected:
            try:
                waiting = conn.in_waiting
                if waiting > 0:
                    chunk = conn.read(waiting)
                    if not chunk:
                        continue

                    buf += chunk
                    no_data_seconds = 0.0

                    # Process all complete lines in the buffer
                    while b"\n" in buf:
                        line_bytes, buf = buf.split(b"\n", 1)
                        line = line_bytes.decode("ascii", errors="ignore").strip()
                        if not line:
                            continue
                        logger.info(f"RAW: {line!r}")
                        reading = self.parser.parse(line)
                        if reading:
                            with self._reading_lock:
                                self._latest_reading = reading

                    # Prevent buffer from growing unbounded on garbage data
                    if len(buf) > 512:
                        buf = buf[-256:]
                else:
                    # No data available — short sleep to avoid busy-waiting
                    time.sleep(0.05)
                    no_data_seconds += 0.05

                    # If no data for 5 seconds, try re-sending continuous command
                    if no_data_seconds >= 5.0 and self._connected:
                        logger.warning("No data from scale for 5s — re-sending continuous command...")
                        try:
                            conn.write(self.parser.request_continuous())
                        except Exception:
                            pass
                        no_data_seconds = 0.0

            except Exception as e:
                if self._connected and not self._stop_reader.is_set():
                    logger.error(f"Serial read error in reader thread: {e}")
                break

    def _start_reader(self):
        """Start the background serial reader thread.

        Safe to call multiple times — only starts if not already running.
        """
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._stop_reader.clear()
        self._latest_reading = None
        if self.serial_conn:
            self.serial_conn.reset_input_buffer()
            self.serial_conn.write(self.parser.request_continuous())
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def start_streaming(self):
        """Start continuous reading from the scale. Called once after auto_detect."""
        self._start_reader()

    def _stop_reader_thread(self):
        """Stop the background reader thread."""
        self._stop_reader.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)
        self._reader_thread = None

    def _close_serial(self):
        """Close the serial connection if open."""
        self._stop_reader_thread()
        if self.serial_conn is not None:
            try:
                if self.serial_conn.is_open:
                    try:
                        self.serial_conn.write(b"\r\n")
                        self.serial_conn.reset_input_buffer()
                        self.serial_conn.reset_output_buffer()
                    except Exception:
                        pass
                    self.serial_conn.close()
            except Exception as e:
                logger.debug(f"Error closing serial: {e}")
            finally:
                self.serial_conn = None

    @property
    def connected(self) -> bool:
        return self._connected

    def status_json(self) -> str:
        return json.dumps({
            "type": "status",
            "connected": self._connected,
            "scale": self.scale_info.to_dict() if self.scale_info else None,
        })

    async def stream(self) -> AsyncGenerator[WeightReading, None]:
        """Stream weight readings to a single WebSocket client.

        Does NOT manage the reader thread lifecycle — that is handled by
        start_streaming() and close(). This way, clients connecting and
        disconnecting (e.g. page navigation) don't disrupt the serial reader.
        """
        if not (self.serial_conn and self._connected):
            # Simulation mode
            weight = 0.0
            while True:
                yield WeightReading(weight_g=weight, stable=True)
                await asyncio.sleep(self.config.poll_interval)
            return

        # Ensure reader is running (no-op if already started)
        self._start_reader()
        last_yielded = None

        while self._connected:
            # Grab the latest reading (non-blocking)
            with self._reading_lock:
                reading = self._latest_reading

            if reading is not None and reading is not last_yielded:
                last_yielded = reading
                yield reading

            await asyncio.sleep(self.config.poll_interval)

    async def tare(self) -> None:
        if self.serial_conn and self._connected:
            self.serial_conn.write(self.parser.request_tare())

    async def zero(self) -> None:
        if self.serial_conn and self._connected:
            self.serial_conn.write(self.parser.request_zero())

    def close(self) -> None:
        """Close all resources. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        self._connected = False
        port_name = self.serial_conn.port if self.serial_conn else "N/A"
        self._close_serial()
        logger.info(f"Serial port {port_name} closed.")

    def __del__(self) -> None:
        if self.serial_conn is not None:
            try:
                self.serial_conn.close()
            except Exception:
                pass
