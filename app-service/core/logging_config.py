import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any

from core.config import settings

RPC_DEBUG_SNS = frozenset(
    {
        "a2b0004620c25068d090426",
        "a4b0000737c35554d070426",
    }
)


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
