# services/redis_client.py
import os
import uuid
import logging
from typing import Optional

try:
    import redis  # type: ignore
except Exception as e:
    redis = None

# Глобальный клиент Redis; инициализируется через init_redis()
_redis_client: Optional["redis.Redis"] = None # type: ignore
CLICK_COUNTER_KEY = os.getenv("CLICK_COUNTER_KEY", "click_id_counter")


def init_redis(logger: Optional[logging.Logger] = None) -> None:
    """
    Инициализация глобального Redis-клиента и стартового значения счётчика.
    Если Redis или пакет redis недоступен — оставляем _redis_client = None (фолбэк в get_next_click_id()).
    """
    global _redis_client

    if redis is None:
        if logger:
            logger.error("Python package 'redis' is not installed; falling back to UUID for click_id")
        _redis_client = None
        return

    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db   = int(os.getenv("REDIS_DB", "0"))

    try:
        client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        # Устанавливаем стартовую точку 999, чтобы первый INCR вернул 1000
        client.setnx(CLICK_COUNTER_KEY, 999)
        # Пробный вызов PING
        client.ping()
        _redis_client = client
        if logger:
            logger.info("Redis connected", extra={"host": host, "port": port, "db": db})
    except Exception as e:
        _redis_client = None
        if logger:
            logger.error("Redis connection failed; falling back to UUID for click_id", extra={"error": str(e)})


def get_next_click_id(strict: bool = False) -> str:
    """
    Возвращает следующий атомарный клик-ID как строку.
    - Если Redis доступен: INCR по CLICK_COUNTER_KEY (начиная с 1000).
    - Если недоступен:
        * strict=True  -> выбрасываем исключение (чтобы отдать 500 на уровне хендлера).
        * strict=False -> делаем безопасный фолбэк на короткий UUID (12 hex-символов).
    """
    global _redis_client

    if _redis_client is not None:
        try:
            next_id = _redis_client.incr(CLICK_COUNTER_KEY)
            return str(next_id)
        except Exception:
            # Падаем в фолбэк ниже
            pass

    if strict:
        raise RuntimeError("Redis is not available for click_id generation")

    # Мягкий фолбэк
    return uuid.uuid4().hex[:12]
