import math
import os
from datetime import date, datetime
from typing import Optional, Tuple, List

import pandas as pd
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv

# Email sending
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False
    print("Warning: SendGrid not available. Email functionality disabled.")

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

def format_age_display(age_weeks: float, birthday_date: Optional[date] = None) -> str:
    """Format age display. If birthday_date is provided, calculates months based on calendar dates."""
    if age_weeks is None or age_weeks < 0:
        return "—"
    
    weeks = int(round(age_weeks))
    
    # If we have the birthday date, calculate months based on actual calendar dates
    if birthday_date and weeks >= 4:
        today = date.today()
        # Calculate months and days difference
        years_diff = today.year - birthday_date.year
        months_diff = today.month - birthday_date.month
        days_diff = today.day - birthday_date.day
        
        # Adjust for negative days
        if days_diff < 0:
            months_diff -= 1
            # Get days in previous month
            if today.month == 1:
                prev_month = 12
                prev_year = today.year - 1
            else:
                prev_month = today.month - 1
                prev_year = today.year
            days_in_prev_month = (date(prev_year, prev_month + 1, 1) - date(prev_year, prev_month, 1)).days
            days_diff = days_in_prev_month + days_diff
        
        # Adjust for negative months
        if months_diff < 0:
            years_diff -= 1
            months_diff = 12 + months_diff
        
        total_months = years_diff * 12 + months_diff
        rem_weeks = days_diff // 7
        
        if weeks < 12:
            # For very young kittens, show weeks only
            return f"{weeks} week{'s' if weeks != 1 else ''}"
        elif total_months < 12:
            # Show months and weeks
            parts = []
            if total_months:
                parts.append(f"{total_months} month{'s' if total_months != 1 else ''}")
            if rem_weeks:
                parts.append(f"{rem_weeks} week{'s' if rem_weeks != 1 else ''}")
            return " ".join(parts) if parts else "0 months"
        else:
            # Show years, months, and weeks
            years = total_months // 12
            months = total_months % 12
            parts = [f"{years} year{'s' if years != 1 else ''}"]
            if months:
                parts.append(f"{months} month{'s' if months != 1 else ''}")
            if rem_weeks:
                parts.append(f"{rem_weeks} week{'s' if rem_weeks != 1 else ''}")
            return " ".join(parts)
    
    # Fallback to week-based calculation if no birthday date provided
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


