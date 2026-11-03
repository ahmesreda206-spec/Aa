from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import AuthContext, get_auth_context, require_csrf
from ..models import ChatMessage
from ..rate_limit import limiter
from ..schemas import AIStatus, ChatMessageOut, ChatRequest, ChatResponse
from ..services.inference import llama_service

router = APIRouter(prefix="/api/ai", tags=["local-ai"])


@router.get("/status", response_model=AIStatus)
def ai_status(context: AuthContext = Depends(get_auth_context)) -> dict:
    return llama_service.status()


@router.get("/history", response_model=list[ChatMessageOut])
def history(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
) -> list[ChatMessage]:
    return list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == context.user.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(100)
        ).all()[::-1]
    )


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
async def chat(
    payload: ChatRequest,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ChatResponse:
    prior = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == context.user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(12)
    ).all()
    messages = [{"role": item.role, "content": item.content} for item in reversed(prior)]
    user_message = ChatMessage(user_id=context.user.id, role="user", content=payload.message)
    db.add(user_message)
    db.commit()
    messages.append({"role": "user", "content": payload.message})
    try:
        answer = await llama_service.generate(messages)
        if not answer:
            raise RuntimeError("The model returned an empty response")
    except Exception:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Local model unavailable; verify the AI runtime, base weights, and adapter files",
        ) from None
    assistant_message = ChatMessage(user_id=context.user.id, role="assistant", content=answer)
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    return ChatResponse(
        message=ChatMessageOut.model_validate(assistant_message),
        model="Llama 14B",
        adapter="llama_14b_lora",
    )


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def clear_history(
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    db.query(ChatMessage).filter(ChatMessage.user_id == context.user.id).delete()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
