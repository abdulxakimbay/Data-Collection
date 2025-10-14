# models/event.py
from pydantic import BaseModel, Field
from typing import Optional

class UTM(BaseModel):
    source: str = ""
    medium: str = ""
    campaign: str = ""
    content: str = ""
    term: Optional[str] = ""

class ClientInfo(BaseModel):
    time_on_page_ms: Optional[int] = 0

class FormData(BaseModel):
    name: str
    phone: str

# ─── Событие клика по Telegram или WhatsApp ───
class MessengerClick(BaseModel):
    page_city: Optional[str] = ""
    utm: UTM
    client: Optional[ClientInfo] = ClientInfo()

# ─── Событие отправки формы ───
class FormSubmit(BaseModel):
    page_city: Optional[str] = ""
    utm: UTM
    client: Optional[ClientInfo] = ClientInfo()
    form: FormData

# ─── Контакт от бота ───
class BotContact(BaseModel):
    msg: str