def kcal_split(total_kcal: float, meals_per_day: int, diet_list: List[dict], foods_list: List[dict], meal_settings: dict = None) -> tuple:
    """Calculate per-meal feeding plan. Returns DataFrame with meal_num, Food, pct, kcal_day, kcal_meal, grams_per_meal, food_type
    
    This function distributes foods across meals to meet:
    1. Each meal's target calories (from meal_kcal percentage)
    2. Each meal's wet/dry proportion (from meal_wet percentage)
    
    If requirements cannot be met, foods are distributed proportionally with warnings.
    """
    if total_kcal <= 0 or meals_per_day <= 0 or not diet_list or not foods_list:
        return pd.DataFrame(columns=["meal_num", "Food", "pct", "kcal_day", "kcal_meal", "grams_per_meal", "food_type"]), []
    
    foods_dict = {f["id"]: f for f in foods_list}
    out = []
    warnings = []  # Store warnings for impossible configurations
    
    # Get meal kcal percentages (default to equal distribution)
    meal_kcal_pcts = {}
    if meal_settings and "meal_kcal" in meal_settings:
        # Convert string keys to int for easier access
        for k, v in meal_settings["meal_kcal"].items():
            meal_kcal_pcts[int(k)] = float(v)
    else:
        # Default: equal distribution
        for meal_num in range(1, meals_per_day + 1):
            meal_kcal_pcts[meal_num] = 100.0 / meals_per_day
    
    # Get meal wet/dry proportions (default to 50/50)
    meal_wet_pcts = {}
    if meal_settings and "meal_wet" in meal_settings:
        # Convert string keys to int for easier access
        for k, v in meal_settings["meal_wet"].items():
            meal_wet_pcts[int(k)] = float(v)
    else:
        # Default: 50% wet, 50% dry
        for meal_num in range(1, meals_per_day + 1):
            meal_wet_pcts[meal_num] = 50.0
    
    # First, analyze available foods
    wet_foods = []
    dry_foods = []
    for diet_item in diet_list:
        fid = int(diet_item["food_id"])
        pct = float(diet_item["pct_daily_kcal"])
        food = foods_dict.get(fid)
        if not food:
            continue
        food_type = food.get("food_type", "")
        if food_type == "wet":
            wet_foods.append({"food": food, "pct": pct, "kcal_day": total_kcal * pct / 100.0})
        elif food_type == "dry":
            dry_foods.append({"food": food, "pct": pct, "kcal_day": total_kcal * pct / 100.0})
    
    total_wet_pct = sum(f["pct"] for f in wet_foods)
    total_dry_pct = sum(f["pct"] for f in dry_foods)
    total_wet_kcal = sum(f["kcal_day"] for f in wet_foods)
    total_dry_kcal = sum(f["kcal_day"] for f in dry_foods)
    
    # Calculate per meal for each meal
    for meal_num in range(1, meals_per_day + 1):
        meal_kcal_pct = meal_kcal_pcts.get(meal_num, 100.0 / meals_per_day)
        meal_wet_pct = meal_wet_pcts.get(meal_num, 50.0)
        meal_dry_pct = 100.0 - meal_wet_pct
        
        # Target kcal for this meal
        meal_target_kcal = total_kcal * meal_kcal_pct / 100.0
        
        # Target wet and dry kcal for this meal
        meal_target_wet_kcal = meal_target_kcal * meal_wet_pct / 100.0
        meal_target_dry_kcal = meal_target_kcal * meal_dry_pct / 100.0
        
        # Calculate what's possible for this meal
        # We need to distribute the daily food amounts across meals
        # The constraint is: sum of all meals for each food = daily amount
        
        # For now, use a proportional distribution approach
        # Calculate how much of each food type we can allocate to this meal
        # based on the meal's target proportions
        
        # Calculate minimum and maximum possible wet percentage for this meal
        # Minimum: if we put all dry foods in other meals (if possible)
        # Maximum: if we put all wet foods in this meal (if possible)
        
        # Simple approach: distribute foods proportionally to meet meal requirements
        # If we can't meet exact requirements, distribute proportionally and warn
        
        # Calculate available wet/dry kcal for this meal
        # We'll distribute daily amounts across meals based on meal_kcal percentages
        # Then adjust to meet wet/dry requirements
        
        # Distribute foods to meet both calorie and wet/dry requirements
        # Strategy: Allocate foods proportionally, then adjust to meet wet/dry target
        
        # Calculate how much wet and dry we need for this meal
        meal_target_wet_kcal = meal_target_kcal * meal_wet_pct / 100.0
        meal_target_dry_kcal = meal_target_kcal * meal_dry_pct / 100.0
        
        # Distribute wet foods to meet target wet kcal
        if total_wet_kcal > 0 and meal_target_wet_kcal > 0:
            for item in wet_foods:
                food = item["food"]
                kcal_day = item["kcal_day"]
                
                # Calculate proportion of wet foods this meal should get
                # Based on: meal_target_wet_kcal / total_wet_kcal
                wet_proportion = meal_target_wet_kcal / total_wet_kcal
                food_meal_kcal = kcal_day * wet_proportion
                
                kcal_per_kg = calories_per_kg(food)
                if not kcal_per_kg or kcal_per_kg <= 0:
                    continue
                
                grams_pm = (food_meal_kcal * 1000.0) / kcal_per_kg if food_meal_kcal > 0 else 0
                
                out.append({
                    "meal_num": meal_num,
                    "Food": food["name"],
                    "pct": item["pct"],
                    "kcal_day": kcal_day,
                    "kcal_meal": round(food_meal_kcal, 1),
                    "grams_per_meal": round(grams_pm, 1),
                    "food_type": "wet"
                })
        
        # Distribute dry foods to meet target dry kcal
        if total_dry_kcal > 0 and meal_target_dry_kcal > 0:
            for item in dry_foods:
                food = item["food"]
                kcal_day = item["kcal_day"]
                
                # Calculate proportion of dry foods this meal should get
                # Based on: meal_target_dry_kcal / total_dry_kcal
                dry_proportion = meal_target_dry_kcal / total_dry_kcal
                food_meal_kcal = kcal_day * dry_proportion
                
                kcal_per_kg = calories_per_kg(food)
                if not kcal_per_kg or kcal_per_kg <= 0:
                    continue
                
                grams_pm = (food_meal_kcal * 1000.0) / kcal_per_kg if food_meal_kcal > 0 else 0
                
                out.append({
                    "meal_num": meal_num,
                    "Food": food["name"],
                    "pct": item["pct"],
                    "kcal_day": kcal_day,
                    "kcal_meal": round(food_meal_kcal, 1),
                    "grams_per_meal": round(grams_pm, 1),
                    "food_type": "dry"
                })
    
    # Calculate warnings for each meal
    warnings = []
    for meal_num in range(1, meals_per_day + 1):
        meal_kcal_pct = meal_kcal_pcts.get(meal_num, 100.0 / meals_per_day)
        meal_wet_pct = meal_wet_pcts.get(meal_num, 50.0)
        
        # Calculate what's actually possible for this meal
        # Minimum wet %: if we put minimum wet foods in this meal
        # Maximum wet %: if we put maximum wet foods in this meal
        
        # Calculate min/max based on available foods and meal calorie percentage
        meal_kcal = total_kcal * meal_kcal_pct / 100.0
        
        # Minimum wet: put as much dry as possible in this meal
        # Maximum wet: put as much wet as possible in this meal
        # But we need to consider that foods are distributed across all meals
        
        # Simple check: if meal wants more wet than available, or more dry than available
        if total_wet_kcal > 0 and total_dry_kcal > 0:
            # Calculate min/max wet percentage possible for this meal
            # This is a simplified calculation - in reality it depends on distribution across all meals
            min_wet_pct = max(0, ((meal_kcal - total_dry_kcal) / meal_kcal * 100.0) if meal_kcal > 0 else 0)
            max_wet_pct = min(100, (total_wet_kcal / meal_kcal * 100.0) if meal_kcal > 0 else 100)
            
            min_wet_pct = max(0, min(100, min_wet_pct))
            max_wet_pct = max(0, min(100, max_wet_pct))
            
            if meal_wet_pct < min_wet_pct - 1.0:
                warnings.append({
                    "meal_num": meal_num,
                    "type": "wet_too_low",
                    "message": f"Meal {meal_num}: Wet food % ({meal_wet_pct:.0f}%) is too low. Minimum possible: {min_wet_pct:.0f}%",
                    "min_wet": round(min_wet_pct),
                    "max_wet": round(max_wet_pct)
                })
            elif meal_wet_pct > max_wet_pct + 1.0:
                warnings.append({
                    "meal_num": meal_num,
                    "type": "wet_too_high",
                    "message": f"Meal {meal_num}: Wet food % ({meal_wet_pct:.0f}%) is too high. Maximum possible: {max_wet_pct:.0f}%",
                    "min_wet": round(min_wet_pct),
                    "max_wet": round(max_wet_pct)
                })
        elif total_wet_kcal == 0 and meal_wet_pct > 0:
            warnings.append({
                "meal_num": meal_num,
                "type": "no_wet_food",
                "message": f"Meal {meal_num}: No wet foods in diet plan, but {meal_wet_pct:.0f}% wet requested.",
                "min_wet": 0,
                "max_wet": 0
            })
        elif total_dry_kcal == 0 and meal_wet_pct < 100:
            warnings.append({
                "meal_num": meal_num,
                "type": "no_dry_food",
                "message": f"Meal {meal_num}: No dry foods in diet plan, but {100 - meal_wet_pct:.0f}% dry requested.",
                "min_wet": 100,
                "max_wet": 100
            })
    
    return pd.DataFrame(out), warnings

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

