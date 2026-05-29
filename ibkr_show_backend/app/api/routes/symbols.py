from fastapi import APIRouter, Depends, Query

from app.api.deps import get_symbol_suggest_service, require_authenticated_session
from app.core.auth import AuthSession
from app.services.symbol_suggest_service import SymbolSuggestService

router = APIRouter(prefix="/symbols", tags=["symbols"])


@router.get("/suggest")
def suggest_symbols(
    q: str = Query(..., min_length=1),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: SymbolSuggestService = Depends(get_symbol_suggest_service),
) -> dict:
    suggestions = service.suggest(q, limit=5)
    corrected = service.correct_symbol(q)
    return {"suggestions": suggestions, "corrected": corrected}
