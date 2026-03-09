import logging
import logging.handlers
from pathlib import Path

from core.config import settings


def setup_module_logger(module_name: str, log_file: str) -> logging.Logger:
    """
    Настраивает и возвращает логгер для модуля с ротацией по размеру.

    :param module_name: Имя модуля (используется как имя логгера)
    :param log_file: Имя файла лога (будет сохранён в /var/log/app/)
    :return: Настроенный экземпляр Logger
    """
    # Создаём путь к файлу лога
    log_dir = Path("/var/log/app")
    log_dir.mkdir(exist_ok=True)  # Создаём директорию, если не существует
    log_path = log_dir / log_file

    # Создаём логгер
    logger = logging.getLogger(module_name)
    logger.setLevel(settings.logging.log_level_value)

    # Избегаем дублирования обработчиков
    if logger.handlers:
        logger.handlers.clear()

    # Обработчик с ротацией (макс 10 МБ, 10 файлов)
    handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        mode="a",
        maxBytes=10 * 1024 * 1024,  # 10 МБ
        backupCount=10,
        encoding="utf-8",
    )
    handler.setLevel(settings.logging.log_level_value)

    # Форматирование
    formatter = logging.Formatter(
        settings.logging.log_format, datefmt=settings.logging.date_format
    )
    handler.setFormatter(formatter)

    # Добавляем обработчик
    logger.addHandler(handler)

    return logger
