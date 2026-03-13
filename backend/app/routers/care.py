from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TenantBank
from app.database import get_db
from app.middleware.auth import resolve_tenant
from app.services import handle_chat

router = APIRouter()


class ChatIn(BaseModel):
    session_id: str
    customer_id: str
    message: str
    channel: str = "mobile_app"


class ChatOut(BaseModel):
    session_id: str
    intent: str
    response: str
    escalate_to_human: bool
    suggested_actions: list[str]
    processing_time_ms: int


@router.post("/chat", response_model=ChatOut)
async def chat(
    payload: ChatIn,
    bank: TenantBank = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await handle_chat(
        db=db,
        bank=bank,
        session_id=payload.session_id,
        customer_id=payload.customer_id,
        message=payload.message,
        channel=payload.channel,
    )
    return ChatOut(**result)
