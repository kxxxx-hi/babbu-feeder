import math
import os
from datetime import date, datetime
from typing import Optional, Tuple, List

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import Vercel Blob storage manager
try:
    from .storage import CloudStorageManager
    storage_manager = CloudStorageManager()
    STORAGE_AVAILABLE = True
    print("Vercel Blob Storage initialized successfully")
except Exception as e:
    print(f"Warning: Vercel Blob Storage not available: {e}")
    import traceback
    traceback.print_exc()
    STORAGE_AVAILABLE = False
    storage_manager = None

# Fix template path for Vercel - templates are in parent directory
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
app = Flask(__name__, template_folder=template_dir)

# Add custom Jinja2 filter for strftime
@app.template_filter('strftime')
def strftime_filter(date_format):
    """Custom filter to format current date/time"""
    from datetime import datetime
    return datetime.now().strftime(date_format)

# ---------- Math ----------
def weeks_between(d1: date, d2: date) -> float:
    return (d2 - d1).days / 7.0

def current_age_weeks(anchor_date: date, anchor_age_weeks: float) -> float:
    return anchor_age_weeks + weeks_between(anchor_date, date.today())

def infer_life_stage(age_weeks: float) -> str:
    if age_weeks < 16:
        return "kitten_0_4m"
    elif age_weeks < 52:
        return "kitten_4_12m"
    else:
        return "adult_neutered"

def rer_kcal(weight_kg: float) -> float:
    return 70.0 * (weight_kg ** 0.75)

def der_factor(stage: str) -> float:
    mapping = {
        "kitten_0_4m": 2.5,
        "kitten_4_12m": 2.0,
        "adult_neutered": 1.2,
        "adult_intact": 1.4,
        "adult_obese_prone": 1.0,
    }
    return mapping.get(stage, 1.2)

def der_kcal(weight_kg: float, stage: str) -> float:
    return rer_kcal(weight_kg) * der_factor(stage)

def kcal_split(total_kcal: float, meals_per_day: int, diet_list: List[dict], foods_list: List[dict]) -> pd.DataFrame:
    if total_kcal <= 0 or meals_per_day <= 0 or not diet_list or not foods_list:
        return pd.DataFrame(columns=["Food","pct","kcal_day","kcal_meal","qty_per_meal","unit","grams_per_meal"])
    
    foods_dict = {f["id"]: f for f in foods_list}
    out = []
    for diet_item in diet_list:
        fid = int(diet_item["food_id"])
        pct = float(diet_item["pct_daily_kcal"])
        kcal_day = total_kcal * pct / 100.0
        kcal_meal = kcal_day / meals_per_day
        food = foods_dict.get(fid)
        if not food:
            continue
        unit = food["unit"]
        kpu = float(food["kcal_per_unit"])
        qty_per_meal = kcal_meal / kpu if kpu > 0 else 0.0
        grams_pm = None
        if unit == "kcal_per_g":
            grams_pm = qty_per_meal
        elif unit == "kcal_per_cup":
            gpc = food.get("grams_per_cup")
            grams_pm = qty_per_meal * gpc if gpc else None
        out.append({
            "Food": food["name"],
            "pct": pct,
            "kcal_day": round(kcal_day, 1),
            "kcal_meal": round(kcal_meal, 1),
            "qty_per_meal": round(qty_per_meal, 3),
            "unit": ("g" if unit=="kcal_per_g" else "cups"),
            "grams_per_meal": None if grams_pm is None else round(grams_pm, 1),
        })
    return pd.DataFrame(out)

# ---------- Vercel Blob Data helpers ----------
def get_profile():
    """Get cat profile from Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        print("Storage not available, returning default profile")
        return {
            "id": 1,
            "name": None,
            "anchor_date": date.today().isoformat(),
            "anchor_age_weeks": 8.0,
            "meals_per_day": 3,
            "life_stage_override": None
        }
    try:
        data = storage_manager.read_json("cat_profile")
        print(f"Read data from blob: {data}")
        profile = data.get("profile", {})
        if not profile:
            print("No profile found in blob data, returning default")
            # Return default profile
            return {
                "id": 1,
                "name": None,
                "anchor_date": date.today().isoformat(),
                "anchor_age_weeks": 8.0,
                "meals_per_day": 3,
                "life_stage_override": None
            }
        print(f"Found profile: {profile}")
        return profile
    except Exception as e:
        print(f"Error reading profile: {e}")
        import traceback
        traceback.print_exc()
        # Return default on error
        return {
            "id": 1,
            "name": None,
            "anchor_date": date.today().isoformat(),
            "anchor_age_weeks": 8.0,
            "meals_per_day": 3,
            "life_stage_override": None
        }

def save_profile(profile_data: dict):
    """Save cat profile to Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        print("Storage not available, cannot save profile")
        return
    try:
        data = {"profile": profile_data}
        print(f"Saving profile: {profile_data}")
        storage_manager.write_json(data, "cat_profile")
        print("Profile saved successfully")
    except Exception as e:
        print(f"Error saving profile: {e}")
        import traceback
        traceback.print_exc()

