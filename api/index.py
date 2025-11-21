import math
import os
from datetime import date, datetime
from typing import Optional, Tuple, List

import pandas as pd
import requests
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

# ---------- Vercel Blob Data helpers - Multiple Cats Support ----------
def get_all_cats():
    """Get list of all cats"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = storage_manager.read_json("cats")
        cats = data.get("cats", [])
        # Sort by created_at descending (newest first)
        return sorted(cats, key=lambda x: x.get("created_at", ""), reverse=True)
    except Exception as e:
        print(f"Error reading cats list: {e}")
        return []

def get_cat(cat_id: int):
    """Get full cat data including profile and weights"""
    if not STORAGE_AVAILABLE:
        return None
    try:
        data = storage_manager.read_json(f"cat_{cat_id}_data")
        return data
    except Exception as e:
        print(f"Error reading cat {cat_id}: {e}")
        return None

def save_cat(cat_data: dict):
    """Save or update a cat"""
    if not STORAGE_AVAILABLE:
        return None
    try:
        # Get all cats
        all_cats_data = storage_manager.read_json("cats")
        cats = all_cats_data.get("cats", [])
        
        cat_id = cat_data.get("id")
        existing_data = None
        if cat_id:
            # Get existing data to preserve weights and diet
            existing_data = get_cat(cat_id)
        
        if not cat_id:
            # New cat - generate ID
            max_id = max([c.get("id", 0) for c in cats], default=0)
            cat_id = max_id + 1
            cat_data["id"] = cat_id
            cat_data["created_at"] = datetime.now().isoformat()
            # Add to cats list
            cats.append({
                "id": cat_id,
                "name": cat_data.get("name", "Unnamed Cat"),
                "birthday": cat_data.get("birthday"),
                "profile_pic_url": cat_data.get("profile_pic_url"),
                "created_at": cat_data["created_at"]
            })
        else:
            # Update existing cat in list
            for i, c in enumerate(cats):
                if c.get("id") == cat_id:
                    # Update basic info
                    cats[i].update({
                        "name": cat_data.get("name", "Unnamed Cat"),
                        "birthday": cat_data.get("birthday"),
                        "profile_pic_url": cat_data.get("profile_pic_url", cats[i].get("profile_pic_url")),
                        "updated_at": datetime.now().isoformat()
                    })
                    break
        
        # Save cats list
        all_cats_data["cats"] = cats
        storage_manager.write_json(all_cats_data, "cats")
        
        # Save full cat data - preserve existing weights and diet if updating
        full_data = {
            "id": cat_id,
            "name": cat_data.get("name", "Unnamed Cat"),
            "birthday": cat_data.get("birthday"),
            "profile_pic_url": cat_data.get("profile_pic_url") or (existing_data.get("profile_pic_url") if existing_data else None),
            "anchor_date": cat_data.get("anchor_date") or (existing_data.get("anchor_date") if existing_data else date.today().isoformat()),
            "anchor_age_weeks": cat_data.get("anchor_age_weeks") if "anchor_age_weeks" in cat_data else (existing_data.get("anchor_age_weeks") if existing_data else 8.0),
            "meals_per_day": cat_data.get("meals_per_day") if "meals_per_day" in cat_data else (existing_data.get("meals_per_day") if existing_data else 3),
            "life_stage_override": cat_data.get("life_stage_override") if "life_stage_override" in cat_data else (existing_data.get("life_stage_override") if existing_data else None),
            "weights": cat_data.get("weights") if "weights" in cat_data else (existing_data.get("weights", []) if existing_data else []),
            "diet": cat_data.get("diet") if "diet" in cat_data else (existing_data.get("diet", []) if existing_data else [])
        }
        storage_manager.write_json(full_data, f"cat_{cat_id}_data")
        
        return cat_id
    except Exception as e:
        print(f"Error saving cat: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_weights(cat_id: int):
    """Get weight logs for a specific cat"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = get_cat(cat_id)
        if not data:
            return []
        weights = data.get("weights", [])
        return sorted(weights, key=lambda x: x.get("dt", ""))
    except Exception as e:
        print(f"Error reading weights: {e}")
        return []

def save_weight(cat_id: int, weight_dt: str, weight_kg: float):
    """Save weight log for a specific cat"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = get_cat(cat_id)
        if not data:
            data = {}
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
        storage_manager.write_json(data, f"cat_{cat_id}_data")
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

def get_diet(cat_id: int):
    """Get diet plan for a specific cat"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = get_cat(cat_id)
        if not data:
            return []
        return data.get("diet", [])
    except Exception as e:
        print(f"Error reading diet: {e}")
        return []

