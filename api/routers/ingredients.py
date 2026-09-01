"""Ingredients Management Routes."""

from fastapi import APIRouter, HTTPException, Depends
from ..config import supabase_admin, require_admin

router = APIRouter(prefix="/api/ingredients", tags=["ingredients"])

@router.get("")
def get_ingredients():
    try:
        resp = supabase_admin.table("ingredients").select("*").order("name").execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def add_ingredient(payload: dict, user = Depends(require_admin)):
    try:
        resp = supabase_admin.table("ingredients").insert({
            "name": payload["name"],
            "unit": payload["unit"],
            "stock_quantity": float(payload.get("stock_quantity", 0)),
            "min_stock_level": float(payload.get("min_stock_level", 0)),
            "cost_per_unit": float(payload.get("cost_per_unit", 0)),
            "expiry_date": payload.get("expiry_date", None),
            "batch_number": payload.get("batch_number", "Main")
        }).execute()
        return resp.data[0] if resp.data else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{ingredient_id}")
def update_ingredient(ingredient_id: str, payload: dict, user = Depends(require_admin)):
    try:
        update = {}
        for field in ["name", "unit", "stock_quantity", "min_stock_level", "cost_per_unit", "expiry_date", "batch_number"]:
            if field in payload:
                update[field] = payload[field]
        resp = supabase_admin.table("ingredients").update(update).eq("id", ingredient_id).execute()
        return resp.data[0] if resp.data else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{ingredient_id}")
def delete_ingredient(ingredient_id: str, user = Depends(require_admin)):
    try:
        supabase_admin.table("waste_logs").delete().eq("ingredient_id", ingredient_id).execute()
        supabase_admin.table("product_recipes").delete().eq("ingredient_id", ingredient_id).execute()
        supabase_admin.table("ingredients").delete().eq("id", ingredient_id).execute()
        return {"message": "Ingredient deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
