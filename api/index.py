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

def format_age_display(age_weeks: float) -> str:
    if age_weeks is None or age_weeks < 0:
        return "—"
    weeks = int(round(age_weeks))
    if weeks < 12:
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    if weeks < 52:
        months = weeks // 4
        rem_weeks = weeks % 4
        parts = []
        if months:
            parts.append(f"{months} month{'s' if months != 1 else ''}")
        if rem_weeks:
            parts.append(f"{rem_weeks} week{'s' if rem_weeks != 1 else ''}")
        return " ".join(parts) if parts else "0 months"
    years = weeks // 52
    rem_weeks = weeks % 52
    months = rem_weeks // 4
    parts = [f"{years} year{'s' if years != 1 else ''}"]
    if months:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    return " ".join(parts)

def format_life_stage(stage: str) -> str:
    """Format life stage string to be human-readable"""
    if not stage:
        return "Unknown"
    
    stage_lower = stage.lower()
    
    # Map stage codes to human-readable format
    stage_map = {
        "kitten_0_4m": "Kitten 0–4 months",
        "kitten_4_12m": "Kitten 4–12 months",
        "adult_neutered": "Adult (Neutered)",
        "adult_intact": "Adult (Intact)",
        "adult_obese_prone": "Adult (Obese-Prone)"
    }
    
    return stage_map.get(stage_lower, stage.replace("_", " ").title())

def estimate_weight_by_age(age_weeks: float) -> float:
    """Estimate typical weight in kg based on age in weeks for generic kcal calculation"""
    if age_weeks < 0:
        return 0.1  # Newborn
    
    # Typical kitten growth pattern
    if age_weeks < 4:
        # 0-4 weeks: 0.1-0.3 kg
        return 0.1 + (age_weeks / 4) * 0.2
    elif age_weeks < 8:
        # 4-8 weeks: 0.3-0.6 kg
        return 0.3 + ((age_weeks - 4) / 4) * 0.3
    elif age_weeks < 12:
        # 8-12 weeks: 0.6-1.0 kg
        return 0.6 + ((age_weeks - 8) / 4) * 0.4
    elif age_weeks < 16:
        # 12-16 weeks: 1.0-1.5 kg
        return 1.0 + ((age_weeks - 12) / 4) * 0.5
    elif age_weeks < 26:
        # 4-6 months: 1.5-2.5 kg
        return 1.5 + ((age_weeks - 16) / 10) * 1.0
    elif age_weeks < 52:
        # 6-12 months: 2.5-4.0 kg
        return 2.5 + ((age_weeks - 26) / 26) * 1.5
    else:
        # Adult: 3.5-5.5 kg (use average of 4.5 kg)
        return 4.5

def calories_per_kg(food: dict) -> Optional[float]:
    """Return kcal per 1000 g for a food entry, converting legacy fields if needed."""
    if not food:
        return None
    if food.get("kcal_per_kg"):
        try:
            return float(food["kcal_per_kg"])
        except (ValueError, TypeError):
            return None
    # Legacy fields
    unit = food.get("unit")
    kpu = food.get("kcal_per_unit")
    if not kpu:
        return None
    try:
        kpu = float(kpu)
    except (ValueError, TypeError):
        return None
    if unit == "kcal_per_g":
        return kpu * 1000.0
    if unit == "kcal_per_cup":
        gpc = food.get("grams_per_cup")
        if gpc:
            try:
                return (kpu / float(gpc)) * 1000.0
            except (ValueError, TypeError):
                return None
    return None


def kcal_split(total_kcal: float, meals_per_day: int, diet_list: List[dict], foods_list: List[dict]) -> pd.DataFrame:
    if total_kcal <= 0 or meals_per_day <= 0 or not diet_list or not foods_list:
        return pd.DataFrame(columns=["Food","pct","kcal_day","kcal_meal","grams_per_meal"])
    
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
        kcal_per_kg = calories_per_kg(food)
        if not kcal_per_kg or kcal_per_kg <= 0:
            continue
        # grams per meal = kcal_meal * 1000 / kcal_per_kg
        grams_pm = (kcal_meal * 1000.0) / kcal_per_kg
        out.append({
            "Food": food["name"],
            "pct": pct,
            "kcal_day": round(kcal_day, 1),
            "kcal_meal": round(kcal_meal, 1),
            "grams_per_meal": round(grams_pm, 1),
        })
    return pd.DataFrame(out)

# ---------- Vercel Blob Data helpers - Multiple Cats Support ----------
# Storage structure (organized in data/ directory):
# - data/cats.json: {cats: [{id, name, birthday, profile_pic_url, created_at}]}
# - data/cat_{id}.json: {id, name, birthday, profile_pic_url, meals_per_day, life_stage_override, weights: [], diet: [], meals: []}
# - data/foods.json: {foods: [{id, name, unit, kcal_per_unit, grams_per_cup}]}
# - cat_images/: profile pictures

