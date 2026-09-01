"""Waste Management Routes."""

from fastapi import APIRouter, HTTPException, Depends
from ..config import supabase_admin, get_current_user
from ..activity_helper import log_activity_event
from datetime import datetime

router = APIRouter(prefix="/api/waste", tags=["waste"])

@router.get("")
def get_waste_logs():
    try:
        response = supabase_admin.table("waste_logs").select(
            "*, products(name, unit_of_measure), ingredients:ingredient_id(*)"
        ).order("logged_date", desc=True).limit(50).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def log_waste(waste_entry: dict, user = Depends(get_current_user)):
    try:
        ingredient_id = waste_entry.get("ingredient_id")
        product_id = waste_entry.get("product_id")
        quantity = float(waste_entry.get("quantity", 0))
        reason = waste_entry.get("reason", "Other")

        entry = {
            "quantity": quantity,
            "reason": reason,
            "logged_date": datetime.now().strftime('%Y-%m-%d')
        }

        item_name = "Item"

        if ingredient_id:
            entry["ingredient_id"] = ingredient_id
            response = supabase_admin.table("waste_logs").insert(entry).execute()

            try:
                ing_resp = supabase_admin.table("ingredients") \
                    .select("name, stock_quantity") \
                    .eq("id", ingredient_id) \
                    .single() \
                    .execute()
                if ing_resp.data:
                    item_name = ing_resp.data.get("name", "Ingredient")
                    current = float(ing_resp.data["stock_quantity"])
                    new_stock = max(0.0, current - quantity)
                    supabase_admin.table("ingredients") \
                        .update({"stock_quantity": round(new_stock, 4)}) \
                        .eq("id", ingredient_id) \
                        .execute()
            except Exception:
                pass
        else:
            entry["product_id"] = product_id
            response = supabase_admin.table("waste_logs").insert(entry).execute()
            try:
                p_resp = supabase_admin.table("products").select("name").eq("id", product_id).single().execute()
                if p_resp.data: item_name = p_resp.data.get("name", "Product")
            except Exception:
                pass

        log_activity_event(
            user=user,
            action_type="WASTE",
            action_title="Logged Waste",
            details=f"Logged {quantity} waste for '{item_name}' (Reason: {reason})"
        )

        return response.data[0] if response.data else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
