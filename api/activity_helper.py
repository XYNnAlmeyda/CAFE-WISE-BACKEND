"""Activity Logger Helper for CafeWise."""

from datetime import datetime, timezone, timedelta
import json
import os
from .config import supabase_admin

PHT = timezone(timedelta(hours=8))  # GMT+8 Philippine Time

LOCAL_LOGS_FILE = os.path.join(os.path.dirname(__file__), "..", "activity_logs.json")

def get_user_info(user):
    if not user:
        return {"user_id": "system", "user_name": "System", "user_role": "SYSTEM"}
    
    metadata = getattr(user, "user_metadata", {}) or {}
    email = getattr(user, "email", "User")
    full_name = metadata.get("full_name") or (email.split("@")[0] if email else "User")
    role = metadata.get("role") or "USER"

    return {
        "user_id": getattr(user, "id", "unknown"),
        "user_name": full_name,
        "user_role": role
    }

def log_activity_event(user, action_type: str, action_title: str, details: str):
    info = get_user_info(user)
    timestamp = datetime.now(PHT).isoformat()

    entry = {
        "user_id": info["user_id"],
        "user_name": info["user_name"],
        "user_role": info["user_role"],
        "action_type": action_type.upper(),
        "action_title": action_title,
        "details": details,
        "created_at": timestamp
    }

    # 1. Try Supabase
    try:
        res = supabase_admin.table("activity_logs").insert(entry).execute()
        if res.data:
            return
    except Exception:
        pass

    # 2. Local JSON file fallback
    try:
        logs = []
        if os.path.exists(LOCAL_LOGS_FILE):
            with open(LOCAL_LOGS_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        
        logs.insert(0, entry)
        logs = logs[:500]

        with open(LOCAL_LOGS_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
    except Exception as err:
        print(f"Failed to log activity locally: {err}")

def fetch_activity_logs(action_type: str = None, limit: int = 100):
    supabase_logs = []
    try:
        query = supabase_admin.table("activity_logs").select("*").order("created_at", desc=True).limit(limit)
        if action_type and action_type.upper() != "ALL":
            query = query.eq("action_type", action_type.upper())
        resp = query.execute()
        if resp.data:
            supabase_logs = resp.data
    except Exception:
        pass

    local_logs = []
    if os.path.exists(LOCAL_LOGS_FILE):
        try:
            with open(LOCAL_LOGS_FILE, "r", encoding="utf-8") as f:
                local_logs = json.load(f)
            if action_type and action_type.upper() != "ALL":
                local_logs = [l for l in local_logs if l.get("action_type") == action_type.upper()]
        except Exception:
            local_logs = []

    # Merge logs uniquely by timestamp & details
    combined = supabase_logs + local_logs
    seen = set()
    unique_logs = []
    for l in combined:
        key = (l.get("created_at"), l.get("action_title"), l.get("details"))
        if key not in seen:
            seen.add(key)
            unique_logs.append(l)

    # Sort descending by parsed datetime
    def get_timestamp(entry):
        val = entry.get("created_at")
        if not val:
            return datetime.min
        try:
            if isinstance(val, str):
                s = val.strip().replace(" ", "T").replace("Z", "+00:00")
                # Append +00:00 if no timezone offset is attached
                if "+" not in s and "-" not in s[10:]:
                    s += "+00:00"
                return datetime.fromisoformat(s)
            return val
        except Exception:
            return datetime.min

    unique_logs.sort(key=get_timestamp, reverse=True)
    return unique_logs[:limit]
