"""Dashboard Routes."""

from fastapi import APIRouter, HTTPException
from ..config import supabase_admin
from datetime import datetime, timedelta
import pandas as pd

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats")
def get_dashboard_stats():
    try:
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())           # Monday
        last_week_start = week_start - timedelta(weeks=1)
        last_week_end = week_start

        # --- Revenue this week vs last week (Timezone-aware) ---
        sales_resp = supabase_admin.table("sales").select("total_amount, sale_date, refunded").execute()
        raw_sales = sales_resp.data or []
        # Filter out refunded sales so revenue decreases on refund
        all_sales = [s for s in raw_sales if not s.get("refunded")]
        
        pdf = pd.DataFrame(all_sales)
        if not pdf.empty:
            pdf["sale_date"] = pd.to_datetime(pdf["sale_date"], format="mixed", utc=True)
            pdf["sale_date_local"] = pdf["sale_date"].dt.tz_convert("Asia/Taipei").dt.date
            
            # Filter out future data
            today_local = (datetime.now() + timedelta(hours=8)).date()
            pdf = pdf[pdf["sale_date_local"] <= today_local]

            week_start_local = week_start.date()
            last_week_start_local = last_week_start.date()
            last_week_end_local = last_week_end.date()

            revenue_this_week = pdf[pdf["sale_date_local"] >= week_start_local]["total_amount"].astype(float).sum()
            revenue_last_week = pdf[
                (pdf["sale_date_local"] >= last_week_start_local) & 
                (pdf["sale_date_local"] < last_week_end_local)
            ]["total_amount"].astype(float).sum()
        else:
            revenue_this_week = 0.0
            revenue_last_week = 0.0

        revenue_total = sum(float(s["total_amount"]) for s in all_sales)
        revenue_change = (
            round((revenue_this_week - revenue_last_week) / revenue_last_week * 100, 1)
            if revenue_last_week > 0
            else (100.0 if revenue_this_week > 0 else 0.0)
        )

        # --- Demand (forecasted next 7 days) ---
        qty_resp = supabase_admin.table("sale_items").select("quantity, sales(sale_date, refunded)").execute()
        raw_qty_rows = qty_resp.data or []
        # Exclude items belonging to refunded sales
        qty_rows = [q for q in raw_qty_rows if not (q.get("sales") or {}).get("refunded")]

        demand_total = 0.0
        demand_change = 0.0

        if qty_rows:
            from collections import defaultdict
            units_by_date = defaultdict(float)
            
            qdf = pd.DataFrame(qty_rows)
            # Expand sales column
            sales_expanded = qdf["sales"].apply(pd.Series)
            qdf["sale_date"] = pd.to_datetime(sales_expanded["sale_date"], format="mixed", utc=True)
            qdf["sale_date_local"] = qdf["sale_date"].dt.tz_convert("Asia/Taipei").dt.date
            
            daily_units = qdf.groupby("sale_date_local")["quantity"].sum().to_dict()
            units_by_date = {str(k): float(v) for k, v in daily_units.items()}

            if units_by_date:
                sorted_dates = sorted(units_by_date.keys())
                # Use last 14 days of data as the rolling window for forecasting
                last_14 = sorted_dates[-14:]
                last_14_values = [units_by_date[d] for d in last_14]
                daily_avg = sum(last_14_values) / len(last_14_values) if last_14_values else 0.0
                demand_total = round(daily_avg * 7, 1)  # Forecast next 7 days

                # Change % vs last week
                week_start_str = week_start.strftime('%Y-%m-%d')
                last_week_start_str = last_week_start.strftime('%Y-%m-%d')
                last_week_end_str = last_week_end.strftime('%Y-%m-%d')
                units_this_week = sum(
                    v for d, v in units_by_date.items()
                    if d >= week_start_str
                )
                units_last_week = sum(
                    v for d, v in units_by_date.items()
                    if last_week_start_str <= d < last_week_end_str
                )
                demand_change = (
                    round((units_this_week - units_last_week) / units_last_week * 100, 1)
                    if units_last_week > 0
                    else (100.0 if units_this_week > 0 else 0.0)
                )

        # --- Expiring ingredients (next 14 days) vs last period ---
        next_two_weeks = today + timedelta(days=14)
        expiring_resp = supabase_admin.table("ingredients").select("id") \
            .lte("expiry_date", next_two_weeks.strftime('%Y-%m-%d')) \
            .gte("expiry_date", today.strftime('%Y-%m-%d')) \
            .execute()
        expiring = len(expiring_resp.data or [])

        # Compare: how many were expiring in the same window last week
        prev_next_two_weeks = today - timedelta(days=7) + timedelta(days=14)
        expiring_prev_resp = supabase_admin.table("ingredients").select("id") \
            .lte("expiry_date", prev_next_two_weeks.strftime('%Y-%m-%d')) \
            .gte("expiry_date", (today - timedelta(days=7)).strftime('%Y-%m-%d')) \
            .execute()
        expiring_prev = len(expiring_prev_resp.data or [])
        expiring_change = (
            round((expiring - expiring_prev) / expiring_prev * 100, 1)
            if expiring_prev > 0
            else (100.0 if expiring > 0 else 0.0)
        )

        # --- Waste cost this week vs last week ---
        waste_resp = supabase_admin.table("waste_logs").select(
            "quantity, logged_date, ingredients:ingredient_id(cost_per_unit), products:product_id(default_price)"
        ).execute()
        waste_all = waste_resp.data or []

        def calc_waste(rows: list) -> float:
            total = 0.0
            for w in rows:
                ing = w.get("ingredients") or {}
                prod = w.get("products") or {}
                if ing and ing.get("cost_per_unit") is not None:
                    cost = float(ing.get("cost_per_unit") or 0)
                elif prod and prod.get("default_price") is not None:
                    cost = float(prod.get("default_price") or 0)
                else:
                    cost = 0.0
                total += float(w["quantity"]) * cost
            return total

        waste_this_week_rows = [
            w for w in waste_all
            if w.get("logged_date") and w["logged_date"][:10] >= week_start.strftime('%Y-%m-%d')
        ]
        waste_last_week_rows = [
            w for w in waste_all
            if w.get("logged_date")
            and last_week_start.strftime('%Y-%m-%d') <= w["logged_date"][:10] < last_week_end.strftime('%Y-%m-%d')
        ]

        waste = calc_waste(waste_all)
        waste_this_wk = calc_waste(waste_this_week_rows)
        waste_last_wk = calc_waste(waste_last_week_rows)
        waste_change = (
            round((waste_this_wk - waste_last_wk) / waste_last_wk * 100, 1)
            if waste_last_wk > 0
            else (100.0 if waste_this_wk > 0 else 0.0)
        )

        return {
            "revenue": revenue_total,
            "revenue_change": revenue_change,
            "demand": demand_total,
            "demand_change": demand_change,
            "expiring": expiring,
            "expiring_change": expiring_change,
            "waste": waste,
            "waste_change": waste_change
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/alerts")
def get_expiry_alerts():
    try:
        today = datetime.now()
        next_two_weeks = today + timedelta(days=14)

        response = supabase_admin.table("ingredients").select(
            "id, name, stock_quantity, unit, expiry_date, batch_number"
        ).lte("expiry_date", next_two_weeks.strftime('%Y-%m-%d')) \
         .gte("expiry_date", today.strftime('%Y-%m-%d')) \
         .gt("stock_quantity", 0) \
         .order("expiry_date").execute()
         
        # Map ingredients to match the expected format of Topbar.tsx
        alerts = []
        for ing in (response.data or []):
            alerts.append({
                "id": ing["id"],
                "batch_number": ing.get("batch_number", "Main"),
                "quantity": ing["stock_quantity"],
                "expiry_date": ing["expiry_date"],
                "products": {
                    "name": ing["name"],
                    "unit_of_measure": ing["unit"]
                }
            })
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
