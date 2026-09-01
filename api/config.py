"""Configuration and shared dependencies for the API."""

from fastapi import HTTPException, Depends, Header
from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase Clients safely
url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

service_key = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or 
    os.environ.get("VITE_SUPABASE_SERVICE_KEY") or
    os.environ.get("SERVICE_ROLE_KEY") or
    ""
)

try:
    supabase: Client = create_client(url, key) if (url and key) else None
except Exception:
    supabase = None

try:
    if service_key and url:
        supabase_admin: Client = create_client(url, service_key)
    elif url and key:
        supabase_admin: Client = create_client(url, key)
    else:
        supabase_admin = None
except Exception:
    supabase_admin = None

def check_admin_configured():
    if not service_key:
        raise HTTPException(
            status_code=500, 
            detail="CRITICAL: Backend is not configured with a Service Role Key (SUPABASE_SERVICE_ROLE_KEY). Database operations will fail RLS checks. Please add this variable to Vercel/environment."
        )

import base64
import json
from datetime import datetime

class TokenUser:
    def __init__(self, user_id: str, email: str = "", metadata: dict = None):
        self.id = user_id
        self.email = email
        self.user_metadata = metadata or {}

def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload = parts[1]
            padding = "=" * (4 - (len(payload) % 4))
            decoded_bytes = base64.urlsafe_b64decode(payload + padding)
            return json.loads(decoded_bytes.decode("utf-8"))
    except Exception:
        pass
    return {}

# Authentication Dependency
async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = authorization.split(" ")[1]
    if supabase:
        try:
            # Verify token with Supabase
            user_resp = supabase.auth.get_user(token)
            if user_resp and getattr(user_resp, "user", None):
                return user_resp.user
        except Exception:
            pass

    # Fallback: extract user claims directly from the JWT payload
    payload = _decode_jwt_payload(token)
    if payload and payload.get("sub"):
        return TokenUser(
            user_id=payload.get("sub"),
            email=payload.get("email", ""),
            metadata=payload.get("user_metadata") or payload.get("app_metadata") or {}
        )
    raise HTTPException(status_code=401, detail="Auth error: Invalid or expired token")

async def require_admin(user = Depends(get_current_user)):
    check_admin_configured()
    # Check role from user metadata or profile table
    metadata_role = user.user_metadata.get("role")
    print(f"DEBUG: Metadata role for user {user.id}: {metadata_role}")
    
    if metadata_role in ["ADMIN", "MANAGER"]:
        return user
        
    # Fallback check profiles table
    try:
        print(f"DEBUG: Checking profiles table for user {user.id}...")
        profile_resp = supabase_admin.table("users").select("role").eq("id", user.id).execute()
        print(f"DEBUG: Profile response: {profile_resp.data}")
        
        profile_data = profile_resp.data[0] if profile_resp.data else None
        role = profile_data.get("role") if profile_data else None
        print(f"DEBUG: Found role in DB: {role}")
        
        if not role or role.upper() not in ["ADMIN", "MANAGER"]:
            print(f"DEBUG: Access denied. Role '{role}' not authorized.")
            raise HTTPException(status_code=403, detail="Admin or Manager access required")
    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG: Unexpected error in require_admin: {str(e)}")
        raise HTTPException(status_code=403, detail=f"Admin or Manager access error: {str(e)}")
    return user