def save_diet(cat_id: int, diet_list: List[dict], meal_settings: dict = None) -> bool:
    """Save diet plan for a specific cat. Returns True if successful, False otherwise."""
    if not STORAGE_AVAILABLE or not cat_id:
        print("Error: Storage not available or cat_id missing")
        return False
    try:
        data = get_cat(cat_id)
        if not data:
            print(f"Cat {cat_id} not found, cannot save diet")
            return False
        # Preserve all other data when saving diet
        data["diet"] = diet_list
        if meal_settings:
            data["meal_settings"] = meal_settings
        print(f"Saving diet plan for cat {cat_id} with {len(diet_list)} items: {diet_list}")
        if meal_settings:
            print(f"Meal settings: {meal_settings}")
        success = storage_manager.write_json(data, f"data/cat_{cat_id}")
        if success:
            # Verify the write by reading it back
            verify_data = get_cat(cat_id)
            if verify_data:
                saved_diet = verify_data.get("diet", [])
                # Check if the saved diet matches what we tried to save
                if len(saved_diet) == len(diet_list):
                    # Verify the food_ids match
                    saved_food_ids = {item.get("food_id") for item in saved_diet}
                    expected_food_ids = {item.get("food_id") for item in diet_list}
                    if saved_food_ids == expected_food_ids:
                        print(f"Successfully saved and verified diet plan for cat {cat_id}")
                        return True
                    else:
                        print(f"Warning: Diet food_ids don't match. Saved: {saved_food_ids}, Expected: {expected_food_ids}")
                else:
                    print(f"Warning: Diet save verification - length mismatch. Saved: {len(saved_diet)}, Expected: {len(diet_list)}")
                    print(f"Saved diet: {saved_diet}")
                    print(f"Expected diet: {diet_list}")
            else:
                print(f"Warning: Could not read back saved data for cat {cat_id}")
            return False
        else:
            print(f"Error: Failed to save diet plan for cat {cat_id}")
            return False
    except Exception as e:
        print(f"Error saving diet: {e}")
        import traceback
        traceback.print_exc()
        return False

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

    if action == "update_life_stage" and cat_id:
        # Update only life stage
        cat_data = get_cat(cat_id)
        if cat_data:
            life_stage_override = request.form.get("life_stage_override") or None
            cat_data["life_stage_override"] = life_stage_override
            save_cat(cat_data)
            return redirect(url_for("home", cat_id=cat_id))
        return redirect(url_for("home", cat_id=cat_id))
    
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
        food_type = request.form.get("food_type", "").strip()
        if not food_type or food_type not in ["wet", "dry"]:
            return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))
        kcal_per_kg = float(request.form.get("kcal_per_kg"))
        if kcal_per_kg <= 0:
            return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))
        food_data = {
            "name": name,
            "food_type": food_type,
            "kcal_per_kg": round(kcal_per_kg, 1)
        }
        save_food(food_data)
        return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))

    if action == "delete_food":
        fid = int(request.form.get("del_food_id"))
        delete_food(fid)
        tab = request.form.get("current_tab", "foods")
        return redirect(url_for("home", cat_id=cat_id, tab=tab) if cat_id else url_for("home", tab=tab))

    if action == "save_diet":
        if not cat_id:
            print(f"Error: save_diet action requires cat_id. Form data: {dict(request.form)}")
            return redirect(url_for("home"))
        try:
            foods = get_foods()
            total = 0
            diet_list = []
            print(f"save_diet: Processing diet plan for cat {cat_id}")
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
            print(f"save_diet: Total percentage = {total}%, diet_list has {len(diet_list)} items")
            if total == 100:
                # Get meal settings
                selected_cat = get_cat(cat_id)
                meals_per_day = selected_cat.get("meals_per_day", 3) if selected_cat else 3
                meal_settings = {
                    "meal_kcal": {},
                    "meal_wet": {}
                }
                meal_kcal_total = 0
                for meal_num in range(1, meals_per_day + 1):
                    meal_kcal_str = request.form.get(f"meal_kcal_{meal_num}", "0") or "0"
                    meal_kcal = int(float(meal_kcal_str))
                    meal_settings["meal_kcal"][meal_num] = meal_kcal
                    meal_kcal_total += meal_kcal
                    
                    meal_wet_str = request.form.get(f"meal_wet_{meal_num}")
                    # Handle None, empty string, but allow "0" as valid value
                    if meal_wet_str is None or meal_wet_str == "":
                        meal_wet_str = "50"  # Default only if truly missing
                    meal_wet = int(float(meal_wet_str))
                    # Ensure value is between 0 and 100
                    meal_wet = max(0, min(100, meal_wet))
                    meal_settings["meal_wet"][meal_num] = meal_wet
                
                print(f"save_diet: Meal kcal total = {meal_kcal_total}%, meal_settings = {meal_settings}")
                success = save_diet(cat_id, diet_list, meal_settings)
                if success:
                    print(f"Diet plan saved successfully for cat {cat_id}")
                else:
                    print(f"Warning: Diet save may have failed for cat {cat_id}")
            else:
                print(f"Error: Diet plan total is {total}%, must be exactly 100%")
            tab = request.form.get("current_tab", "diet")
            print(f"Redirecting to home with cat_id={cat_id}, tab={tab}")
            return redirect(url_for("home", cat_id=cat_id, tab=tab))
        except Exception as e:
            print(f"Error in save_diet: {e}")
            import traceback
            traceback.print_exc()
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
    birthday_date = None
    if birthday:
        try:
            birthday_date = date.fromisoformat(birthday)
            age_weeks = weeks_between(birthday_date, date.today())
        except Exception as e:
            print(f"Error parsing birthday {birthday}: {e}")
            age_weeks = 0.0
    
    stage = (selected_cat.get("life_stage_override") or "") or infer_life_stage(age_weeks)
    age_display = format_age_display(age_weeks, birthday_date)
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
    meal_settings = selected_cat.get("meal_settings", {}) if selected_cat else {}
    meal_warnings = []
    if daily_kcal and not diet_df.empty and not foods_df.empty:
        per_meal, meal_warnings = kcal_split(daily_kcal, int(selected_cat.get("meals_per_day", 3)), diet_list, foods_list, meal_settings)

    # for diet form display - convert to integers for display
    diet_map = {int(r["food_id"]): int(round(float(r["pct_daily_kcal"]))) for _, r in diet_df.iterrows()} if not diet_df.empty else {}
    
    # Calculate grams per day for each food in diet plan (for display recommendations)
    # Create a map of food_id -> grams_per_day based on current percentages and daily_kcal
    grams_recommendations = {}
    if daily_kcal and foods_list:
        foods_dict = {f["id"]: f for f in foods_list}
        for food_id, pct in diet_map.items():
            if pct > 0:
                food = foods_dict.get(food_id)
                if food:
                    kcal_per_kg = calories_per_kg(food)
                    if kcal_per_kg and kcal_per_kg > 0:
                        # Calculate grams per day: (daily_kcal * pct / 100) * 1000 / kcal_per_kg
                        kcal_for_food = daily_kcal * pct / 100.0
                        grams_per_day = (kcal_for_food * 1000.0) / kcal_per_kg
                        grams_recommendations[food_id] = round(grams_per_day, 1)

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
        grams_recommendations=grams_recommendations,
        meal_settings=meal_settings,
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

