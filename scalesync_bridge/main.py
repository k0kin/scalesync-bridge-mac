from __future__ import annotations
import asyncio
import atexit
import argparse
import logging
import signal
import sys
from scalesync_bridge.config import BridgeConfig
from scalesync_bridge.scale_manager import ScaleManager
from scalesync_bridge.server import BridgeServer

logger = logging.getLogger(__name__)

# Global reference so atexit/signal handlers can clean up
_manager: ScaleManager | None = None


def _cleanup():
    """Safety-net cleanup called on any exit path."""
    global _manager
    if _manager is not None:
        logger.info("atexit: cleaning up resources...")
        _manager.close()
        _manager = None


def main() -> None:
    parser = argparse.ArgumentParser(description="ScaleSync Bridge")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket port")
    parser.add_argument("--serial", type=str, default=None, help="Serial port (e.g., /dev/tty.usbserial-1420)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = BridgeConfig()
    config.port = args.port
    config.baud_rate = args.baud
    if args.serial:
        config.serial_port = args.serial

    # Register cleanup so it runs even if the process is killed abruptly
    atexit.register(_cleanup)

    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        logger.info("Bridge stopped by user.")
    finally:
        _cleanup()


async def _run(config: BridgeConfig) -> None:
    global _manager
    manager = ScaleManager(config)
    _manager = manager
    shutdown_event = asyncio.Event()

    def request_shutdown():
        logger.info("Shutdown requested...")
        shutdown_event.set()

    # macOS/Linux: use asyncio signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_shutdown)

    try:
        while not shutdown_event.is_set():
            scale = await manager.auto_detect()
            if scale:
                logger.info(f"Connected to {scale.make} {scale.model} on {scale.port}")
                break
            logger.warning("No scale detected — retrying in 5 seconds... (check USB connection)")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                continue

        if not shutdown_event.is_set():
            manager.start_streaming()
            server = BridgeServer(manager, config)
            await server.start(shutdown_event)
    finally:
        logger.info("Cleaning up resources...")
        manager.close()
        _manager = None
        logger.info("Serial port closed. WebSocket port released. Safe to restart.")


if __name__ == "__main__":
    main()