def get_weights():
    """Get weight logs from Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = storage_manager.read_json("logs")
        weights = data.get("weights", [])
        return sorted(weights, key=lambda x: x.get("dt", ""))
    except Exception as e:
        print(f"Error reading weights: {e}")
        return []

def save_weight(weight_dt: str, weight_kg: float):
    """Save weight log to Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = storage_manager.read_json("logs")
        weights = data.get("weights", [])
        
        # Remove existing entry for this date if exists
        weights = [w for w in weights if w.get("dt") != weight_dt]
        
        # Add new entry
        weights.append({
            "dt": weight_dt,
            "weight_kg": weight_kg
        })
        
        # Sort by date
        weights = sorted(weights, key=lambda x: x.get("dt", ""))
        data["weights"] = weights
        storage_manager.write_json(data, "logs")
    except Exception as e:
        print(f"Error saving weight: {e}")
        import traceback
        traceback.print_exc()

def get_foods():
    """Get foods from Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = storage_manager.read_json("foods")
        foods = data.get("foods", [])
        return sorted(foods, key=lambda x: x.get("name", ""))
    except Exception as e:
        print(f"Error reading foods: {e}")
        return []

def save_food(food_data: dict):
    """Save food to Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = storage_manager.read_json("foods")
        foods = data.get("foods", [])
        
        # Generate ID if not present
        if "id" not in food_data or not food_data["id"]:
            max_id = max([f.get("id", 0) for f in foods], default=0)
            food_data["id"] = max_id + 1
        
        foods.append(food_data)
        data["foods"] = foods
        storage_manager.write_json(data, "foods")
    except Exception as e:
        print(f"Error saving food: {e}")
        import traceback
        traceback.print_exc()

def delete_food(food_id: int):
    """Delete food from Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = storage_manager.read_json("foods")
        foods = data.get("foods", [])
        foods = [f for f in foods if f.get("id") != food_id]
        data["foods"] = foods
        storage_manager.write_json(data, "foods")
    except Exception as e:
        print(f"Error deleting food: {e}")
        import traceback
        traceback.print_exc()

def get_diet():
    """Get diet plan from Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = storage_manager.read_json("cat_profile")
        profile = data.get("profile", {})
        return profile.get("diet", [])
    except Exception as e:
        print(f"Error reading diet: {e}")
        return []