def generate_diet_plan_email(cat_id: int, recipient_email: str) -> Optional[str]:
    """Generate and send daily diet plan email for a cat. Returns error message if failed, None if success."""
    if not SENDGRID_AVAILABLE:
        return "SendGrid not configured"
    
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
    if not sendgrid_api_key:
        return "SENDGRID_API_KEY not set"
    
    try:
        # Get cat data
        cat_data = get_cat(cat_id)
        if not cat_data:
            return f"Cat {cat_id} not found"
        
        cat_name = cat_data.get("name", "Your cat")
        
        # Get all necessary data
        weights_list = get_weights(cat_id)
        foods_list = get_foods()
        diet_list = get_diet(cat_id)
        
        if not diet_list:
            return f"No diet plan found for {cat_name}"
        
        # Convert to DataFrames
        weights_df = pd.DataFrame(weights_list) if weights_list else pd.DataFrame(columns=["dt", "weight_kg"])
        foods_df = pd.DataFrame(foods_list) if foods_list else pd.DataFrame(columns=["id", "name", "food_type", "kcal_per_kg"])
        diet_df = pd.DataFrame(diet_list) if diet_list else pd.DataFrame(columns=["food_id", "pct_daily_kcal"])
        
        # Calculate age and stage
        birthday = cat_data.get("birthday")
        age_weeks = 0.0
        birthday_date = None
        if birthday:
            try:
                birthday_date = date.fromisoformat(birthday)
                age_weeks = weeks_between(birthday_date, date.today())
            except Exception as e:
                print(f"Error parsing birthday {birthday}: {e}")
        
        stage = (cat_data.get("life_stage_override") or "") or infer_life_stage(age_weeks)
        stage_display = format_life_stage(stage)
        
        # Get latest weight
        latest_w = None
        if not weights_df.empty:
            latest_w = float(weights_df.iloc[-1]["weight_kg"])
        
        # Calculate daily kcal
        if latest_w:
            daily_kcal = der_kcal(latest_w, stage)
        elif age_weeks > 0:
            estimated_weight = estimate_weight_by_age(age_weeks)
            daily_kcal = der_kcal(estimated_weight, stage)
        else:
            daily_kcal = None
        
        if not daily_kcal:
            return f"Cannot calculate daily kcal for {cat_name}"
        
        # Get meal settings
        meal_settings = cat_data.get("meal_settings", {})
        meals_per_day = int(cat_data.get("meals_per_day", 3))
        
        # Calculate per-meal plan
        per_meal_df, meal_warnings = kcal_split(daily_kcal, meals_per_day, diet_list, foods_list, meal_settings)
        per_meal = per_meal_df.to_dict(orient="records")
        
        if not per_meal:
            return f"No meal plan available for {cat_name}"
        
        # Build email HTML
        today = date.today().strftime("%B %d, %Y")
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ background: linear-gradient(135deg, #fff5f5 0%, #f8f9fa 100%); padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .meal-section {{ margin: 20px 0; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
                .meal-title {{ color: #e91e63; font-weight: 600; font-size: 1.1rem; margin-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #fff5f5; font-weight: 600; }}
                .badge {{ padding: 3px 8px; border-radius: 4px; font-size: 0.85em; }}
                .badge-wet {{ background-color: #0dcaf0; color: white; }}
                .badge-dry {{ background-color: #6c757d; color: white; }}
                .summary {{ background: #e7f3ff; padding: 15px; border-radius: 8px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>🐾 Daily Diet Plan for {cat_name}</h2>
                <p><strong>Date:</strong> {today}</p>
                <p><strong>Daily Target:</strong> {daily_kcal:.0f} kcal</p>
                <p><strong>Life Stage:</strong> {stage_display}</p>
                <p><strong>Meals Per Day:</strong> {meals_per_day}</p>
            </div>
        """
        
        # Group meals by meal number
        meals_dict = {}
        for item in per_meal:
            meal_num = item.get("meal_num", 1)
            if meal_num not in meals_dict:
                meals_dict[meal_num] = []
            meals_dict[meal_num].append(item)
        
        # Add meal sections
        for meal_num in sorted(meals_dict.keys()):
            meal_items = meals_dict[meal_num]
            meal_total_kcal = sum(item.get("kcal_meal", 0) for item in meal_items)
            
            meal_label = f"{meal_num}{'st' if meal_num == 1 else 'nd' if meal_num == 2 else 'rd' if meal_num == 3 else 'th'} Meal"
            
            html_content += f"""
            <div class="meal-section">
                <div class="meal-title">{meal_label} ({meal_total_kcal:.0f} kcal)</div>
                <table>
                    <thead>
                        <tr>
                            <th>Food</th>
                            <th>Type</th>
                            <th>Grams per Meal</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            for item in meal_items:
                food_name = item.get("Food", "")
                food_type = item.get("food_type", "")
                grams = item.get("grams_per_meal", 0)
                
                type_badge = f'<span class="badge badge-{food_type}">{food_type.title()}</span>' if food_type else ""
                
                html_content += f"""
                        <tr>
                            <td><strong>{food_name}</strong></td>
                            <td>{type_badge}</td>
                            <td>{grams:.1f} g</td>
                        </tr>
                """
            
            html_content += """
                    </tbody>
                </table>
            </div>
            """
        
        html_content += """
            <div class="summary">
                <p><strong>💡 Tip:</strong> Feed according to the meal plan above. Adjust portions if your cat's activity level or weight changes.</p>
            </div>
        </body>
        </html>
        """
        
        # Send email
        from_email = os.getenv("SENDGRID_FROM_EMAIL", "noreply@babbu-feeder.com")
        message = Mail(
            from_email=from_email,
            to_emails=recipient_email,
            subject=f"🐾 Daily Diet Plan for {cat_name} - {today}",
            html_content=html_content
        )
        
        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        
        if response.status_code in [200, 201, 202]:
            print(f"Email sent successfully to {recipient_email} for cat {cat_id}")
            return None
        else:
            return f"SendGrid API error: {response.status_code}"
            
    except Exception as e:
        print(f"Error sending email: {e}")
        import traceback
        traceback.print_exc()
        return str(e)

@app.route("/api/send-daily-email", methods=["GET", "POST"])
def send_daily_email():
    """Endpoint to send daily diet plan email. Can be called by Vercel Cron Jobs."""
    # Get recipient email from environment or default
    recipient_email = os.getenv("DAILY_EMAIL_RECIPIENT")
    if not recipient_email:
        return jsonify({"error": "DAILY_EMAIL_RECIPIENT not set"}), 500
    
    # Get cat ID from environment or default to 1 (Youtiao)
    cat_id = int(os.getenv("DAILY_EMAIL_CAT_ID", "1"))
    
    # Optional: Check for secret token to prevent unauthorized access
    secret_token = os.getenv("CRON_SECRET")
    if secret_token:
        provided_token = request.headers.get("Authorization") or request.args.get("token")
        if provided_token != f"Bearer {secret_token}":
            return jsonify({"error": "Unauthorized"}), 401
    
    error = generate_diet_plan_email(cat_id, recipient_email)
    
    if error:
        return jsonify({"error": error}), 500
    
    return jsonify({"success": True, "message": f"Email sent to {recipient_email} for cat {cat_id}"})

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

