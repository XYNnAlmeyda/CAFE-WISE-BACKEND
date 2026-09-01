"""Sales Routes — including Refund endpoint."""

from fastapi import APIRouter, HTTPException, Depends
from ..config import supabase_admin, get_current_user
from ..activity_helper import log_activity_event, get_user_info, PHT
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/sales", tags=["sales"])

@router.get("")
def get_sales():
    try:
        response = supabase_admin.table("sales").select("*, sale_items(quantity, unit_price, products(name))") \
            .order("sale_date", desc=True).limit(50).execute()
        return response.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def create_sale(payload: dict, user = Depends(get_current_user)):
    try:
        items = payload.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="At least one item is required.")

        subtotal = sum(
            float(i["quantity"]) * float(i["unit_price"]) for i in items
        )
        discount = float(payload.get("discount", 0.0))
        total_amount = max(0.0, subtotal - discount)

        sale_id = str(uuid.uuid4())
        actual_staff_id = user.id if hasattr(user, 'id') else payload.get("staff_id")

        sale_resp = supabase_admin.table("sales").insert({
            "id": sale_id,
            "sale_date": payload.get("sale_date"),
            "total_amount": round(total_amount, 2),
            "payment_method": payload.get("payment_method", "CASH"),
            "discount": round(discount, 2),
            "recorded_by": payload.get("recorded_by", "Staff"),
            "staff_id": actual_staff_id
        }).execute()

        if not sale_resp.data:
            raise HTTPException(status_code=500, detail="Failed to create sale record.")

        sale_items = [
            {
                "id": str(uuid.uuid4()),
                "sale_id": sale_id,
                "product_id": i["product_id"],
                "quantity": int(i["quantity"]),
                "unit_price": float(i["unit_price"])
            }
            for i in items
        ]
        supabase_admin.table("sale_items").insert(sale_items).execute()

        # Deduct raw ingredients via recipe
        deduction_errors = []
        for item in items:
            product_id = item["product_id"]
            qty_sold = float(item["quantity"])
            try:
                recipe_resp = supabase_admin.table("product_recipes") \
                    .select("ingredient_id, quantity_required") \
                    .eq("product_id", product_id) \
                    .execute()
                for recipe_row in (recipe_resp.data or []):
                    ingredient_id = recipe_row["ingredient_id"]
                    qty_to_deduct = qty_sold * float(recipe_row["quantity_required"])
                    ing_resp = supabase_admin.table("ingredients") \
                        .select("stock_quantity") \
                        .eq("id", ingredient_id) \
                        .single() \
                        .execute()
                    if ing_resp.data:
                        current_stock = float(ing_resp.data["stock_quantity"])
                        new_stock = max(0.0, current_stock - qty_to_deduct)
                        supabase_admin.table("ingredients") \
                            .update({"stock_quantity": round(new_stock, 4)}) \
                            .eq("id", ingredient_id) \
                            .execute()
            except Exception as e:
                deduction_errors.append(f"Failed to deduct ingredients for {product_id}: {str(e)}")

        total_item_count = sum(int(i["quantity"]) for i in items)
        disc_note = f" (Senior/PWD ₱{discount:,.2f} discount)" if discount > 0 else ""
        log_activity_event(
            user=user,
            action_type="SALES",
            action_title="Recorded Sale",
            details=f"Completed sale of {total_item_count} item(s) for ₱{round(total_amount, 2):,.2f} ({payload.get('payment_method', 'CASH')}{disc_note})"
        )

        return {
            "id": sale_id,
            "total_amount": total_amount,
            "message": "Sale recorded successfully",
            "warnings": deduction_errors if deduction_errors else None
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{sale_id}/refund")
def refund_sale(sale_id: str, payload: dict = {}, user = Depends(get_current_user)):
    """Mark a sale as refunded, automatically log items to waste_logs, and log activity."""
    try:
        # Fetch the sale with its items
        sale_resp = supabase_admin.table("sales") \
            .select("*, sale_items(quantity, unit_price, product_id, products(name))") \
            .eq("id", sale_id).single().execute()

        if not sale_resp.data:
            raise HTTPException(status_code=404, detail="Sale not found")

        sale = sale_resp.data

        # Guard: already refunded?
        if sale.get("refunded"):
            raise HTTPException(status_code=400, detail="This sale has already been refunded")

        info = get_user_info(user)
        refunded_at = datetime.now(PHT).isoformat()
        today_date_str = datetime.now(PHT).strftime('%Y-%m-%d')

        # 1. Mark refunded (gracefully skip if columns don't exist yet)
        try:
            supabase_admin.table("sales").update({
                "refunded": True,
                "refunded_by": info["user_name"],
                "refunded_at": refunded_at,
            }).eq("id", sale_id).execute()
        except Exception as e:
            print(f"Warning: Could not update refunded column on sales table: {e}")

        sale_items = sale.get("sale_items") or []

        # 2. Automatically log refunded items/recipe ingredients to waste_logs
        for si in sale_items:
            try:
                prod_id = si.get("product_id")
                qty = float(si.get("quantity", 1))
                if not prod_id:
                    continue

                # Check if product has recipe ingredients configured
                recipe_resp = supabase_admin.table("product_recipes") \
                    .select("ingredient_id, quantity_required") \
                    .eq("product_id", prod_id) \
                    .execute()
                recipe_rows = recipe_resp.data or []

                if recipe_rows:
                    # Log each recipe ingredient as waste
                    for r in recipe_rows:
                        ing_id = r["ingredient_id"]
                        req_qty = float(r.get("quantity_required", 0)) * qty
                        supabase_admin.table("waste_logs").insert({
                            "ingredient_id": ing_id,
                            "quantity": req_qty,
                            "reason": "Refunded Sale",
                            "logged_date": today_date_str
                        }).execute()
                else:
                    # Log product directly as waste
                    supabase_admin.table("waste_logs").insert({
                        "product_id": prod_id,
                        "quantity": qty,
                        "reason": "Refunded Sale",
                        "logged_date": today_date_str
                    }).execute()
            except Exception as we:
                print(f"Warning: Failed to log automatic waste entry for item {si}: {we}")

        # Build summary for logs
        items_summary = ", ".join(
            f"{si['quantity']}x {si['products']['name']}"
            for si in sale_items
            if si.get("products")
        ) or "items"
        total = float(sale.get("total_amount", 0))

        # 3. Log history events
        log_activity_event(
            user=user,
            action_type="SALES",
            action_title="Refunded Sale",
            details=f"Refunded ₱{total:,.2f} sale ({items_summary})"
        )

        log_activity_event(
            user=user,
            action_type="WASTE",
            action_title="Logged Waste (Refund)",
            details=f"Automatically logged waste for refunded items: {items_summary} (Reason: Refunded Sale)"
        )

        return {
            "success": True,
            "message": f"Refund for ₱{total:,.2f} processed and automatically logged to Waste!"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

