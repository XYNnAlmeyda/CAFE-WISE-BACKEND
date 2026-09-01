"""Recipe Management Routes."""

from fastapi import APIRouter, HTTPException, Depends
from ..config import supabase_admin, require_admin, get_current_user
from ..activity_helper import log_activity_event

router = APIRouter(prefix="/api/recipes", tags=["recipes"])

@router.get("/{product_id}")
def get_recipe(product_id: str):
    """Get recipe for a product with ingredient details."""
    try:
        resp = supabase_admin.table("product_recipes") \
            .select("*, ingredients(id, name, unit, stock_quantity, cost_per_unit)") \
            .eq("product_id", product_id) \
            .execute()
        
        recipe_data = resp.data or []
        
        # Calculate total cost per unit
        total_cost = 0
        for item in recipe_data:
            if item.get("ingredients"):
                cost_per_unit = item["ingredients"].get("cost_per_unit", 0)
                qty = item.get("quantity_required", 0)
                total_cost += cost_per_unit * qty
        
        return {
            "items": recipe_data,
            "total_cost_per_unit": round(total_cost, 2),
            "ingredient_count": len(recipe_data)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{product_id}")
def add_recipe_ingredient(product_id: str, payload: dict, user = Depends(require_admin)):
    """Add or update ingredient in recipe."""
    try:
        if "ingredient_id" not in payload or "quantity_required" not in payload:
            raise HTTPException(status_code=400, detail="Missing ingredient_id or quantity_required")
        
        ing_id = payload["ingredient_id"]
        qty = float(payload["quantity_required"])

        # Fetch names for clear log details
        prod_name = "Product"
        ing_name = "Ingredient"
        try:
            pr = supabase_admin.table("products").select("name").eq("id", product_id).single().execute()
            if pr.data: prod_name = pr.data.get("name", "Product")
            ir = supabase_admin.table("ingredients").select("name, unit").eq("id", ing_id).single().execute()
            if ir.data: ing_name = ir.data.get("name", "Ingredient")
        except Exception:
            pass

        resp = supabase_admin.table("product_recipes").upsert({
            "product_id": product_id,
            "ingredient_id": ing_id,
            "quantity_required": qty,
        }, on_conflict="product_id,ingredient_id").execute()
        
        log_activity_event(
            user=user,
            action_type="RECIPE",
            action_title="Added Ingredient to Recipe",
            details=f"Added/Updated {qty} of '{ing_name}' in '{prod_name}' recipe"
        )
        return {
            "success": True,
            "message": "Ingredient added to recipe",
            "data": resp.data[0] if resp.data else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid quantity_required value")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{product_id}/{ingredient_id}")
def update_recipe_quantity(product_id: str, ingredient_id: str, payload: dict, user = Depends(require_admin)):
    """Update quantity of ingredient in recipe."""
    try:
        if "quantity_required" not in payload:
            raise HTTPException(status_code=400, detail="Missing quantity_required")
        
        qty = float(payload["quantity_required"])

        prod_name = "Product"
        ing_name = "Ingredient"
        try:
            pr = supabase_admin.table("products").select("name").eq("id", product_id).single().execute()
            if pr.data: prod_name = pr.data.get("name", "Product")
            ir = supabase_admin.table("ingredients").select("name").eq("id", ingredient_id).single().execute()
            if ir.data: ing_name = ir.data.get("name", "Ingredient")
        except Exception:
            pass

        resp = supabase_admin.table("product_recipes").update({
            "quantity_required": qty
        }).eq("product_id", product_id).eq("ingredient_id", ingredient_id).execute()
        
        log_activity_event(
            user=user,
            action_type="RECIPE",
            action_title="Updated Recipe Ingredient",
            details=f"Changed quantity of '{ing_name}' in '{prod_name}' recipe to {qty}"
        )
        return {
            "success": True,
            "message": "Recipe quantity updated",
            "data": resp.data[0] if resp.data else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid quantity_required value")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{product_id}/{ingredient_id}")
def remove_recipe_ingredient(product_id: str, ingredient_id: str, user = Depends(require_admin)):
    """Remove ingredient from recipe."""
    try:
        prod_name = "Product"
        ing_name = "Ingredient"
        try:
            pr = supabase_admin.table("products").select("name").eq("id", product_id).single().execute()
            if pr.data: prod_name = pr.data.get("name", "Product")
            ir = supabase_admin.table("ingredients").select("name").eq("id", ingredient_id).single().execute()
            if ir.data: ing_name = ir.data.get("name", "Ingredient")
        except Exception:
            pass

        resp = supabase_admin.table("product_recipes") \
            .delete() \
            .eq("product_id", product_id) \
            .eq("ingredient_id", ingredient_id) \
            .execute()
        
        log_activity_event(
            user=user,
            action_type="RECIPE",
            action_title="Removed Ingredient from Recipe",
            details=f"Removed '{ing_name}' from '{prod_name}' recipe"
        )
        return {
            "success": True,
            "message": "Ingredient removed from recipe"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{product_id}/build")
def build_recipe(product_id: str, payload: dict = {}, user = Depends(get_current_user)):
    """Build / Prepare a recipe without deducting ingredient stock."""
    try:
        qty_to_build = int(payload.get("quantity", 1))
        if qty_to_build <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be at least 1")

        prod_resp = supabase_admin.table("products").select("name").eq("id", product_id).single().execute()
        product_name = prod_resp.data.get("name", "Product") if prod_resp.data else "Product"

        recipe_resp = supabase_admin.table("product_recipes") \
            .select("*, ingredients(id, name, stock_quantity, unit)") \
            .eq("product_id", product_id) \
            .execute()
        
        recipe_items = recipe_resp.data or []
        if not recipe_items:
            raise HTTPException(status_code=400, detail=f"No recipe ingredients configured for '{product_name}'")

        log_activity_event(
            user=user,
            action_type="RECIPE",
            action_title="Built Recipe",
            details=f"Prepared {qty_to_build} batch(es) of '{product_name}' recipe without changing ingredient inventory"
        )

        return {"success": True, "message": f"Successfully built {qty_to_build} unit(s) of '{product_name}'"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{product_id}/validate")
def validate_recipe_feasibility(product_id: str):
    """Check if recipe can be made with current stock. Returns how many units can be made."""
    try:
        # Get recipe
        recipe_resp = supabase_admin.table("product_recipes") \
            .select("*, ingredients(id, name, unit, stock_quantity)") \
            .eq("product_id", product_id) \
            .execute()
        
        recipe_items = recipe_resp.data or []
        
        if not recipe_items:
            return {
                "can_make": 0,
                "reason": "No recipe defined",
                "limiting_ingredient": None,
                "recipe_items": []
            }
        
        # Calculate how many units can be made
        min_can_make = float('inf')
        limiting_ingredient = None
        
        for item in recipe_items:
            ingredients = item.get("ingredients")
            if not ingredients:
                return HTTPException(status_code=400, detail="Ingredient not found")
            
            stock = ingredients.get("stock_quantity", 0)
            required = item.get("quantity_required", 0)
            
            if required <= 0:
                continue
            
            can_make = int(stock / required)
            
            if can_make < min_can_make:
                min_can_make = can_make
                limiting_ingredient = {
                    "id": ingredients.get("id"),
                    "name": ingredients.get("name"),
                    "stock": stock,
                    "required": required,
                    "unit": ingredients.get("unit")
                }
        
        final_count = 0 if min_can_make == float('inf') else min_can_make
        
        return {
            "can_make": final_count,
            "limiting_ingredient": limiting_ingredient,
            "reason": "Limited by " + limiting_ingredient["name"] if limiting_ingredient else "Full stock available",
            "recipe_items": len(recipe_items)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
