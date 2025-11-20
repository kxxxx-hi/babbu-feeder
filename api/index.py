import math
import os
import uuid
from datetime import date, datetime
from typing import Optional, Tuple, List

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import GCS storage manager
try:
    from .storage import CloudStorageManager
    storage_manager = CloudStorageManager()
    GCS_AVAILABLE = True
except Exception as e:
    print(f"Warning: Google Cloud Storage not available: {e}")
    GCS_AVAILABLE = False
    storage_manager = None

# Fix template path for Vercel - templates are in parent directory
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
app = Flask(__name__, template_folder=template_dir)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

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

# ---------- GCS Data helpers (Multi-cat support) ----------
def get_all_cats():
    """Get all cat profiles from GCS"""
    if not GCS_AVAILABLE:
        return []
    data = storage_manager.read_json("cat_profile")
    cats = data.get("cats", [])
    # Ensure created_at exists for ordering
    for cat in cats:
        if not cat.get("created_at"):
            cat["created_at"] = datetime.utcnow().isoformat()
    # Sort alphabetically for readability
    return sorted(cats, key=lambda x: (x.get("name") or "").lower())

def get_cat_profile(cat_id: str):
    """Get a specific cat profile by ID"""
    if not GCS_AVAILABLE:
        return None
    cats = get_all_cats()
    for cat in cats:
        if cat.get("id") == cat_id:
            return cat
    return None

def save_cat_profile(cat_data: dict):
    """Save or update a cat profile"""
    if not GCS_AVAILABLE:
        return
    data = storage_manager.read_json("cat_profile")
    cats = data.get("cats", [])
    
    # Generate ID if new cat
    if "id" not in cat_data or not cat_data["id"]:
        cat_data["id"] = str(uuid.uuid4())
    
    # Update or add
    cat_id = cat_data["id"]
    existing_index = next((i for i, c in enumerate(cats) if c.get("id") == cat_id), None)
    # Preserve created_at for existing cat or set default
    created_at = None
    if existing_index is not None:
        existing_cat = cats[existing_index]
        created_at = existing_cat.get("created_at")
    if not created_at:
        created_at = cat_data.get("created_at") or datetime.utcnow().isoformat()
    cat_data["created_at"] = created_at
    cat_data["updated_at"] = datetime.utcnow().isoformat()

    if existing_index is not None:
        cats[existing_index] = cat_data
    else:
        cats.append(cat_data)
    
    data["cats"] = cats
    storage_manager.write_json(data, "cat_profile")
    return cat_data["id"]

def get_weights(cat_id: str):
    """Get weight logs for a specific cat"""
    if not GCS_AVAILABLE:
        return []
    data = storage_manager.read_json("logs")
    weights_by_cat = data.get("weights_by_cat", {})
    weights = weights_by_cat.get(cat_id, [])
    return sorted(weights, key=lambda x: x.get("dt", ""))

def save_weight(cat_id: str, weight_dt: str, weight_kg: float):
    """Save weight log for a specific cat"""
    if not GCS_AVAILABLE:
        return
    data = storage_manager.read_json("logs")
    weights_by_cat = data.get("weights_by_cat", {})
    weights = weights_by_cat.get(cat_id, [])
    
    # Remove existing entry for this date if exists
    weights = [w for w in weights if w.get("dt") != weight_dt]
    
    # Add new entry
    weights.append({
        "dt": weight_dt,
        "weight_kg": weight_kg
    })
    
    # Sort by date
    weights = sorted(weights, key=lambda x: x.get("dt", ""))
    weights_by_cat[cat_id] = weights
    data["weights_by_cat"] = weights_by_cat
    storage_manager.write_json(data, "logs")

def get_foods():
    """Get foods from GCS (shared across all cats)"""
    if not GCS_AVAILABLE:
        return []
    data = storage_manager.read_json("foods")
    foods = data.get("foods", [])
    return sorted(foods, key=lambda x: x.get("name", ""))