def get_all_cats():
    """Get list of all cats"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = storage_manager.read_json("data/cats")
        if not data:
            return []
        cats = data.get("cats", [])
        # Sort by created_at descending (newest first)
        return sorted(cats, key=lambda x: x.get("created_at", ""), reverse=True)
    except Exception as e:
        print(f"Error reading cats list: {e}")
        return []

def get_cat(cat_id: int):
    """Get full cat data including profile, weights, diet, and meals"""
    if not STORAGE_AVAILABLE or not cat_id:
        return None
    try:
        data = storage_manager.read_json(f"data/cat_{cat_id}")
        if not data:
            return None
        return data
    except Exception as e:
        print(f"Error reading cat {cat_id}: {e}")
        import traceback
        traceback.print_exc()
        return None

def save_cat(cat_data: dict):
    """Save or update a cat - clear structure"""
    if not STORAGE_AVAILABLE:
        return None
    try:
        # Get all cats
        all_cats_data = storage_manager.read_json("data/cats")
        if not all_cats_data:
            all_cats_data = {"cats": []}
        cats = all_cats_data.get("cats", [])
        
        cat_id = cat_data.get("id")
        existing_data = None
        if cat_id:
            # Get existing data to preserve weights, diet, and meals
            existing_data = get_cat(cat_id)
        
        if not cat_id:
            # New cat - generate ID
            max_id = max([c.get("id", 0) for c in cats], default=0)
            cat_id = max_id + 1
            cat_data["id"] = cat_id
            created_at = datetime.now().isoformat()
            # Add to cats list
            cats.append({
                "id": cat_id,
                "name": cat_data.get("name", "Unnamed Cat"),
                "birthday": cat_data.get("birthday"),
                "profile_pic_url": cat_data.get("profile_pic_url"),
                "created_at": created_at
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
        storage_manager.write_json(all_cats_data, "data/cats")
        
        # Save full cat data - preserve existing weights, diet, and meals if updating
        full_data = {
            "id": cat_id,
            "name": cat_data.get("name", "Unnamed Cat"),
            "birthday": cat_data.get("birthday"),
            "profile_pic_url": cat_data.get("profile_pic_url") or (existing_data.get("profile_pic_url") if existing_data else None),
            "meals_per_day": cat_data.get("meals_per_day") if "meals_per_day" in cat_data else (existing_data.get("meals_per_day") if existing_data else 3),
            "life_stage_override": cat_data.get("life_stage_override") if "life_stage_override" in cat_data else (existing_data.get("life_stage_override") if existing_data else None),
            "weights": existing_data.get("weights", []) if existing_data else [],
            "diet": existing_data.get("diet", []) if existing_data else [],
            "meals": existing_data.get("meals", []) if existing_data else []
        }
        storage_manager.write_json(full_data, f"data/cat_{cat_id}")
        
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

def save_weight(cat_id: int, weight_dt: str, weight_kg: float) -> bool:
    """Save weight log for a specific cat. Returns True if successful, False otherwise."""
    if not STORAGE_AVAILABLE:
        print("Error: Storage not available")
        return False
    if not cat_id:
        print("Error: cat_id is required")
        return False
    try:
        print(f"Attempting to save weight for cat {cat_id}: {weight_kg} kg on {weight_dt}")
        data = get_cat(cat_id)
        if not data:
            print(f"Cat {cat_id} not found, cannot save weight")
            return False
        weights = data.get("weights", [])
        print(f"Current weights count: {len(weights)}")
        
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
        print(f"Saving {len(weights)} weight entries for cat {cat_id}")
        
        # Write and verify success
        success = storage_manager.write_json(data, f"data/cat_{cat_id}")
        if success:
            # Verify the write by reading it back
            verify_data = get_cat(cat_id)
            if verify_data and len(verify_data.get("weights", [])) == len(weights):
                print(f"Successfully saved and verified weight for cat {cat_id}")
                return True
            else:
                print(f"Warning: Weight save may have failed - verification read returned {len(verify_data.get('weights', [])) if verify_data else 0} weights, expected {len(weights)}")
                return False
        else:
            print(f"Error: Failed to save weight for cat {cat_id}")
            return False
    except Exception as e:
        print(f"Error saving weight: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_foods():
    """Get foods from Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return []
    try:
        data = storage_manager.read_json("data/foods")
        if not data:
            return []
        foods = data.get("foods", [])
        # ensure kcal_per_kg present
        for food in foods:
            if "kcal_per_kg" not in food or not food.get("kcal_per_kg"):
                converted = calories_per_kg(food)
                if converted:
                    food["kcal_per_kg"] = round(converted, 1)
        return sorted(foods, key=lambda x: x.get("name", ""))
    except Exception as e:
        print(f"Error reading foods: {e}")
        return []

