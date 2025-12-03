# main.py
from dotenv import load_dotenv
load_dotenv()

# ── logging ──────────────────────────────────────────────────────────────────
import logging
from services.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# ── app imports ──────────────────────────────────────────────────────────────
import os
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
import re
import geoip2.database
from urllib.parse import quote
from typing import Union
from zoneinfo import ZoneInfo

from models.event import MessengerClick, FormSubmit, BotContact
from services.sheets import append_row_to_sheets, update_messenger_by_id
from services.planfix import build_planfix_payload, send_to_planfix
from services.redis_client import init_redis, get_next_click_id

# ── FastAPI app ─────────────────────────────────────────────────────────────
app = FastAPI(title="Data Collection API")

# CORS
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis init
init_redis(logger=logger)

# GeoIP
geoip_reader = None
geoip_path = os.getenv("GEOIP_DB_PATH")
if geoip_path and os.path.exists(geoip_path):
    try:
        geoip_reader = geoip2.database.Reader(geoip_path)
        logger.info(f"GeoIP DB loaded: {geoip_path}")
    except Exception as e:
        logger.warning(f"GeoIP load failed: path={geoip_path} err={e}")
else:
    logger.info("GeoIP disabled or file not found")


def get_city_by_ip(ip: str) -> str:
    if not geoip_reader:
        return ""
    try:
        resp = geoip_reader.city(ip)
        return resp.city.name or ""
    except Exception:
        return ""


@app.get("/health")
def health_check():
    logger.debug("health_check")
    return {"status": "ok"}

# ========== Поиск click_id в тексте ==========
# Ищем целое число длиной >= 4 символов (наш ID начиная с 1000),
# Берём ПОСЛЕДНЕЕ совпадение в строке — мы добавляем ID в конец prefill.
INT_CLICK_ID_RE = re.compile(r'\b(\d{4,7})\b')

def extract_click_id_from_text(text: str) -> str | None:
    if not text:
        return None
    ids = INT_CLICK_ID_RE.findall(text)
    if not ids:
        return None
    return ids[-1]

def _build_common_values(
    click_id: str,
    event: str,
    data: Union[MessengerClick, FormSubmit],
    ip: str,
    city: str,
    ua: str
) -> list:
    """
    Универсальная сборка строки данных для Google Sheets.
    """
    timestamp = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M:%S")
    page_city = getattr(data, "page_city", "") or ""
    utm = getattr(data, "utm", None)
    utm_source = getattr(utm, "source", "") if utm else ""
    utm_medium = getattr(utm, "medium", "") if utm else ""
    utm_campaign = getattr(utm, "campaign", "") if utm else ""
    utm_content = getattr(utm, "content", "") if utm else ""
    utm_term = getattr(utm, "term", "") if utm else ""

    client = getattr(data, "client", None)
    time_on_page = getattr(client, "time_on_page_ms", 0) if client else 0
    ref = getattr(client, "referrer", "") if client else ""

    values = [
        click_id,          # A id
        timestamp,         # B timestamp
        event,             # C event
        page_city,         # D page_city
        utm_source,        # E utm_source
        utm_medium,        # F utm_medium
        utm_campaign,      # G utm_campaign
        utm_content,       # H utm_content
        utm_term,          # I utm_term
        time_on_page,      # J time_on_page_ms
        ip,                # K ip
        city,              # L geo_city
        ua,                # M user_agent
        ref,               # N referrer
        "",                # O messenger (заполняется позже ботом)
    ]
    return values


def append_row_bg(values: list, click_id: str, event: str):
    try:
        success, result = append_row_to_sheets(values)
        if success:
            logger.info("sheets_append_ok (bg)", extra={"click_id": click_id, "event": event})
        else:
            logger.error("sheets_append_fail (bg)", extra={"click_id": click_id, "event": event, "error": str(result)})
    except Exception:
        logger.exception("sheets_append_exception (bg)", extra={"click_id": click_id, "event": event})


# ========== 1) Telegram click endpoint (redirect) ==========
@app.post("/events/telegram_click")
async def telegram_click(data: MessengerClick, request: Request, background_tasks: BackgroundTasks):
    """
    Логирует клик на Telegram, добавляет строку в Google Sheet и возвращает RedirectResponse на t.me?start=<id>
    """
    ip = request.client.host
    city = get_city_by_ip(ip)
    ua = request.headers.get("user-agent", "")

    # Генерируем атомарный integer ID (строкой)
    click_id = get_next_click_id()  # мягкий фолбэк на UUID, если Redis недоступен
    logger.info("telegram_click", extra={"click_id": click_id, "page_city": data.page_city, "ip": ip})

    values = _build_common_values(click_id, "telegram_click", data, ip, city, ua)
    background_tasks.add_task(append_row_bg, values, click_id, "telegram_click")

    BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")
    if not BOT_USERNAME:
        logger.error("telegram_username_missing")
        return JSONResponse(status_code=500, content={"ok": False, "error": "TELEGRAM_BOT_USERNAME not set"})

    tg_link = f"https://t.me/{BOT_USERNAME}?start={click_id}"
    logger.info("telegram_link_built", extra={"click_id": click_id, "tg_link": tg_link})

    return {"ok": True, "tg_link": tg_link}


