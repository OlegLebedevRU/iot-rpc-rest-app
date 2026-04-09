import json
import logging
import logging.handlers
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.config import settings

RPC_DEBUG_SNS = frozenset(
    {
        "a2b0004620c25068d090426",
        "a4b0000737c35554d070426",
    }
)

RPC_REQ_VERBOSE_DEBUG_SNS = frozenset({"a2b0004620c25068d090426"})


class SnDebugFilter(logging.Filter):
    def __init__(self, sn: str):
        super().__init__()
        self.sn = sn

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "sn", None) == self.sn


def _get_log_dir() -> Path:
    log_dir = Path("/var/log/app")
    log_dir.mkdir(exist_ok=True)
    return log_dir


def _build_rotating_handler(
    log_path: Path, level: int | None = None
) -> logging.handlers.RotatingFileHandler:
    handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        mode="a",
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setLevel(level or settings.logging.log_level_value)
    handler.setFormatter(
        logging.Formatter(
            settings.logging.log_format, datefmt=settings.logging.date_format
        )
    )
    return handler


def get_rpc_debug_logger() -> logging.Logger:
    logger = logging.getLogger("rpc_debug")
    logger.setLevel(settings.logging.log_level_value)
    logger.propagate = False

    if getattr(logger, "_rpc_debug_configured", False):
        return logger

    if logger.handlers:
        logger.handlers.clear()

    log_dir = _get_log_dir()
    for sn in sorted(RPC_DEBUG_SNS):
        handler = _build_rotating_handler(log_dir / f"rpc_{sn}.log")
        handler.addFilter(SnDebugFilter(sn))
        logger.addHandler(handler)

    logger._rpc_debug_configured = True
    return logger


def log_rpc_debug(sn: str | None, event: str, **fields: Any) -> None:
    if sn not in RPC_DEBUG_SNS:
        return

    payload = [f"event={event}", f"sn={sn}"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        else:
            rendered = str(value)
        payload.append(f"{key}={rendered}")

    get_rpc_debug_logger().info(" ".join(payload), extra={"sn": sn})


def _render_debug_value(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return repr(value)

    if value is None or isinstance(value, bool | int | float | str):
        return value

    if isinstance(value, bytes | bytearray):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(value).hex()

    if isinstance(value, memoryview):
        return _render_debug_value(value.tobytes(), depth + 1)

    if isinstance(value, Mapping):
        return {
            str(key): _render_debug_value(item, depth + 1)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_render_debug_value(item, depth + 1) for item in value]

    if hasattr(value, "__dict__"):
        return {
            key: _render_debug_value(item, depth + 1)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }

    return repr(value)


def build_rabbit_message_debug_snapshot(msg: Any) -> dict[str, Any]:
    raw_message = getattr(msg, "raw_message", None)
    body = getattr(msg, "body", None)
    body_bytes = bytes(body) if isinstance(body, memoryview) else body

    if isinstance(body_bytes, bytes):
        try:
            body_preview = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            body_preview = body_bytes.hex()
        if len(body_preview) > 1000:
            body_preview = body_preview[:1000] + "..."
    else:
        body_preview = _render_debug_value(body_bytes)

    return {
        "msg_type": type(msg).__name__,
        "msg_repr": repr(msg),
        "correlation_id": _render_debug_value(getattr(msg, "correlation_id", None)),
        "message_id": _render_debug_value(getattr(msg, "message_id", None)),
        "headers": _render_debug_value(getattr(msg, "headers", None)),
        "body_len": len(body_bytes) if isinstance(body_bytes, (bytes, bytearray)) else None,
        "body_preview": body_preview,
        "raw_message": {
            "type": type(raw_message).__name__ if raw_message is not None else None,
            "repr": repr(raw_message) if raw_message is not None else None,
            "correlation_id": _render_debug_value(getattr(raw_message, "correlation_id", None)),
            "message_id": _render_debug_value(getattr(raw_message, "message_id", None)),
            "reply_to": _render_debug_value(getattr(raw_message, "reply_to", None)),
            "routing_key": _render_debug_value(getattr(raw_message, "routing_key", None)),
            "headers": _render_debug_value(getattr(raw_message, "headers", None)),
            "properties": _render_debug_value(getattr(raw_message, "properties", None)),
        },
    }


def setup_module_logger(module_name: str, log_file: str) -> logging.Logger:
    """
    Настраивает и возвращает логгер для модуля с ротацией по размеру.

    :param module_name: Имя модуля (используется как имя логгера)
    :param log_file: Имя файла лога (будет сохранён в /var/log/app/)
    :return: Настроенный экземпляр Logger
    """
    # Создаём путь к файлу лога
    log_dir = _get_log_dir()
    log_path = log_dir / log_file

    # Создаём логгер
    logger = logging.getLogger(module_name)
    logger.setLevel(settings.logging.log_level_value)
    logger.propagate = False

    # Избегаем дублирования обработчиков
    if logger.handlers:
        logger.handlers.clear()

    # Обработчик с ротацией (макс 10 МБ, 10 файлов)
    handler = _build_rotating_handler(log_path)

    # Добавляем обработчик
    logger.addHandler(handler)

    return logger
