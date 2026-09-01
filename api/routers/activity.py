"""Activity & Audit Log Routes."""

from fastapi import APIRouter, HTTPException, Depends, Query
from ..config import get_current_user
from ..activity_helper import log_activity_event, fetch_activity_logs

router = APIRouter(prefix="/api/activity", tags=["activity"])

@router.get("")
def get_activity_logs(
    action_type: str = Query(None, alias="type"),
    search: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user = Depends(get_current_user)
):
    """Retrieve activity history logs."""
    try:
        logs = fetch_activity_logs(action_type=action_type, limit=limit)
        
        if search and search.strip():
            s = search.strip().lower()
            logs = [
                l for l in logs
                if s in str(l.get("user_name", "")).lower()
                or s in str(l.get("action_title", "")).lower()
                or s in str(l.get("details", "")).lower()
                or s in str(l.get("action_type", "")).lower()
            ]

        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def record_activity(payload: dict, user = Depends(get_current_user)):
    """Record a new activity event."""
    try:
        action_type = payload.get("action_type", "GENERAL")
        action_title = payload.get("action_title", "User Action")
        details = payload.get("details", "")

        log_activity_event(
            user=user,
            action_type=action_type,
            action_title=action_title,
            details=details
        )
        return {"success": True, "message": "Activity logged"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