def save_food(food_data: dict):
    """Save food to GCS"""
    if not GCS_AVAILABLE:
        return
    data = storage_manager.read_json("foods")
    foods = data.get("foods", [])
    
    # Generate ID if not present
    if "id" not in food_data or not food_data["id"]:
        max_id = max([f.get("id", 0) for f in foods], default=0)
        food_data["id"] = max_id + 1
    
    foods.append(food_data)
    data["foods"] = foods
    storage_manager.write_json(data, "foods")

def delete_food(food_id: int):
    """Delete food from GCS"""
    if not GCS_AVAILABLE:
        return
    data = storage_manager.read_json("foods")
    foods = data.get("foods", [])
    foods = [f for f in foods if f.get("id") != food_id]
    data["foods"] = foods
    storage_manager.write_json(data, "foods")

def get_diet(cat_id: str):
    """Get diet plan for a specific cat"""
    if not GCS_AVAILABLE:
        return []
    data = storage_manager.read_json("cat_profile")
    diets_by_cat = data.get("diets_by_cat", {})
    return diets_by_cat.get(cat_id, [])

def save_diet(cat_id: str, diet_list: List[dict]):
    """Save diet plan for a specific cat"""
    if not GCS_AVAILABLE:
        return
    data = storage_manager.read_json("cat_profile")
    diets_by_cat = data.get("diets_by_cat", {})
    diets_by_cat[cat_id] = diet_list
    data["diets_by_cat"] = diets_by_cat
    storage_manager.write_json(data, "cat_profile")

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def home():
    if not GCS_AVAILABLE:
        return render_template("index.html", 
            error="Google Cloud Storage not configured. Please set up GCS_BUCKET_NAME and credentials.",
            cats=[], selected_cat_id=None, prof=None, age_weeks=0, stage="", latest_w=None, daily_kcal=None,
            weights_list=[], per_meal=[], foods=[], diet_map={}, total_pct=0.0, trend=[])
    
    # Get all cats for dropdown
    all_cats = get_all_cats()
    
    # Get selected cat ID from form, session, or latest cat
    selected_cat_id = request.form.get("selected_cat_id") or session.get("selected_cat_id")
    if not selected_cat_id and all_cats:
        latest_cat = max(all_cats, key=lambda c: c.get("created_at", ""))
        selected_cat_id = latest_cat.get("id")
    
    # Save selected cat to session
    if selected_cat_id:
        session["selected_cat_id"] = selected_cat_id
    
    # Handle actions
    action = request.form.get("action")

    if action == "select_cat":
        selected_cat_id = request.form.get("selected_cat_id")
        if selected_cat_id:
            session["selected_cat_id"] = selected_cat_id
        return redirect(url_for("home"))

    if action == "create_cat":
        new_cat_id = str(uuid.uuid4())
        name = request.form.get("new_cat_name") or "New Cat"
        anchor_date = request.form.get("new_cat_anchor_date") or date.today().isoformat()
        anchor_age_weeks = float(request.form.get("new_cat_anchor_age_weeks") or 8.0)
        meals_per_day = int(request.form.get("new_cat_meals_per_day") or 3)
        life_stage = request.form.get("new_cat_life_stage") or None

        new_cat = {
            "id": new_cat_id,
            "name": name,
            "anchor_date": anchor_date,
            "anchor_age_weeks": anchor_age_weeks,
            "meals_per_day": meals_per_day,
            "life_stage_override": life_stage,
            "created_at": datetime.utcnow().isoformat()
        }

        # Handle image upload
        if 'new_cat_profile_picture' in request.files:
            file = request.files['new_cat_profile_picture']
            if file and file.filename:
                ext = os.path.splitext(file.filename)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                    filename = f"{new_cat_id}{ext}"
                    image_data = file.read()
                    image_url = storage_manager.upload_image(image_data, filename, file.content_type)
                    new_cat["profile_picture"] = image_url
                    new_cat["profile_picture_filename"] = filename

        save_cat_profile(new_cat)
        session["selected_cat_id"] = new_cat_id
        return redirect(url_for("home") + "?saved=true")

    if action == "save_profile":
        # Get or create cat ID
        if not selected_cat_id:
            # Create new cat if none selected
            selected_cat_id = str(uuid.uuid4())
            session["selected_cat_id"] = selected_cat_id
        
        prof = get_cat_profile(selected_cat_id) or {}
        prof["id"] = selected_cat_id
        prof["name"] = request.form.get("name") or None
        prof["anchor_date"] = request.form.get("anchor_date") or date.today().isoformat()
        prof["anchor_age_weeks"] = float(request.form.get("anchor_age_weeks") or 8.0)
        prof["meals_per_day"] = int(request.form.get("meals_per_day") or 3)
        prof["life_stage_override"] = request.form.get("life_stage_override") or None
        
        # Handle image upload
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename:
                # Get file extension
                ext = os.path.splitext(file.filename)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                    filename = f"{selected_cat_id}{ext}"
                    image_data = file.read()
                    image_url = storage_manager.upload_image(image_data, filename, file.content_type)
                    prof["profile_picture"] = image_url
                    prof["profile_picture_filename"] = filename
        
        save_cat_profile(prof)
        # Redirect with success message and collapse profile
        return redirect(url_for("home") + "?saved=true")

    if action == "add_weight" and selected_cat_id:
        wdt = request.form.get("weight_dt") or date.today().isoformat()
        wkg = float(request.form.get("weight_kg"))
        save_weight(selected_cat_id, wdt, wkg)
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

    if action == "save_diet" and selected_cat_id:
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
            save_diet(selected_cat_id, diet_list)
            return redirect(url_for("home"))

    # Get selected cat profile
    prof = get_cat_profile(selected_cat_id) if selected_cat_id else None
    
    # If no profile, create default
    if not prof and selected_cat_id:
        prof = {
            "id": selected_cat_id,
            "name": None,
            "anchor_date": date.today().isoformat(),
            "anchor_age_weeks": 8.0,
            "meals_per_day": 3,
            "life_stage_override": None
        }
    elif not prof:
        prof = {
            "id": None,
            "name": None,
            "anchor_date": date.today().isoformat(),
            "anchor_age_weeks": 8.0,
            "meals_per_day": 3,
            "life_stage_override": None
        }
    
    # Get data for selected cat
    weights_list = get_weights(selected_cat_id) if selected_cat_id else []
    foods_list = get_foods()
    diet_list = get_diet(selected_cat_id) if selected_cat_id else []

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

    # Get query parameters for UI state
    show_success = request.args.get('saved') == 'true'
    profile_open = request.args.get('expand_profile') == 'true'
    if not profile_open:
        profile_open = not prof or not prof.get("name")
    if show_success:
        profile_open = False
    
    return render_template(
        "index.html",
        cats=all_cats,
        selected_cat_id=selected_cat_id,
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
        trend=trend,
        show_success=show_success,
        profile_open=profile_open
    )

# Health check
@app.route("/api/health")
def health():
    return {"ok": True, "gcs_available": GCS_AVAILABLE}

@app.route("/api/cats")
def list_cats_api():
    if not GCS_AVAILABLE:
        return {"cats": [], "error": "Google Cloud Storage not configured"}, 503
    return {"cats": get_all_cats()}

@app.route("/api/cats/raw")
def cats_raw():
    if not GCS_AVAILABLE:
        return {"profile": {}, "cats": [], "error": "Google Cloud Storage not configured"}, 503
    data = storage_manager.read_json("cat_profile")
    # Provide default keys for easier debugging
    data.setdefault("cats", [])
    data.setdefault("profile", {})
    return data

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
