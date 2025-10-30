import math
import sqlite3
import os
from datetime import date, datetime
from typing import Optional, Tuple, List

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for

DB_PATH = "/tmp/cat_feeder.db"  # Vercel fs: write to /tmp

# Fix template path for Vercel - templates are in parent directory
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
app = Flask(__name__, template_folder=template_dir)

# ---------- DB ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY CHECK (id=1),
        name TEXT,
        anchor_date TEXT NOT NULL,
        anchor_age_weeks REAL NOT NULL,
        meals_per_day INTEGER NOT NULL DEFAULT 3,
        life_stage_override TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS weights (
        id INTEGER PRIMARY KEY,
        dt TEXT NOT NULL UNIQUE,
        weight_kg REAL NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS foods (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        unit TEXT NOT NULL CHECK(unit IN ('kcal_per_g','kcal_per_cup')),
        kcal_per_unit REAL NOT NULL,
        grams_per_cup REAL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS diet (
        id INTEGER PRIMARY KEY,
        food_id INTEGER NOT NULL,
        pct_daily_kcal REAL NOT NULL,
        FOREIGN KEY(food_id) REFERENCES foods(id) ON DELETE CASCADE
    );
    """)
    conn.commit()
    # Seed default profile if missing
    cur.execute("SELECT COUNT(*) AS c FROM profile WHERE id=1;")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO profile(id, name, anchor_date, anchor_age_weeks, meals_per_day, life_stage_override) VALUES (1,?,?,?,?,?)",
            (None, date.today().isoformat(), 8.0, 3, None)
        )
        conn.commit()
    conn.close()

init_db()

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

def kcal_split(total_kcal: float, meals_per_day: int, diet_df: pd.DataFrame, foods_df: pd.DataFrame) -> pd.DataFrame:
    if total_kcal <= 0 or meals_per_day <= 0 or diet_df.empty or foods_df.empty:
        return pd.DataFrame(columns=["Food","pct","kcal_day","kcal_meal","qty_per_meal","unit","grams_per_meal"])
    foods = foods_df.set_index("id")
    out = []
    for _, r in diet_df.iterrows():
        fid = int(r["food_id"])
        pct = float(r["pct_daily_kcal"])
        kcal_day = total_kcal * pct / 100.0
        kcal_meal = kcal_day / meals_per_day
        unit = foods.loc[fid, "unit"]
        kpu = foods.loc[fid, "kcal_per_unit"]
        qty_per_meal = kcal_meal / kpu if kpu > 0 else 0.0
        grams_pm = None
        if unit == "kcal_per_g":
            grams_pm = qty_per_meal
        elif unit == "kcal_per_cup":
            gpc = foods.loc[fid, "grams_per_cup"]
            grams_pm = qty_per_meal * gpc if gpc else None
        out.append({
            "Food": foods.loc[fid, "name"],
            "pct": pct,
            "kcal_day": round(kcal_day, 1),
            "kcal_meal": round(kcal_meal, 1),
            "qty_per_meal": round(qty_per_meal, 3),
            "unit": ("g" if unit=="kcal_per_g" else "cups"),
            "grams_per_meal": None if grams_pm is None else round(grams_pm, 1),
        })
    return pd.DataFrame(out)

# ---------- Data helpers ----------
def fetch_df(q: str, params: tuple=()):
    conn = get_conn()
    df = pd.read_sql_query(q, conn, params=params)
    conn.close()
    return df

def execute(q: str, params: tuple=()):
    conn = get_conn()
    conn.execute(q, params)
    conn.commit()
    conn.close()

def executemany(q: str, rows: List[tuple]):
    conn = get_conn()
    conn.executemany(q, rows)
    conn.commit()
    conn.close()

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def home():
    # Handle actions
    action = request.form.get("action")

    if action == "save_profile":
        name = request.form.get("name") or ""
        anchor_date = request.form.get("anchor_date") or date.today().isoformat()
        anchor_age_weeks = float(request.form.get("anchor_age_weeks") or 8.0)
        mpd = int(request.form.get("meals_per_day") or 3)
        lso = request.form.get("life_stage_override") or None
        execute("UPDATE profile SET name=?, anchor_date=?, anchor_age_weeks=?, meals_per_day=?, life_stage_override=? WHERE id=1;",
                (name, anchor_date, anchor_age_weeks, mpd, lso))
        return redirect(url_for("home"))

    if action == "add_weight":
        wdt = request.form.get("weight_dt") or date.today().isoformat()
        wkg = float(request.form.get("weight_kg"))
        execute("INSERT OR REPLACE INTO weights(dt, weight_kg) VALUES (?,?);", (wdt, wkg))
        return redirect(url_for("home"))

    if action == "add_food":
        name = request.form.get("food_name").strip()
        unit = request.form.get("food_unit")
        kpu = float(request.form.get("kcal_per_unit"))
        gpc_raw = request.form.get("grams_per_cup")
        gpc = float(gpc_raw) if gpc_raw else None
        execute("INSERT INTO foods(name, unit, kcal_per_unit, grams_per_cup) VALUES (?,?,?,?);",
                (name, unit, kpu, gpc))
        return redirect(url_for("home"))

    if action == "delete_food":
        fid = int(request.form.get("del_food_id"))
        execute("DELETE FROM foods WHERE id=?;", (fid,))
        return redirect(url_for("home"))

    if action == "save_diet":
        # rows like diet_pct_<food_id>
        foods = fetch_df("SELECT id FROM foods ORDER BY name;")
        total = 0.0
        rows = []
        for fid in foods["id"].tolist():
            pct = float(request.form.get(f"diet_pct_{fid}", "0") or "0")
            total += pct
            rows.append((int(fid), pct))
        if round(total, 1) != 100.0:
            # fall through and show error on page
            pass
        else:
            execute("DELETE FROM diet;")
            executemany("INSERT INTO diet(food_id, pct_daily_kcal) VALUES (?,?);", rows)
            return redirect(url_for("home"))

    # Data for render
    prof = fetch_df("SELECT * FROM profile WHERE id=1;").iloc[0].to_dict()
    weights = fetch_df("SELECT dt, weight_kg FROM weights ORDER BY dt;")
    foods = fetch_df("SELECT * FROM foods ORDER BY name;")
    diet = fetch_df("SELECT food_id, pct_daily_kcal FROM diet;")

    age_weeks = current_age_weeks(date.fromisoformat(prof["anchor_date"]), float(prof["anchor_age_weeks"]))
    stage = (prof["life_stage_override"] or "") or infer_life_stage(age_weeks)

    latest_w = None
    if not weights.empty:
        latest_w = float(weights.iloc[-1]["weight_kg"])
    daily_kcal = der_kcal(latest_w, stage) if latest_w else None

    # charts data
    trend = []
    if not weights.empty:
        for _, r in weights.iterrows():
            dt = date.fromisoformat(r["dt"])
            age_w = float(prof["anchor_age_weeks"]) + weeks_between(date.fromisoformat(prof["anchor_date"]), dt)
            stg = prof["life_stage_override"] or infer_life_stage(age_w)
            kcal = der_kcal(float(r["weight_kg"]), stg)
            trend.append({
                "dt": r["dt"],
                "weight_kg": float(r["weight_kg"]),
                "der_kcal": round(kcal, 1)
            })

    per_meal = pd.DataFrame()
    if daily_kcal and not diet.empty and not foods.empty:
        per_meal = kcal_split(daily_kcal, int(prof["meals_per_day"]), diet, foods)

    # for diet form display
    foods_list = foods.to_dict(orient="records")
    diet_map = {int(r["food_id"]): float(r["pct_daily_kcal"]) for _, r in diet.iterrows()}

    return render_template(
        "index.html",
        prof=prof,
        age_weeks=age_weeks,
        stage=stage,
        latest_w=latest_w,
        daily_kcal=daily_kcal,
        weights_list=weights.to_dict(orient="records"),
        per_meal=per_meal.to_dict(orient="records"),
        foods=foods_list,
        diet_map=diet_map,
        total_pct=sum(diet_map.values()) if diet_map else 0.0,
        trend=trend
    )

# Health check
@app.route("/api/health")
def health():
    return {"ok": True}

# Vercel requires variable "app"
# already defined: app = Flask(__name__)
