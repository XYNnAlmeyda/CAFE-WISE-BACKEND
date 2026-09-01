"""Admin & Staff Management Routes."""

from fastapi import APIRouter, HTTPException, Depends
from ..config import supabase_admin, require_admin
from ..activity_helper import log_activity_event

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.post("/setup-admin")
def setup_admin(payload: dict):
    """
    Setup endpoint to create the first admin account.
    This endpoint does NOT require authentication (for initial setup only).
    WARNING: Remove or disable this endpoint in production!
    """
    if not supabase_admin:
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_ROLE_KEY is not configured on the backend.")

    try:
        email = payload.get("email")
        password = payload.get("password")
        full_name = payload.get("fullName")

        if not email or not password or not full_name:
            raise HTTPException(status_code=400, detail="email, password, and fullName are required")

        # 1. Create user in Auth
        auth_resp = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "user_metadata": {"full_name": full_name, "role": "ADMIN"},
            "email_confirm": True
        })

        if not auth_resp.user:
            raise HTTPException(status_code=400, detail="Failed to create auth user")

        user_id = auth_resp.user.id

        # 2. Create record in users table
        users_resp = supabase_admin.table("users").insert({
            "id": user_id,
            "full_name": full_name,
            "role": "ADMIN"
        }).execute()

        if not users_resp.data:
            # If users table insert fails, delete the auth user
            try:
                supabase_admin.auth.admin.delete_user(user_id)
            except:
                pass
            raise HTTPException(status_code=500, detail="Failed to create user record in database")

        return {
            "message": f"Admin account created for {email}",
            "user_id": user_id,
            "email": email,
            "role": "ADMIN",
            "full_name": full_name,
            "note": "This account has ADMIN privileges"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating admin: {str(e)}")

@router.get("/staff")
def get_staff(user = Depends(require_admin)):
    try:
        # Fetch all profiles EXCEPT the current user
        response = supabase_admin.table("users").select("*").neq("id", user.id).execute()
        return response.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: str, user = Depends(require_admin)):
    if not supabase_admin:
        raise HTTPException(status_code=500, detail="Admin access not configured")
    
    try:
        # Get user details for log
        staff_name = "Staff Member"
        try:
            u_resp = supabase_admin.table("users").select("full_name").eq("id", staff_id).single().execute()
            if u_resp.data: staff_name = u_resp.data.get("full_name", "Staff Member")
        except Exception:
            pass

        # 1. Delete from Auth
        auth_resp = supabase_admin.auth.admin.delete_user(staff_id)
        
        # 2. Delete from Profiles (manual check for cascade)
        supabase_admin.table("users").delete().eq("id", staff_id).execute()
        
        log_activity_event(
            user=user,
            action_type="STAFF",
            action_title="Deleted Staff Account",
            details=f"Deleted user account '{staff_name}' (ID: {staff_id})"
        )

        return {"message": "Staff deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create-staff")
def create_staff(payload: dict, user = Depends(require_admin)):
    if not supabase_admin:
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_ROLE_KEY is not configured on the backend.")

    try:
        email = payload.get("email")
        password = payload.get("password")
        full_name = payload.get("fullName")

        role = payload.get("role", "STAFF").upper()
        if role not in ["ADMIN", "MANAGER", "STAFF"]:
            role = "STAFF"

        # 1. Create user in Auth
        auth_resp = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "user_metadata": {"full_name": full_name, "role": role},
            "email_confirm": True
        })

        if not auth_resp.user:
            raise HTTPException(status_code=400, detail="Failed to create auth user")

        user_id = auth_resp.user.id

        # 2. Create record in users table
        users_resp = supabase_admin.table("users").insert({
            "id": user_id,
            "full_name": full_name,
            "role": role
        }).execute()

        if not users_resp.data:
            # If users table insert fails, we should delete the auth user
            try:
                supabase_admin.auth.admin.delete_user(user_id)
            except:
                pass
            raise HTTPException(status_code=500, detail="Failed to create user record in database")

        return {
            "message": f"Staff account created for {email}",
            "user_id": user_id,
            "email": email,
            "role": role,
            "full_name": full_name
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating staff: {str(e)}")


# ─────────────────────────────────────────────
# USER CREATION ENDPOINTS (by role)
# ─────────────────────────────────────────────

def _create_user_with_role(email: str, password: str, full_name: str, role: str, performing_user=None):
    """Helper function to create users with different roles"""
    if not supabase_admin:
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_ROLE_KEY is not configured on the backend.")

    try:
        # Validate inputs
        if not email or not password or not full_name:
            raise HTTPException(status_code=400, detail="email, password, and fullName are required")

        # 1. Create user in Auth
        auth_resp = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "user_metadata": {"full_name": full_name, "role": role},
            "email_confirm": True
        })

        if not auth_resp.user:
            raise HTTPException(status_code=400, detail="Failed to create auth user")

        user_id = auth_resp.user.id

        # 2. Create record in users table
        users_resp = supabase_admin.table("users").insert({
            "id": user_id,
            "full_name": full_name,
            "role": role
        }).execute()

        if not users_resp.data:
            try:
                supabase_admin.auth.admin.delete_user(user_id)
            except:
                pass
            raise HTTPException(status_code=500, detail="Failed to create user record in database")

        log_activity_event(
            user=performing_user,
            action_type="STAFF",
            action_title="Created Staff Account",
            details=f"Created {role} account for '{full_name}' ({email})"
        )

        return {
            "message": f"{role} account created successfully",
            "user_id": user_id,
            "email": email,
            "role": role,
            "full_name": full_name
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating {role.lower()}: {str(e)}")


@router.post("/users")
def create_user(payload: dict, user = Depends(require_admin)):
    return _create_user_with_role(
        payload.get("email"),
        payload.get("password"),
        payload.get("fullName"),
        "STAFF",
        performing_user=user
    )


@router.post("/staff")
def create_staff_user(payload: dict, user = Depends(require_admin)):
    return _create_user_with_role(
        payload.get("email"),
        payload.get("password"),
        payload.get("fullName"),
        "STAFF",
        performing_user=user
    )


@router.post("/managers")
def create_manager(payload: dict, user = Depends(require_admin)):
    return _create_user_with_role(
        payload.get("email"),
        payload.get("password"),
        payload.get("fullName"),
        "ADMIN",
        performing_user=user
    )


@router.post("/admins")
def create_admin_user(payload: dict, user = Depends(require_admin)):
    return _create_user_with_role(
        payload.get("email"),
        payload.get("password"),
        payload.get("fullName"),
        "ADMIN",
        performing_user=user
    )
