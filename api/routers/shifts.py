"""Shift Management Routes — Open/Close Shift tracking."""

from fastapi import APIRouter, HTTPException, Depends
from ..config import supabase_admin, get_current_user
from ..activity_helper import log_activity_event, get_user_info, PHT
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/shifts", tags=["shifts"])


def _current_time_pht() -> str:
    return datetime.now(PHT).isoformat()


@router.get("/current")
def get_current_shift(user=Depends(get_current_user)):
    """Return the currently open shift with cash and e-wallet sales breakdown, or null if none."""
    try:
        resp = supabase_admin.table("shifts") \
            .select("*") \
            .eq("status", "OPEN") \
            .order("opened_at", desc=True) \
            .limit(1) \
            .execute()
        rows = resp.data or []
        if not rows:
            return None

        shift = rows[0]
        opened_at = shift.get("opened_at")

        # Calculate sales during this shift
        cash_sales = 0.0
        ewallet_sales = 0.0

        if opened_at:
            try:
                sales_resp = supabase_admin.table("sales") \
                    .select("total_amount, payment_method, refunded") \
                    .gte("sale_date", opened_at) \
                    .execute()
                sales = [s for s in (sales_resp.data or []) if not s.get("refunded")]

                for s in sales:
                    amt = float(s.get("total_amount") or 0)
                    pm = str(s.get("payment_method") or "").upper()
                    if pm in ["E-WALLET", "EWALLET", "GCASH", "MAYA"]:
                        ewallet_sales += amt
                    else:
                        cash_sales += amt
            except Exception as se:
                print(f"Warning: Failed to fetch shift sales: {se}")

        opening_cash = float(shift.get("opening_cash") or 0)
        opening_ewallet = float(shift.get("opening_ewallet") or 0)
        shift["cash_sales"] = round(cash_sales, 2)
        shift["ewallet_sales"] = round(ewallet_sales, 2)
        shift["total_sales"] = round(cash_sales + ewallet_sales, 2)
        shift["expected_cash"] = round(opening_cash + cash_sales, 2)
        shift["expected_ewallet"] = round(opening_ewallet + ewallet_sales, 2)

        return shift
    except Exception as e:
        return None


@router.get("")
def list_shifts(user=Depends(get_current_user)):
    """Return last 30 shifts (admin history)."""
    try:
        resp = supabase_admin.table("shifts") \
            .select("*") \
            .order("opened_at", desc=True) \
            .limit(30) \
            .execute()
        return resp.data or []
    except Exception as e:
        return []


@router.post("/open")
def open_shift(payload: dict, user=Depends(get_current_user)):
    """Open a new shift with cash float and e-wallet float."""
    try:
        # Check if a shift is already open
        existing_resp = supabase_admin.table("shifts") \
            .select("id") \
            .eq("status", "OPEN") \
            .limit(1) \
            .execute()
        if existing_resp.data:
            raise HTTPException(status_code=400, detail="A shift is already open. Please close it first.")

        info = get_user_info(user)
        opening_cash = float(payload.get("opening_cash", 0))
        opening_ewallet = float(payload.get("opening_ewallet", 0))
        shift_id = str(uuid.uuid4())
        now = _current_time_pht()

        insert_data = {
            "id": shift_id,
            "opened_by": info["user_name"],
            "opened_at": now,
            "opening_cash": opening_cash,
            "status": "OPEN",
        }
        try:
            insert_data["opening_ewallet"] = opening_ewallet
            supabase_admin.table("shifts").insert(insert_data).execute()
        except Exception:
            insert_data.pop("opening_ewallet", None)
            supabase_admin.table("shifts").insert(insert_data).execute()

        ew_str = f" and ₱{opening_ewallet:,.2f} opening e-wallet" if opening_ewallet > 0 else ""
        log_activity_event(
            user=user,
            action_type="SHIFT",
            action_title="Opened Shift",
            details=f"{info['user_name']} opened a new shift with ₱{opening_cash:,.2f} opening cash{ew_str}"
        )

        return {
            "success": True,
            "shift_id": shift_id,
            "opened_by": info["user_name"],
            "opened_at": now,
            "opening_cash": opening_cash,
            "status": "OPEN",
            "message": "Shift opened successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/close")
def close_shift(payload: dict, user=Depends(get_current_user)):
    """Close the currently open shift."""
    try:
        # Find the open shift
        resp = supabase_admin.table("shifts") \
            .select("*") \
            .eq("status", "OPEN") \
            .order("opened_at", desc=True) \
            .limit(1) \
            .execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=400, detail="No open shift found to close.")

        shift = rows[0]
        shift_id = shift["id"]

        info = get_user_info(user)
        closing_cash = float(payload.get("closing_cash", 0))
        closing_ewallet = float(payload.get("closing_ewallet", 0))
        notes = payload.get("notes", "").strip()
        now = _current_time_pht()

        update_data = {
            "closed_by": info["user_name"],
            "closed_at": now,
            "closing_cash": closing_cash,
            "notes": notes or None,
            "status": "CLOSED",
        }
        try:
            update_data["closing_ewallet"] = closing_ewallet
            supabase_admin.table("shifts").update(update_data).eq("id", shift_id).execute()
        except Exception:
            update_data.pop("closing_ewallet", None)
            supabase_admin.table("shifts").update(update_data).eq("id", shift_id).execute()

        opening_cash = float(shift.get("opening_cash", 0))
        opening_ewallet = float(shift.get("opening_ewallet", 0))
        cash_diff = closing_cash - opening_cash
        ew_diff = closing_ewallet - opening_ewallet

        log_activity_event(
            user=user,
            action_type="SHIFT",
            action_title="Closed Shift",
            details=(
                f"{info['user_name']} closed shift. "
                f"Cash: ₱{opening_cash:,.2f}→₱{closing_cash:,.2f} (diff: ₱{cash_diff:,.2f}) | "
                f"E-Wallet: ₱{opening_ewallet:,.2f}→₱{closing_ewallet:,.2f} (diff: ₱{ew_diff:,.2f})"
                + (f" | Notes: {notes}" if notes else "")
            )
        )

        return {
            "success": True,
            "message": "Shift closed successfully",
            "shift_id": shift_id,
            "opening_cash": opening_cash,
            "closing_cash": closing_cash,
            "cash_difference": cash_diff,
            "opening_ewallet": opening_ewallet,
            "closing_ewallet": closing_ewallet,
            "ewallet_difference": ew_diff,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