def save_diet(diet_list: List[dict]):
    """Save diet plan to Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = storage_manager.read_json("cat_profile")
        profile = data.get("profile", {})
        profile["diet"] = diet_list
        data["profile"] = profile
        storage_manager.write_json(data, "cat_profile")
    except Exception as e:
        print(f"Error saving diet: {e}")
        import traceback
        traceback.print_exc()

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def home():
    if not STORAGE_AVAILABLE:
        return render_template("index.html", 
            error="Vercel Blob Storage not configured. Please set up BLOB_READ_WRITE_TOKEN environment variable.",
            prof={}, age_weeks=0, stage="", latest_w=None, daily_kcal=None,
            weights_list=[], per_meal=[], foods=[], diet_map={}, total_pct=0.0, trend=[])
    
    # Handle actions
    action = request.form.get("action")

    if action == "save_profile":
        prof = get_profile()
        prof["name"] = request.form.get("name") or None
        prof["anchor_date"] = request.form.get("anchor_date") or date.today().isoformat()
        prof["anchor_age_weeks"] = float(request.form.get("anchor_age_weeks") or 8.0)
        prof["meals_per_day"] = int(request.form.get("meals_per_day") or 3)
        prof["life_stage_override"] = request.form.get("life_stage_override") or None
        save_profile(prof)
        return redirect(url_for("home"))

    if action == "add_weight":
        wdt = request.form.get("weight_dt") or date.today().isoformat()
        wkg = float(request.form.get("weight_kg"))
        save_weight(wdt, wkg)
        return redirect(url_for("home"))

    if action == "add_food":
        name = request.form.get("food_name").strip()
        unit = request.form.get("food_unit")
        kpu = float(request.form.get("kcal_per_unit"))
        gpc_raw = request.form.get("grams_per_cup")
        gpc = float(gpc_raw) if gpc_raw else None
        food_data = {
            "name": name,
            "unit": unit,
            "kcal_per_unit": kpu,
            "grams_per_cup": gpc
        }
        save_food(food_data)
        return redirect(url_for("home"))

    if action == "delete_food":
        fid = int(request.form.get("del_food_id"))
        delete_food(fid)
        return redirect(url_for("home"))

    if action == "save_diet":
        foods = get_foods()
        total = 0.0
        diet_list = []
        for food in foods:
            fid = food["id"]
            pct = float(request.form.get(f"diet_pct_{fid}", "0") or "0")
            total += pct
            if pct > 0:
                diet_list.append({
                    "food_id": fid,
                    "pct_daily_kcal": pct
                })
        if round(total, 1) != 100.0:
            # fall through and show error on page
            pass
        else:
            save_diet(diet_list)
            return redirect(url_for("home"))

    # Data for render
    prof = get_profile()
    weights_list = get_weights()
    foods_list = get_foods()
    diet_list = get_diet()

    # Convert to DataFrames for compatibility
    weights_df = pd.DataFrame(weights_list) if weights_list else pd.DataFrame(columns=["dt", "weight_kg"])
    foods_df = pd.DataFrame(foods_list) if foods_list else pd.DataFrame(columns=["id", "name", "unit", "kcal_per_unit", "grams_per_cup"])
    diet_df = pd.DataFrame(diet_list) if diet_list else pd.DataFrame(columns=["food_id", "pct_daily_kcal"])

    age_weeks = current_age_weeks(date.fromisoformat(prof["anchor_date"]), float(prof["anchor_age_weeks"]))
    stage = (prof.get("life_stage_override") or "") or infer_life_stage(age_weeks)

    latest_w = None
    if not weights_df.empty:
        latest_w = float(weights_df.iloc[-1]["weight_kg"])
    daily_kcal = der_kcal(latest_w, stage) if latest_w else None

    # charts data
    trend = []
    if not weights_df.empty:
        for _, r in weights_df.iterrows():
            dt = date.fromisoformat(r["dt"])
            age_w = float(prof["anchor_age_weeks"]) + weeks_between(date.fromisoformat(prof["anchor_date"]), dt)
            stg = prof.get("life_stage_override") or infer_life_stage(age_w)
            kcal = der_kcal(float(r["weight_kg"]), stg)
            trend.append({
                "dt": r["dt"],
                "weight_kg": float(r["weight_kg"]),
                "der_kcal": round(kcal, 1)
            })

    per_meal = pd.DataFrame()
    if daily_kcal and not diet_df.empty and not foods_df.empty:
        per_meal = kcal_split(daily_kcal, int(prof["meals_per_day"]), diet_list, foods_list)

    # for diet form display
    diet_map = {int(r["food_id"]): float(r["pct_daily_kcal"]) for _, r in diet_df.iterrows()} if not diet_df.empty else {}

    return render_template(
        "index.html",
        prof=prof,
        age_weeks=age_weeks,
        stage=stage,
        latest_w=latest_w,
        daily_kcal=daily_kcal,
        weights_list=weights_list,
        per_meal=per_meal.to_dict(orient="records"),
        foods=foods_list,
        diet_map=diet_map,
        total_pct=sum(diet_map.values()) if diet_map else 0.0,
        trend=trend
    )

# Health check
@app.route("/api/health")
def health():
    return {"ok": True, "storage_available": STORAGE_AVAILABLE}

# Simple test route
@app.route("/test")
def test():
    return "Flask is working!"

# Error handler for debugging - catch all exceptions
@app.errorhandler(Exception)
def handle_error(error):
    import traceback
    error_text = traceback.format_exc()
    return f"<h1>Error Details</h1><pre>{error_text}</pre>", 500

# Vercel requires variable "app"
# already defined: app = Flask(__name__)

