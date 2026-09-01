"""Analytics Routes."""

from fastapi import APIRouter, HTTPException
from ..config import supabase_admin
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from statsmodels.tsa.statespace.sarimax import SARIMAX
import warnings
import calendar as _cal
from datetime import date as _date

warnings.filterwarnings("ignore")

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

@router.get("/category")
def get_category_sales():
    try:
        sale_items = supabase_admin.table("sale_items").select("quantity, unit_price, products(category)").execute()
        return sale_items.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/waste_weekly")
def get_weekly_waste():
    try:
        waste_logs = supabase_admin.table("waste_logs").select(
            "quantity, logged_date, ingredients:ingredient_id(*)"
        ).execute()
        return waste_logs.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sarimax")
def get_sarimax_forecast():
    """
    Robust Analytics Engine:
    - Safeguard for 0 sales (No 500 error).
    - Future-testing support (Actuals can be in the future).
    - Wavy-Guard Hybrid Engine (Simulates pulse for < 14 days).
    - SARIMAX with school-week + PH holiday exogenous variables.
    - Philippine public holidays detected automatically (fixed + moveable).
    """
    try:
        # 1. Pull most recent 150 sales
        resp = supabase_admin.table("sales").select("total_amount, sale_date, refunded").order("sale_date", desc=True).limit(150).execute()
        rows = [r for r in (resp.data or []) if not r.get("refunded")]

        # LOCAL TIME: Always align to Taipei
        today = pd.Timestamp.now(tz="Asia/Taipei").date()

        # CASE 0: No data in database
        if not rows:
            return {
                "actual": [],
                "forecast": [{"date": str(today + timedelta(days=i)), "value": 0.0} for i in range(1, 8)]
            }

        # 2. Process Data
        df = pd.DataFrame(rows)
        df["sale_date"] = pd.to_datetime(df["sale_date"], format="mixed", utc=True).dt.tz_convert("Asia/Taipei")
        df["total_amount"] = df["total_amount"].astype(float)
        
        # Group by date for Daily Totals
        daily = df.groupby(df["sale_date"].dt.date)["total_amount"].sum().reset_index()
        daily = daily.sort_values("sale_date")
        daily.columns = ["date", "val"]
        
        # Align forecast to start after the latest found record or today
        last_data_date = daily["date"].iloc[-1]
        forecast_start_date = max(today, last_data_date)

        forecast = []
        actual = [
            {"date": str(row["date"]), "value": round(float(row["val"]), 2)}
            for _, row in daily.tail(30).iterrows()
        ]

        # ── School-Week Demand Prior ──────────────────────────────────────────
        # Business rule: Mon–Fri = high sales (students in school),
        #                Sat–Sun = low sales (students off school).
        # dow: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
        SCHOOL_WEEK_PRIOR = {0: 1.25, 1: 1.25, 2: 1.25, 3: 1.25, 4: 1.25,
                             5: 0.55, 6: 0.55}

        # ── Philippine Public Holidays ────────────────────────────────────────
        # On PH holidays schools are closed → sales drop even below weekend.
        HOLIDAY_MULTIPLIER = 0.45

        def _easter(year: int) -> _date:
            """Compute Easter Sunday for the given year (Anonymous Gregorian)."""
            a = year % 19
            b, c = divmod(year, 100)
            d, e = divmod(b, 4)
            f = (b + 8) // 25
            g = (b - f + 1) // 3
            h = (19 * a + b - d - g + 15) % 30
            i, k = divmod(c, 4)
            l = (32 + 2 * e + 2 * i - h - k) % 7
            m = (a + 11 * h + 22 * l) // 451
            month = (h + l - 7 * m + 114) // 31
            day   = ((h + l - 7 * m + 114) % 31) + 1
            return _date(year, month, day)

        def get_ph_holidays(year: int) -> set:
            """Return set of Philippine public holiday strings (YYYY-MM-DD)."""
            from datetime import timedelta as _td
            hols = set()

            # ── Fixed Regular Holidays ───────────────────────────────────────
            for m, d in [
                (1,  1),   # New Year's Day
                (4,  9),   # Araw ng Kagitingan (Bataan & Corregidor Day)
                (5,  1),   # Labor Day
                (6,  12),  # Independence Day
                (11, 1),   # All Saints' Day
                (11, 30),  # Bonifacio Day
                (12, 25),  # Christmas Day
                (12, 30),  # Rizal Day
            ]:
                hols.add(f"{year}-{m:02d}-{d:02d}")

            # ── Fixed Special Non-Working Holidays ───────────────────────────
            for m, d in [
                (2,  25),  # EDSA People Power Revolution Anniversary
                (8,  21),  # Ninoy Aquino Day
                (11, 2),   # All Souls' Day
                (12, 8),   # Feast of the Immaculate Conception
                (12, 24),  # Christmas Eve
                (12, 31),  # New Year's Eve
            ]:
                hols.add(f"{year}-{m:02d}-{d:02d}")

            # ── National Heroes Day: last Monday of August ────────────────────
            month_cal = _cal.monthcalendar(year, 8)
            mondays = [week[0] for week in month_cal if week[0] != 0]
            hols.add(f"{year}-08-{mondays[-1]:02d}")

            # ── Easter-based moveable holidays ───────────────────────────────
            easter = _easter(year)
            hols.add(str(easter - _td(days=3)))  # Maundy Thursday
            hols.add(str(easter - _td(days=2)))  # Good Friday
            hols.add(str(easter - _td(days=1)))  # Black Saturday

            return hols

        # Pre-compute holidays for years we'll need (this + next year)
        ph_holidays: set = get_ph_holidays(forecast_start_date.year)
        if forecast_start_date.year != (forecast_start_date + timedelta(days=7)).year:
            ph_holidays |= get_ph_holidays(forecast_start_date.year + 1)
        # Also needed for history exog spanning previous years
        history_years = {pd.Timestamp(d).year for d in daily["date"]}
        for yr in history_years:
            ph_holidays |= get_ph_holidays(yr)

        # CASE 1: Scarce Data (< 14 unique days) -> Wavy-Guard Simulation
        if len(daily) < 14:
            daily["dow"] = pd.to_datetime(daily["date"]).dt.dayofweek
            historical_avg = daily["val"].mean() if not daily.empty else 1.0
            learned_multipliers = daily.groupby("dow")["val"].mean() / historical_avg

            # Blend learned pattern (40%) with school-week prior (60%)
            # so even with sparse data the weekday shape is correct
            def blended_multiplier(dow):
                learned = float(learned_multipliers.get(dow, 1.0))
                prior   = SCHOOL_WEEK_PRIOR[dow]
                return 0.4 * learned + 0.6 * prior

            # Pulse Volume: Avg of last 7 days (or whatever we have)
            current_volume = float(daily["val"].tail(7).mean())

            for i in range(1, 8):
                f_date = forecast_start_date + timedelta(days=i)
                if str(f_date) in ph_holidays:
                    # PH holiday → students off regardless of weekday
                    jitter = 1.0 + (np.random.uniform(-0.02, 0.02))
                    val = round(current_volume * HOLIDAY_MULTIPLIER * jitter, 2)
                else:
                    multiplier = blended_multiplier(f_date.weekday())
                    jitter = 1.0 + (np.random.uniform(-0.04, 0.04))
                    val = round(current_volume * multiplier * jitter, 2)
                forecast.append({"date": str(f_date), "value": max(0.0, val)})

        # CASE 2: Sufficient Data (14+ days) -> SARIMAX + Weekday + Holiday Exogenous
        else:
            try:
                # Build 2-column exog: [is_weekday, is_holiday]
                # is_weekday: 1=Mon-Fri, 0=Sat-Sun
                # is_holiday: 1=PH public holiday (school closed), 0=normal day
                history_dates = list(daily["date"])

                def make_exog_row(d):
                    ds = str(d)
                    is_holiday = 1.0 if ds in ph_holidays else 0.0
                    is_weekday = 1.0 if pd.Timestamp(d).weekday() < 5 and not is_holiday else 0.0
                    return [is_weekday, is_holiday]

                exog_history = np.array([make_exog_row(d) for d in history_dates])

                series = daily["val"].values.astype(float)

                model = SARIMAX(
                    series,
                    exog=exog_history,
                    order=(1, 0, 1),
                    seasonal_order=(0, 1, 0, 7),
                    enforce_stationarity=True,
                    enforce_invertibility=False,
                )
                result = model.fit(disp=False, maxiter=50)

                # Build exog for the 7 forecast days
                exog_future = np.array(
                    [make_exog_row(forecast_start_date + timedelta(days=i+1))
                     for i in range(7)]
                )

                fc_values = result.forecast(steps=7, exog=exog_future)

                for i, val in enumerate(fc_values):
                    f_date = forecast_start_date + timedelta(days=i+1)
                    forecast.append({"date": str(f_date), "value": round(max(0.0, float(val)), 2)})

            except Exception as e:
                print(f"SARIMAX Fit Error: {e}")
                # Emergency fallback: apply school-week prior + holiday override
                avg = float(daily["val"].tail(7).mean())
                neutral_scale = sum(SCHOOL_WEEK_PRIOR.values()) / 7  # ≈ 1.0
                for i in range(7):
                    f_date = forecast_start_date + timedelta(days=i+1)
                    if str(f_date) in ph_holidays:
                        val = round(avg * HOLIDAY_MULTIPLIER, 2)
                    else:
                        prior = SCHOOL_WEEK_PRIOR[f_date.weekday()]
                        val = round(avg * (prior / neutral_scale), 2)
                    forecast.append({"date": str(f_date), "value": max(0.0, val)})

        return {"actual": actual, "forecast": forecast}

    except Exception as e:
        print(f"Global Forecast Engine Error: {e}")
        return {"actual": [], "forecast": []}