def save_diet(cat_id: int, diet_list: List[dict]):
    """Save diet plan for a specific cat"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = get_cat(cat_id)
        if not data:
            data = {}
        data["diet"] = diet_list
        storage_manager.write_json(data, f"cat_{cat_id}_data")
    except Exception as e:
        print(f"Error saving diet: {e}")
        import traceback
        traceback.print_exc()

# Helper function to upload image to Vercel Blob
def upload_image_to_blob(file, filename: str) -> Optional[str]:
    """Upload image file to Vercel Blob and return URL"""
    if not STORAGE_AVAILABLE or not file:
        return None
    try:
        # Read file content
        file_content = file.read()
        # Determine content type
        content_type = file.content_type or "image/jpeg"
        if filename.lower().endswith('.png'):
            content_type = "image/png"
        elif filename.lower().endswith('.gif'):
            content_type = "image/gif"
        
        # Upload to Vercel Blob
        blob_key = f"cat_images/{filename}"
        token = storage_manager.token
        if not token:
            print("No blob token available")
            return None
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        }
        response = requests.put(
            f"{storage_manager.base_url}/{blob_key}",
            headers=headers,
            data=file_content,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            result = response.json()
            return result.get("url")
        else:
            print(f"Error uploading image: HTTP {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"Error uploading image: {e}")
        import traceback
        traceback.print_exc()
        return None

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def home():
    if not STORAGE_AVAILABLE:
        return render_template("index.html", 
            error="Vercel Blob Storage not configured. Please set up BLOB_READ_WRITE_TOKEN environment variable.",
            cats=[], selected_cat=None, age_weeks=0, stage="", latest_w=None, daily_kcal=None,
            weights_list=[], per_meal=[], foods=[], diet_map={}, total_pct=0.0, trend=[])
    
    # Get all cats
    all_cats = get_all_cats()
    
    # Get selected cat ID from query param or form, default to latest
    cat_id = None
    if request.args.get("cat_id"):
        cat_id = int(request.args.get("cat_id"))
    elif request.form.get("cat_id"):
        cat_id = int(request.form.get("cat_id"))
    elif all_cats:
        cat_id = all_cats[0].get("id")  # Latest cat
    
    # Handle actions
    action = request.form.get("action")

    if action == "create_cat":
        # Create new cat
        name = request.form.get("cat_name", "").strip() or "Unnamed Cat"
        birthday = request.form.get("birthday") or date.today().isoformat()
        anchor_date = request.form.get("anchor_date") or birthday
        anchor_age_weeks = float(request.form.get("anchor_age_weeks") or 0.0)
        meals_per_day = int(request.form.get("meals_per_day") or 3)
        life_stage_override = request.form.get("life_stage_override") or None
        
        # Handle profile picture upload
        profile_pic_url = None
        if "profile_pic" in request.files:
            file = request.files["profile_pic"]
            if file.filename:
                filename = f"{int(datetime.now().timestamp())}_{file.filename}"
                profile_pic_url = upload_image_to_blob(file, filename)
        
        cat_data = {
            "name": name,
            "birthday": birthday,
            "profile_pic_url": profile_pic_url,
            "anchor_date": anchor_date,
            "anchor_age_weeks": anchor_age_weeks,
            "meals_per_day": meals_per_day,
            "life_stage_override": life_stage_override,
            "weights": [],
            "diet": []
        }
        new_cat_id = save_cat(cat_data)
        if new_cat_id:
            return redirect(url_for("home", cat_id=new_cat_id))
        return redirect(url_for("home"))

    if action == "update_profile" and cat_id:
        # Update cat profile
        cat_data = get_cat(cat_id)
        if cat_data:
            cat_data["name"] = request.form.get("cat_name", "").strip() or "Unnamed Cat"
            cat_data["birthday"] = request.form.get("birthday") or date.today().isoformat()
            cat_data["anchor_date"] = request.form.get("anchor_date") or cat_data["birthday"]
            cat_data["anchor_age_weeks"] = float(request.form.get("anchor_age_weeks") or 0.0)
            cat_data["meals_per_day"] = int(request.form.get("meals_per_day") or 3)
            cat_data["life_stage_override"] = request.form.get("life_stage_override") or None
            
            # Handle profile picture upload
            if "profile_pic" in request.files:
                file = request.files["profile_pic"]
                if file.filename:
                    filename = f"{int(datetime.now().timestamp())}_{file.filename}"
                    profile_pic_url = upload_image_to_blob(file, filename)
                    if profile_pic_url:
                        cat_data["profile_pic_url"] = profile_pic_url
            
            save_cat(cat_data)
        return redirect(url_for("home", cat_id=cat_id))

    if action == "add_weight" and cat_id:
        wdt = request.form.get("weight_dt") or date.today().isoformat()
        wkg = float(request.form.get("weight_kg"))
        save_weight(cat_id, wdt, wkg)
        return redirect(url_for("home", cat_id=cat_id))

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
        return redirect(url_for("home", cat_id=cat_id) if cat_id else url_for("home"))

    if action == "delete_food":
        fid = int(request.form.get("del_food_id"))
        delete_food(fid)
        return redirect(url_for("home", cat_id=cat_id) if cat_id else url_for("home"))

    if action == "save_diet" and cat_id:
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
        if round(total, 1) == 100.0:
            save_diet(cat_id, diet_list)
        return redirect(url_for("home", cat_id=cat_id))

    # Get selected cat data or use default
    selected_cat = None
    if cat_id:
        selected_cat = get_cat(cat_id)
    
    # If no cat selected or found, create dummy data
    if not selected_cat:
        selected_cat = {
            "id": None,
            "name": "Unnamed Cat",
            "birthday": date.today().isoformat(),
            "profile_pic_url": None,
            "anchor_date": date.today().isoformat(),
            "anchor_age_weeks": 8.0,
            "meals_per_day": 3,
            "life_stage_override": None,
            "weights": [],
            "diet": []
        }
        cat_id = None

    # Get data for selected cat
    weights_list = get_weights(cat_id) if cat_id else []
    foods_list = get_foods()
    diet_list = get_diet(cat_id) if cat_id else []

    # Convert to DataFrames for compatibility
    weights_df = pd.DataFrame(weights_list) if weights_list else pd.DataFrame(columns=["dt", "weight_kg"])
    foods_df = pd.DataFrame(foods_list) if foods_list else pd.DataFrame(columns=["id", "name", "unit", "kcal_per_unit", "grams_per_cup"])
    diet_df = pd.DataFrame(diet_list) if diet_list else pd.DataFrame(columns=["food_id", "pct_daily_kcal"])

    # Calculate age and stage
    # If birthday is available, calculate age from birthday
    birthday = selected_cat.get("birthday")
    anchor_date = date.fromisoformat(selected_cat.get("anchor_date", date.today().isoformat()))
    anchor_age_weeks = float(selected_cat.get("anchor_age_weeks", 8.0))
    
    if birthday:
        try:
            birthday_date = date.fromisoformat(birthday)
            age_weeks = weeks_between(birthday_date, date.today())
        except:
            # Fallback to anchor date method
            age_weeks = current_age_weeks(anchor_date, anchor_age_weeks)
    else:
        # Use anchor date method
        age_weeks = current_age_weeks(anchor_date, anchor_age_weeks)
    
    stage = (selected_cat.get("life_stage_override") or "") or infer_life_stage(age_weeks)

    latest_w = None
    if not weights_df.empty:
        latest_w = float(weights_df.iloc[-1]["weight_kg"])
    daily_kcal = der_kcal(latest_w, stage) if latest_w else None

    # charts data
    trend = []
    if not weights_df.empty:
        # Determine age calculation method
        use_birthday = bool(birthday)
        birthday_date_obj = None
        if use_birthday:
            try:
                birthday_date_obj = date.fromisoformat(birthday)
            except:
                use_birthday = False
        
        for _, r in weights_df.iterrows():
            dt = date.fromisoformat(r["dt"])
            if use_birthday and birthday_date_obj:
                age_w = weeks_between(birthday_date_obj, dt)
            else:
                age_w = anchor_age_weeks + weeks_between(anchor_date, dt)
            stg = selected_cat.get("life_stage_override") or infer_life_stage(age_w)
            kcal = der_kcal(float(r["weight_kg"]), stg)
            trend.append({
                "dt": r["dt"],
                "weight_kg": float(r["weight_kg"]),
                "der_kcal": round(kcal, 1)
            })

    per_meal = pd.DataFrame()
    if daily_kcal and not diet_df.empty and not foods_df.empty:
        per_meal = kcal_split(daily_kcal, int(selected_cat.get("meals_per_day", 3)), diet_list, foods_list)

    # for diet form display
    diet_map = {int(r["food_id"]): float(r["pct_daily_kcal"]) for _, r in diet_df.iterrows()} if not diet_df.empty else {}

    return render_template(
        "index.html",
        cats=all_cats,
        selected_cat=selected_cat,
        cat_id=cat_id,
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

