"""Inventory Management Routes."""

from fastapi import APIRouter, HTTPException, Depends
from ..config import supabase_admin, require_admin, get_current_user
from ..activity_helper import log_activity_event
from datetime import datetime, timedelta
from collections import defaultdict

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

@router.get("")
def get_inventory():
    try:
        # Get all products (stock is recipe-based, no need for inventory_transactions join)
        response = supabase_admin.table("products").select("*").execute()
        products = response.data or []

        # Ensure new columns have defaults if not yet present
        for p in products:
            p.setdefault("size", None)
            p.setdefault("default_price", None)
            p.setdefault("is_active", True)

        # For each product, compute recipe-based stock and check for expiring ingredients
        recipe_rows = []
        start = 0
        step = 1000
        while True:
            resp = supabase_admin.table("product_recipes") \
                .select("product_id, quantity_required, ingredients(name, stock_quantity, expiry_date)") \
                .range(start, start + step - 1) \
                .execute()
            batch = resp.data or []
            recipe_rows.extend(batch)
            if len(batch) < step:
                break
            start += step

        # Group recipe rows by product_id
        recipe_by_product = defaultdict(list)
        for row in recipe_rows:
            recipe_by_product[row["product_id"]].append(row)

        today = datetime.now()
        promo_window = today + timedelta(days=14)
        today_str = today.strftime('%Y-%m-%d')
        promo_window_str = promo_window.strftime('%Y-%m-%d')

        for product in products:
            pid = product["id"]
            product["is_promo"] = False
            product["promo_price"] = None
            product["expiring_ingredient"] = None
            product["expiry_date"] = None

            if pid in recipe_by_product:
                min_servable = float('inf')
                limiting_ingredient_name = None
                out_of_stock_ingredients = []
                
                # Check each ingredient in the recipe
                for row in recipe_by_product[pid]:
                    ing = row.get("ingredients") or {}
                    stock = float(ing.get("stock_quantity", 0))
                    qty_req = float(row.get("quantity_required", 1))
                    exp_date = ing.get("expiry_date")

                    # Promo check: if ANY ingredient is expiring soon
                    if exp_date and today_str <= exp_date <= promo_window_str:
                        product["is_promo"] = True
                        product["expiring_ingredient"] = ing.get("name")
                        product["expiry_date"] = exp_date

                    if qty_req > 0:
                        can_make = stock / qty_req
                        if can_make <= 0:
                            out_of_stock_ingredients.append(ing.get("name"))
                            
                        if can_make < min_servable:
                            min_servable = can_make
                            limiting_ingredient_name = ing.get("name")
                
                if min_servable == float('inf'):
                    product["recipe_stock"] = 0
                else:
                    product["recipe_stock"] = int(min_servable)
                    # If multiple are empty, join them. Otherwise use the lowest.
                    if len(out_of_stock_ingredients) > 0:
                        product["limiting_ingredient"] = ", ".join(filter(None, out_of_stock_ingredients))
                    else:
                        product["limiting_ingredient"] = limiting_ingredient_name
            else:
                product["recipe_stock"] = None  # No recipe — use batch stock on frontend
                product["limiting_ingredient"] = None

            # Apply 20% discount if on promo
            if product["is_promo"] and product.get("default_price"):
                product["promo_price"] = round(float(product["default_price"]) * 0.8, 2)

        return products
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/product")
def add_product(product: dict, user = Depends(require_admin)):
    try:
        # Strip empty strings from unique fields so they insert as NULL instead of ""
        # This prevents unique constraint violations (e.g. products_sku_key)
        unique_nullable_fields = ["sku"]
        for field in unique_nullable_fields:
            if field in product and (product[field] == "" or product[field] is None):
                product[field] = None

        response = supabase_admin.table("products").insert(product).execute()
        res_data = response.data[0] if response.data else None
        if res_data:
            p_name = res_data.get("name", "Product")
            log_activity_event(
                user=user,
                action_type="PRODUCTS",
                action_title="Added Product",
                details=f"Added new product '{p_name}' (Category: {res_data.get('category', 'General')})"
            )
        return res_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/product/{product_id}")
def update_product(product_id: str, payload: dict, user = Depends(require_admin)):
    """Update product fields like default_price, size, is_active, etc."""
    try:
        update = {}
        for field in ["default_price", "size", "is_active", "name", "category", "sku", "unit_of_measure", "reorder_level"]:
            if field in payload:
                update[field] = payload[field]
        if not update:
            raise HTTPException(status_code=400, detail="No fields to update")
        response = supabase_admin.table("products").update(update).eq("id", product_id).execute()
        res_data = response.data[0] if response.data else None
        if res_data:
            log_activity_event(
                user=user,
                action_type="PRODUCTS",
                action_title="Updated Product",
                details=f"Updated settings for '{res_data.get('name', 'Product')}'"
            )
        return res_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/product/{product_id}")
def delete_product(product_id: str, user = Depends(require_admin)):
    try:
        p_name = "Product"
        try:
            pr = supabase_admin.table("products").select("name").eq("id", product_id).single().execute()
            if pr.data: p_name = pr.data.get("name", "Product")
        except Exception:
            pass

        supabase_admin.table("sale_items").delete().eq("product_id", product_id).execute()
        supabase_admin.table("product_recipes").delete().eq("product_id", product_id).execute()
        supabase_admin.table("waste_logs").delete().eq("product_id", product_id).execute()
        supabase_admin.table("products").delete().eq("id", product_id).execute()

        log_activity_event(
            user=user,
            action_type="PRODUCTS",
            action_title="Deleted Product",
            details=f"Deleted product '{p_name}' (ID: {product_id})"
        )
        return {"message": "Product deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Products listing endpoint
@router.get("/products/list")
def get_products_list():
    try:
        response = supabase_admin.table("products") \
            .select("id, name, unit_of_measure, sku, size, default_price, is_active, category") \
            .order("name").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
