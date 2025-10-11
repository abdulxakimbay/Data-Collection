# services/planfix.py
import os
import asyncio
import logging
import httpx
from typing import Dict

logger = logging.getLogger(__name__)

PLANFIX_WEBHOOK_URL = os.getenv("PLANFIX_WEBHOOK_URL")
HTTP_TIMEOUT = float(os.getenv("PLANFIX_HTTP_TIMEOUT", "5"))
RETRIES = int(os.getenv("PLANFIX_RETRIES", "3"))
BACKOFF_BASE = float(os.getenv("PLANFIX_BACKOFF_BASE", "0.8"))


def build_planfix_payload(name: str, phone: str, page_city: str) -> Dict:
    """
    Формируем простой JSON под Planfix
    """
    return {
        "name": name,
        "phone": phone,
        "page_city": page_city
    }


async def send_to_planfix(payload: Dict):
    """
    Отправляем POST запрос в Planfix с ретраями.
    Просто логируем результат — функция не бросает исключения наружу.
    """
    if not PLANFIX_WEBHOOK_URL:
        logger.info("PLANFIX_WEBHOOK_URL not set — skipping send_to_planfix")
        return

    attempt = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        while attempt < RETRIES:
            try:
                resp = await client.post(
                    PLANFIX_WEBHOOK_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code < 400:
                    logger.info("Planfix OK", extra={"status": resp.status_code, "payload": payload})
                    return
                # treat as error to retry
                body = await resp.aread() if hasattr(resp, "aread") else resp.text
                raise Exception(f"Planfix error {resp.status_code}: {body}")
            except Exception as e:
                attempt += 1
                if attempt >= RETRIES:
                    logger.exception("Planfix failed final", extra={"attempts": attempt, "error": str(e), "payload": payload})
                    return
                backoff = BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning("Planfix error, retrying", extra={"attempt": attempt, "backoff": backoff, "error": str(e)})
                await asyncio.sleep(backoff)
