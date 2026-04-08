"""Structured JSON logging with WebSocket broadcast."""

import asyncio
import json
import logging
import sys
import time

from fastapi import WebSocket

logger = logging.getLogger("kokoro-server")
logger.setLevel(logging.INFO)

# Stdout handler
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setFormatter(
    logging.Formatter('{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":%(message)s}')
)
logger.addHandler(_stdout_handler)

# Suppress noisy torch/hf warnings from cluttering logs
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

# WebSocket broadcast set
ws_clients: set[WebSocket] = set()


class WebSocketLogHandler(logging.Handler):
    """Broadcasts log records to all connected WebSocket clients."""

    def emit(self, record):
        try:
            raw = record.getMessage()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                msg = raw.strip('"')
            entry = json.dumps(
                {
                    "time": self.format(record).split(",")[0]
                    if hasattr(record, "asctime")
                    else time.strftime("%H:%M:%S"),
                    "level": record.levelname,
                    "message": msg,
                }
            )
            for ws in list(ws_clients):
                asyncio.create_task(_ws_send(ws, entry))
        except Exception:
            pass


async def _ws_send(ws: WebSocket, data: str):
    try:
        await ws.send_text(data)
    except Exception:
        ws_clients.discard(ws)


_ws_handler = WebSocketLogHandler()
_ws_handler.setFormatter(logging.Formatter("%(asctime)s"))
logger.addHandler(_ws_handler)


def log_json(request_id: str, event: str, **kwargs):
    """Log a structured JSON event with consistent format."""
    logger.info(json.dumps({"request_id": request_id, "event": event, **kwargs}))