def save_food(food_data: dict):
    """Save food to Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = storage_manager.read_json("data/foods")
        if not data:
            data = {"foods": []}
        foods = data.get("foods", [])
        
        # Generate ID if not present
        if "id" not in food_data or not food_data["id"]:
            max_id = max([f.get("id", 0) for f in foods], default=0)
            food_data["id"] = max_id + 1
        
        foods.append(food_data)
        data["foods"] = foods
        storage_manager.write_json(data, "data/foods")
    except Exception as e:
        print(f"Error saving food: {e}")
        import traceback
        traceback.print_exc()

def delete_food(food_id: int):
    """Delete food from Vercel Blob Storage"""
    if not STORAGE_AVAILABLE:
        return
    try:
        data = storage_manager.read_json("data/foods")
        if not data:
            return
        foods = data.get("foods", [])
        foods = [f for f in foods if f.get("id") != food_id]
        data["foods"] = foods
        storage_manager.write_json(data, "data/foods")
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
    if not STORAGE_AVAILABLE or not cat_id:
        return
    try:
        data = get_cat(cat_id)
        if not data:
            print(f"Cat {cat_id} not found, cannot save diet")
            return
        data["diet"] = diet_list
        storage_manager.write_json(data, f"data/cat_{cat_id}")
    except Exception as e:
        print(f"Error saving diet: {e}")
        import traceback
        traceback.print_exc()

def add_meal(cat_id: int, meal_date: str, meal_time: str, food_id: int, quantity: float):
    """Add a meal record for a specific cat"""
    if not STORAGE_AVAILABLE or not cat_id:
        return
    try:
        data = get_cat(cat_id)
        if not data:
            print(f"Cat {cat_id} not found, cannot add meal")
            return
        meals = data.get("meals", [])
        meals.append({
            "date": meal_date,
            "time": meal_time,
            "food_id": food_id,
            "quantity": quantity,
            "created_at": datetime.now().isoformat()
        })
        # Sort by date and time
        meals = sorted(meals, key=lambda x: (x.get("date", ""), x.get("time", "")))
        data["meals"] = meals
        storage_manager.write_json(data, f"data/cat_{cat_id}")
    except Exception as e:
        print(f"Error adding meal: {e}")
        import traceback
        traceback.print_exc()

def get_meals(cat_id: int):
    """Get meal records for a specific cat"""
    if not STORAGE_AVAILABLE or not cat_id:
        return []
    try:
        data = get_cat(cat_id)
        if not data:
            return []
        return data.get("meals", [])
    except Exception as e:
        print(f"Error reading meals: {e}")
        return []

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
@app.route("/favicon.ico")
def favicon():
    return "", 204  # No content

@app.route("/", methods=["GET", "POST"])
def home():
    # Get tab parameter from URL
    current_tab = request.args.get("tab", "dash")
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
            "meals_per_day": meals_per_day,
            "life_stage_override": life_stage_override
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
    
    if action == "purge_all_data":
        # Purge all data (admin function)
        deleted_count = storage_manager.purge_all_data()
        return redirect(url_for("home"))

    if action == "add_weight":
        if not cat_id:
            print(f"Error: add_weight action requires cat_id. Form data: {dict(request.form)}")
            return redirect(url_for("home"))
        try:
            wdt = request.form.get("weight_dt") or date.today().isoformat()
            wkg_str = request.form.get("weight_kg")
            print(f"add_weight: cat_id={cat_id}, weight_dt={wdt}, weight_kg={wkg_str}")
            if not wkg_str:
                print("Error: weight_kg is required")
                return redirect(url_for("home", cat_id=cat_id, tab="log"))
            wkg = float(wkg_str)
            if wkg <= 0:
                print("Error: weight must be positive")
                return redirect(url_for("home", cat_id=cat_id, tab="log"))
            print(f"Calling save_weight with cat_id={cat_id}, wdt={wdt}, wkg={wkg}")
            success = save_weight(cat_id, wdt, wkg)
            if not success:
                print(f"Warning: Weight save may have failed for cat {cat_id}")
                # Still redirect but log the warning - user can check logs
            tab = request.form.get("current_tab", "log")
            print(f"Redirecting to home with cat_id={cat_id}, tab={tab}")
            return redirect(url_for("home", cat_id=cat_id, tab=tab))
        except ValueError as e:
            print(f"Error parsing weight: {e}")
            import traceback
            traceback.print_exc()
            return redirect(url_for("home", cat_id=cat_id, tab="log"))
        except Exception as e:
            print(f"Error in add_weight: {e}")
            import traceback
            traceback.print_exc()
            return redirect(url_for("home", cat_id=cat_id, tab="log"))

    if action == "add_food":
        name = (request.form.get("food_name") or "").strip()
        tab = request.form.get("current_tab", "foods")
        if not name:
            return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))
        kcal_per_kg = float(request.form.get("kcal_per_kg"))
        if kcal_per_kg <= 0:
            return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))
        food_data = {
            "name": name,
            "kcal_per_kg": round(kcal_per_kg, 1)
        }
        save_food(food_data)
        return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))

    if action == "delete_food":
        fid = int(request.form.get("del_food_id"))
        delete_food(fid)
        tab = request.form.get("current_tab", "foods")
        return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))

    if action == "save_diet" and cat_id:
        foods = get_foods()
        total = 0
        diet_list = []
        for food in foods:
            fid = food["id"]
            pct_str = request.form.get(f"diet_pct_{fid}", "0") or "0"
            pct = int(float(pct_str))  # Convert to integer
            total += pct
            if pct > 0:
                diet_list.append({
                    "food_id": fid,
                    "pct_daily_kcal": float(pct)  # Store as float for consistency but value is integer
                })
        if total == 100:
            save_diet(cat_id, diet_list)
        tab = request.form.get("current_tab", "diet")
        return redirect(url_for("home", cat_id=cat_id, tab=tab))

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
            "meals_per_day": 3,
            "life_stage_override": None,
            "weights": [],
            "diet": [],
            "meals": []
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

    # Calculate age and stage - only from birthday
    birthday = selected_cat.get("birthday")
    age_weeks = 0.0
    if birthday:
        try:
            birthday_date = date.fromisoformat(birthday)
            age_weeks = weeks_between(birthday_date, date.today())
        except Exception as e:
            print(f"Error parsing birthday {birthday}: {e}")
            age_weeks = 0.0
    
    stage = (selected_cat.get("life_stage_override") or "") or infer_life_stage(age_weeks)
    age_display = format_age_display(age_weeks)
    stage_display = format_life_stage(stage)

    latest_w = None
    if not weights_df.empty:
        latest_w = float(weights_df.iloc[-1]["weight_kg"])
    
    # Calculate daily kcal - use actual weight if available, otherwise estimate based on age
    if latest_w:
        daily_kcal = der_kcal(latest_w, stage)
    elif age_weeks > 0:
        # Estimate weight based on age for generic kcal calculation
        estimated_weight = estimate_weight_by_age(age_weeks)
        daily_kcal = der_kcal(estimated_weight, stage)
    else:
        daily_kcal = None

    # charts data - calculate age from birthday only
    trend = []
    if not weights_df.empty and birthday:
        try:
            birthday_date_obj = date.fromisoformat(birthday)
            for _, r in weights_df.iterrows():
                dt = date.fromisoformat(r["dt"])
                age_w = weeks_between(birthday_date_obj, dt)
                stg = selected_cat.get("life_stage_override") or infer_life_stage(age_w)
                kcal = der_kcal(float(r["weight_kg"]), stg)
                trend.append({
                    "dt": r["dt"],
                    "weight_kg": float(r["weight_kg"]),
                    "der_kcal": round(kcal, 1)
                })
        except Exception as e:
            print(f"Error calculating trend: {e}")

    per_meal = pd.DataFrame()
    if daily_kcal and not diet_df.empty and not foods_df.empty:
        per_meal = kcal_split(daily_kcal, int(selected_cat.get("meals_per_day", 3)), diet_list, foods_list)

    # for diet form display - convert to integers for display
    diet_map = {int(r["food_id"]): int(round(float(r["pct_daily_kcal"]))) for _, r in diet_df.iterrows()} if not diet_df.empty else {}

    return render_template(
        "index.html",
        cats=all_cats,
        selected_cat=selected_cat,
        cat_id=cat_id,
        age_weeks=age_weeks,
        age_display=age_display,
        stage=stage,
        stage_display=stage_display,
        latest_w=latest_w,
        daily_kcal=daily_kcal,
        weights_list=weights_list,
        per_meal=per_meal.to_dict(orient="records"),
        foods=foods_list,
        diet_map=diet_map,
        total_pct=int(round(sum(diet_map.values()))) if diet_map else 0,
        trend=trend,
        current_tab=current_tab
    )

# Health check
@app.route("/api/health")
def health():
    return {"ok": True, "storage_available": STORAGE_AVAILABLE}

# Purge all data route (use with caution!)
@app.route("/api/purge", methods=["POST"])
def purge_data():
    """Purge all application data from blob storage"""
    if not STORAGE_AVAILABLE:
        return {"ok": False, "error": "Storage not available"}, 500
    try:
        deleted_count = storage_manager.purge_all_data()
        return {"ok": True, "deleted_count": deleted_count, "message": f"Purged {deleted_count} data blobs"}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

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