# ========== 2) WhatsApp click endpoint (return wa.me link with prefilled text) ==========
@app.post("/events/whatsapp_click")
async def whatsapp_click(data: MessengerClick, request: Request, background_tasks: BackgroundTasks):
    """
    Логирует клик, сохраняет строку в таблицу и возвращает JSON с готовой ссылкой на WhatsApp.
    """
    ip = request.client.host
    city = get_city_by_ip(ip)
    ua = request.headers.get("user-agent", "")

    click_id = get_next_click_id()
    logger.info("whatsapp_click", extra={"click_id": click_id, "page_city": data.page_city, "ip": ip})

    values = _build_common_values(click_id, "whatsapp_click", data, ip, city, ua)
    background_tasks.add_task(append_row_bg, values, click_id, "whatsapp_click")

    WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER")
    if not WHATSAPP_NUMBER:
        logger.error("whatsapp_number_missing")
        return JSONResponse(status_code=500, content={"ok": False, "error": "WHATSAPP_NUMBER not set"})

    PREFILL = quote(os.getenv("WHATSAPP_PREFILL_TEXT", ""))
    prefilled_text = f"{PREFILL}{click_id}"

    wa_link = f"https://wa.me/{WHATSAPP_NUMBER}?text={prefilled_text}"

    logger.info("whatsapp_link_built", extra={"click_id": click_id, "wa_link": wa_link})
    return {"ok": True, "wa_link": wa_link}


# ========== 3) Form submit endpoint ==========
@app.post("/events/form_submit")
async def form_submit(data: FormSubmit, request: Request, background_tasks: BackgroundTasks):
    """
    Обработка отправки формы: сохраняет данные, записывает в Planfix и в Google Sheets.
    """
    ip = request.client.host
    city = get_city_by_ip(ip)
    ua = request.headers.get("user-agent", "")

    click_id = get_next_click_id()
    logger.info(
        "form_submit",
        extra={
            "click_id": click_id,
            "page_city": data.page_city,
            "ip": ip,
            "form_name": data.form.name if data.form else None
        }
    )

    values = _build_common_values(click_id, "form_submit", data, ip, city, ua)
    background_tasks.add_task(append_row_bg, values, click_id, "form_submit")

    if data.form:
        payload = build_planfix_payload(
            name=data.form.name,
            phone=data.form.phone,
            page_city=data.page_city or "",
        )
        background_tasks.add_task(send_to_planfix, payload)
        logger.info("planfix_enqueued", extra={"click_id": click_id, "form_name": data.form.name})

    return {"ok": True}


# ========== 4) Endpoint для Planfix, который присылает текст с /start <id> ==========
@app.post("/bot/telegram")
async def bot_telegram(body: BotContact):
    # ожидаем "/start <id>"
    parts = (body.msg or "").split()
    if len(parts) < 2:
        logger.warning("bot_telegram_bad_payload", extra={"msg": body.msg})
        raise HTTPException(status_code=400, detail="Bad payload: expected '/start <id>'")

    click_id = parts[1]
    ok, res = update_messenger_by_id(click_id, "telegram")
    if not ok:
        if res == "ID not found":
            logger.warning("bot_telegram_id_not_found", extra={"click_id": click_id})
            raise HTTPException(status_code=404, detail="ID not found")
        logger.error("bot_telegram_update_fail", extra={"click_id": click_id, "error": res})
        raise HTTPException(status_code=500, detail=res)

    logger.info("bot_telegram_updated", extra={"click_id": click_id, "messenger": "telegram"})
    return {"ok": True, "detail": "updated"}


# ========== 5) Endpoint для Planfix, который присылает текст с ?text=... ==========
@app.post("/bot/whatsapp")
async def bot_whatsapp(body: BotContact):
    # ожидаем текст пользователя, где есть click_id (целое число длиной >=4)
    text = (body.msg or "").strip()
    if not text:
        logger.warning("bot_whatsapp_empty_payload", extra={"body": body.dict()})
        raise HTTPException(status_code=400, detail="Empty payload")

    click_id = extract_click_id_from_text(text)
    if not click_id:
        logger.warning("bot_whatsapp_no_id", extra={"text": text})
        raise HTTPException(status_code=400, detail="click_id not found in text")

    ok, res = update_messenger_by_id(click_id, "whatsapp")
    if not ok:
        if res == "ID not found":
            logger.warning("bot_whatsapp_id_not_found", extra={"click_id": click_id, "text": text})
            raise HTTPException(status_code=404, detail="ID not found")
        logger.error("bot_whatsapp_update_fail", extra={"click_id": click_id, "error": res})
        raise HTTPException(status_code=500, detail=res)

    logger.info("bot_whatsapp_updated", extra={"click_id": click_id, "text": text})
    return {"ok": True, "detail": "updated"}
