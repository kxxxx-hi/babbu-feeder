# app.py
import math
import sqlite3
from datetime import date, datetime
from typing import List, Tuple, Optional

import altair as alt
import pandas as pd
import streamlit as st

DB_PATH = "cat_feeder.db"

# ---------- DB helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY CHECK (id=1),
        name TEXT,
        anchor_date TEXT NOT NULL,            -- date when starting age was recorded
        anchor_age_weeks REAL NOT NULL,       -- age (weeks) on anchor_date
        meals_per_day INTEGER NOT NULL DEFAULT 3,
        life_stage_override TEXT              -- optional: kitten_0_4m, kitten_4_12m, adult_neutered, adult_intact
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY,
        dt TEXT NOT NULL UNIQUE,
        total_kcal REAL NOT NULL,
        meals_per_day INTEGER NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS plan_items (
        id INTEGER PRIMARY KEY,
        plan_id INTEGER NOT NULL,
        food_id INTEGER NOT NULL,
        kcal_day REAL NOT NULL,
        qty_per_meal REAL NOT NULL,
        unit TEXT NOT NULL,
        grams_per_meal REAL,
        FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE CASCADE,
        FOREIGN KEY(food_id) REFERENCES foods(id) ON DELETE CASCADE
    );
    """)
    conn.commit()
    conn.close()

def fetch_df(query: str, params: Tuple=()):
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def execute(query: str, params: Tuple=()):
    conn = get_conn()
    conn.execute(query, params)
    conn.commit()
    conn.close()

def executemany(query: str, rows: List[Tuple]):
    conn = get_conn()
    conn.executemany(query, rows)
    conn.commit()
    conn.close()

# ---------- math ----------
def weeks_between(d1: date, d2: date) -> float:
    return (d2 - d1).days / 7.0

def current_age_weeks(anchor_date: date, anchor_age_weeks: float) -> float:
    return anchor_age_weeks + weeks_between(anchor_date, date.today())

def infer_life_stage(age_weeks: float) -> str:
    # Map by age if no override
    if age_weeks < 16:
        return "kitten_0_4m"
    elif age_weeks < 52:
        return "kitten_4_12m"
    else:
        return "adult_neutered"

def rer_kcal(weight_kg: float) -> float:
    # Use exponential form for all bodyweights
    # RER = 70 * (BWkg ^ 0.75)
    return 70.0 * (weight_kg ** 0.75)

def der_factor(life_stage: str) -> float:
    # Factors from commonly used vet guidance.
    # Kittens 0–4 mo: 2.5 × RER
    # Kittens 4–12 mo: 2.0 × RER
    # Adult neutered: 1.2 × RER
    # Adult intact: 1.4 × RER
    mapping = {
        "kitten_0_4m": 2.5,
        "kitten_4_12m": 2.0,
        "adult_neutered": 1.2,
        "adult_intact": 1.4,
        "adult_obese_prone": 1.0,
    }
    return mapping.get(life_stage, 1.2)

def der_kcal(weight_kg: float, life_stage: str) -> float:
    return rer_kcal(weight_kg) * der_factor(life_stage)

# ---------- UI helpers ----------
def load_profile() -> Optional[dict]:
    df = fetch_df("SELECT * FROM profile WHERE id=1;")
    return df.iloc[0].to_dict() if not df.empty else None

def save_profile(anchor_date: date, anchor_age_weeks: float, meals_per_day: int,
                 name: str, life_stage_override: Optional[str]):
    if load_profile():
        execute("UPDATE profile SET anchor_date=?, anchor_age_weeks=?, meals_per_day=?, name=?, life_stage_override=? WHERE id=1;",
                (anchor_date.isoformat(), anchor_age_weeks, meals_per_day, name, life_stage_override))
    else:
        execute("INSERT INTO profile(id, anchor_date, anchor_age_weeks, meals_per_day, name, life_stage_override) VALUES (1,?,?,?,?,?);",
                (anchor_date.isoformat(), anchor_age_weeks, meals_per_day, name, life_stage_override))

def latest_weight() -> Optional[Tuple[date, float]]:
    df = fetch_df("SELECT dt, weight_kg FROM weights ORDER BY dt DESC LIMIT 1;")
    if df.empty:
        return None
    return (date.fromisoformat(df['dt'][0]), float(df['weight_kg'][0]))

def compute_daily_kcal_series() -> pd.DataFrame:
    prof = load_profile()
    if prof is None:
        return pd.DataFrame(columns=["dt","age_weeks","weight_kg","der_kcal"])
    w = fetch_df("SELECT dt, weight_kg FROM weights ORDER BY dt ASC;")
    if w.empty:
        return pd.DataFrame(columns=["dt","age_weeks","weight_kg","der_kcal"])
    rows = []
    for _, r in w.iterrows():
        dt = date.fromisoformat(r["dt"])
        age_w = prof["anchor_age_weeks"] + weeks_between(date.fromisoformat(prof["anchor_date"]), dt)
        stage = prof["life_stage_override"] or infer_life_stage(age_w)
        kcal = der_kcal(r["weight_kg"], stage)
        rows.append({"dt": dt, "age_weeks": age_w, "weight_kg": r["weight_kg"], "der_kcal": kcal})
    return pd.DataFrame(rows)

def kcal_split_table(total_kcal: float, meals_per_day: int, diet_df: pd.DataFrame, foods_df: pd.DataFrame) -> pd.DataFrame:
    if diet_df.empty or foods_df.empty or total_kcal <= 0 or meals_per_day <= 0:
        return pd.DataFrame(columns=[
            "Food","% kcal/day","kcal/day","kcal/meal","Qty/meal","Unit","Grams/meal"
        ])

    foods = foods_df.set_index("id")
    out = []
    for _, row in diet_df.iterrows():
        fid = int(row["food_id"])
        pct = float(row["pct_daily_kcal"])
        kcal_day = total_kcal * pct / 100.0
        kcal_meal = kcal_day / meals_per_day
        unit = foods.loc[fid, "unit"]
        kcal_per_unit = foods.loc[fid, "kcal_per_unit"]
        qty_per_meal = kcal_meal / kcal_per_unit if kcal_per_unit > 0 else 0
        grams_per_meal = None
        if unit == "kcal_per_g":
            grams_per_meal = qty_per_meal
        elif unit == "kcal_per_cup":
            gpc = foods.loc[fid, "grams_per_cup"]
            grams_per_meal = qty_per_meal * gpc if pd.notnull(gpc) and gpc > 0 else None

        out.append({
            "Food": foods.loc[fid, "name"],
            "% kcal/day": pct,
            "kcal/day": round(kcal_day, 1),
            "kcal/meal": round(kcal_meal, 1),
            "Qty/meal": round(qty_per_meal, 3),
            "Unit": "g" if unit=="kcal_per_g" else "cups",
            "Grams/meal": None if grams_per_meal is None else round(grams_per_meal, 1)
        })
    df = pd.DataFrame(out)
    return df

# ---------- App ----------
st.set_page_config(page_title="Kitten Calorie & Feeding Planner", layout="wide")

init_db()
st.title("Kitten Calorie & Feeding Planner")

with st.sidebar:
    st.subheader("Profile")
    prof = load_profile()
    name = st.text_input("Cat name (optional)", value=(prof.get("name") if prof else ""))
    if prof:
        anchor_date = st.date_input("Anchor date (when starting age recorded)", value=date.fromisoformat(prof["anchor_date"]))
        anchor_age_weeks = st.number_input("Starting age on anchor date (weeks)", min_value=0.0, step=0.5, value=float(prof["anchor_age_weeks"]))
        meals_per_day = st.number_input("Meals per day", min_value=1, max_value=12, value=int(prof["meals_per_day"]))
        lso = st.selectbox("Life stage override (optional)", ["" ,"kitten_0_4m","kitten_4_12m","adult_neutered","adult_intact","adult_obese_prone"],
                           index=("" , "kitten_0_4m","kitten_4_12m","adult_neutered","adult_intact","adult_obese_prone").index(prof["life_stage_override"] or ""))
    else:
        anchor_date = st.date_input("Anchor date (when starting age recorded)", value=date.today())
        anchor_age_weeks = st.number_input("Starting age on anchor date (weeks)", min_value=0.0, step=0.5, value=8.0)
        meals_per_day = st.number_input("Meals per day", min_value=1, max_value=12, value=3)
        lso = st.selectbox("Life stage override (optional)", ["","kitten_0_4m","kitten_4_12m","adult_neutered","adult_intact","adult_obese_prone"])

    if st.button("Save profile"):
        save_profile(anchor_date, anchor_age_weeks, meals_per_day, name, lso if lso != "" else None)
        st.success("Saved.")

tabs = st.tabs(["Dashboard", "Log data", "Diet planner", "Foods", "Calculations & sources", "Data"])

# ---------- Dashboard ----------
with tabs[0]:
    st.subheader("At a glance")

    prof = load_profile()
    if not prof:
        st.info("Set profile in the sidebar first.")
        st.stop()

    latest = latest_weight()
    if latest is None:
        st.info("Log at least one weight.")
        st.stop()

    latest_dt, latest_w = latest
    age_wk_now = current_age_weeks(date.fromisoformat(prof["anchor_date"]), prof["anchor_age_weeks"])
    stage = prof["life_stage_override"] or infer_life_stage(age_wk_now)

    daily_need = der_kcal(latest_w, stage)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Age (weeks)", f"{age_wk_now:.1f}")
    c2.metric("Latest weight (kg)", f"{latest_w:.3f}")
    c3.metric("Meals/day", f"{int(prof['meals_per_day'])}")
    c4.metric("Daily target kcal", f"{daily_need:.0f}")

    # Diet split preview
    diet_df = fetch_df("SELECT d.food_id, d.pct_daily_kcal FROM diet d;")
    foods_df = fetch_df("SELECT * FROM foods;")
    plan_table = kcal_split_table(daily_need, int(prof["meals_per_day"]), diet_df, foods_df)

    st.markdown("**Per-meal plan**")
    if plan_table.empty:
        st.info("Set a diet in the Diet planner tab to see per-meal amounts.")
    else:
        st.dataframe(plan_table, use_container_width=True)

    # Charts
    st.markdown("**Trends**")
    series = compute_daily_kcal_series()
    if not series.empty:
        series["dt"] = pd.to_datetime(series["dt"])
        w_chart = alt.Chart(series).mark_line().encode(
            x=alt.X('dt:T', title='Date'),
            y=alt.Y('weight_kg:Q', title='Weight (kg)')
        ).properties(height=250)
        kcal_chart = alt.Chart(series).mark_line().encode(
            x=alt.X('dt:T', title='Date'),
            y=alt.Y('der_kcal:Q', title='Target kcal/day')
        ).properties(height=250)
        st.altair_chart(w_chart, use_container_width=True)
        st.altair_chart(kcal_chart, use_container_width=True)
    else:
        st.info("Add more weekly weights to see charts.")

# ---------- Log data ----------
with tabs[1]:
    st.subheader("Weekly weight")
    dt = st.date_input("Date", value=date.today(), key="weight_dt")
    wkg = st.number_input("Weight (kg)", min_value=0.1, step=0.01, format="%.3f")
    if st.button("Save weight"):
        try:
            execute("INSERT OR REPLACE INTO weights(dt, weight_kg) VALUES (?,?);", (dt.isoformat(), float(wkg)))
            st.success("Saved.")
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("Recent weights")
    wdf = fetch_df("SELECT dt AS Date, weight_kg AS Weight_kg FROM weights ORDER BY dt DESC LIMIT 20;")
    st.dataframe(wdf, use_container_width=True)

# ---------- Diet planner ----------
with tabs[2]:
    st.subheader("Diet composition and per-meal amounts")

    prof = load_profile()
    foods_df = fetch_df("SELECT * FROM foods ORDER BY name;")
    if foods_df.empty:
        st.info("Add foods first.")
    else:
        st.markdown("**Set percent of daily calories by food**")
        # Build editor from existing diet or empty template
        cur_diet = fetch_df("""
            SELECT d.id, d.food_id, f.name, d.pct_daily_kcal
            FROM diet d JOIN foods f ON f.id=d.food_id
            ORDER BY f.name;""")
        # Template for new rows
        template = pd.DataFrame({
            "food_id": foods_df["id"],
            "name": foods_df["name"],
        })
        # Merge to ensure all foods appear once
        merged = template.merge(cur_diet[["food_id","pct_daily_kcal"]], on="food_id", how="left")
        merged["pct_daily_kcal"] = merged["pct_daily_kcal"].fillna(0.0)
        edited = st.data_editor(
            merged[["food_id","name","pct_daily_kcal"]].rename(columns={"name":"Food"}),
            num_rows="fixed",
            use_container_width=True,
            column_config={
                "food_id": st.column_config.NumberColumn("Food ID", disabled=True),
                "Food": st.column_config.TextColumn(disabled=True),
                "pct_daily_kcal": st.column_config.NumberColumn("% kcal/day", min_value=0.0, max_value=100.0, step=1.0)
            },
            key="diet_editor"
        )

        total_pct = float(edited["pct_daily_kcal"].sum())
        st.write(f"Total = **{total_pct:.1f}%**")
        if st.button("Save diet"):
            if abs(total_pct - 100.0) > 0.01:
                st.error("Total must be exactly 100%.")
            else:
                # Clear and insert
                execute("DELETE FROM diet;")
                rows = [(int(r.food_id), float(r.pct_daily_kcal)) for r in edited.itertuples()]
                executemany("INSERT INTO diet(food_id, pct_daily_kcal) VALUES (?,?);", rows)
                st.success("Diet saved.")

        # Preview per-meal amounts for today's weight
        latest = latest_weight()
        if latest:
            latest_dt, latest_w = latest
            age_wk_now = current_age_weeks(date.fromisoformat(prof["anchor_date"]), prof["anchor_age_weeks"])
            stage = prof["life_stage_override"] or infer_life_stage(age_wk_now)
            daily_need = der_kcal(latest_w, stage)
            preview = kcal_split_table(daily_need, int(prof["meals_per_day"]),
                                       fetch_df("SELECT food_id, pct_daily_kcal FROM diet;"),
                                       foods_df)
            st.markdown("**Per-meal amounts (based on latest weight and current meals/day)**")
            if preview.empty:
                st.info("Set diet percentages to 100%.")
            else:
                st.dataframe(preview, use_container_width=True)

                # Save today's plan
                if st.button("Save today's feeding plan"):
                    try:
                        execute("INSERT OR REPLACE INTO plans(dt, total_kcal, meals_per_day) VALUES (?,?,?);",
                                (date.today().isoformat(), float(daily_need), int(prof["meals_per_day"])))
                        plan_id = fetch_df("SELECT id FROM plans WHERE dt=?;", (date.today().isoformat(),)).iloc[0]["id"]
                        execute("DELETE FROM plan_items WHERE plan_id=?;", (int(plan_id),))
                        foods_idx = foods_df.set_index("name")
                        rows = []
                        for _, r in preview.iterrows():
                            food_id = int(foods_idx.loc[r["Food"], "id"])
                            unit = "g" if foods_idx.loc[r["Food"], "unit"]=="kcal_per_g" else "cups"
                            grams_pm = None if pd.isna(r["Grams/meal"]) else float(r["Grams/meal"])
                            rows.append((int(plan_id), food_id, float(r["kcal/day"]), float(r["Qty/meal"]), unit, grams_pm))
                        executemany("""INSERT INTO plan_items(plan_id, food_id, kcal_day, qty_per_meal, unit, grams_per_meal)
                                       VALUES (?,?,?,?,?,?);""", rows)
                        st.success("Saved.")
                    except Exception as e:
                        st.error(f"Error: {e}")

# ---------- Foods ----------
with tabs[3]:
    st.subheader("Food items")
    st.markdown("Add foods with calorie density. For dry or wet foods, use kcal per gram. For kibble by volume, use kcal per cup and optionally grams per cup to also get grams.")
    name_in = st.text_input("Item name")
    unit_in = st.selectbox("Calorie unit", ["kcal_per_g","kcal_per_cup"])
    kcal_unit_in = st.number_input("Calories per unit", min_value=0.0, step=0.1)
    gpc_in = st.number_input("Grams per cup (optional, if unit is kcal_per_cup)", min_value=0.0, step=1.0, format="%.0f")
    add = st.button("Add food")
    if add:
        try:
            grams_per_cup = float(gpc_in) if unit_in=="kcal_per_cup" and gpc_in>0 else None
            execute("INSERT INTO foods(name, unit, kcal_per_unit, grams_per_cup) VALUES (?,?,?,?);",
                    (name_in.strip(), unit_in, float(kcal_unit_in), grams_per_cup))
            st.success("Added.")
        except Exception as e:
            st.error(f"Error: {e}")

    foods = fetch_df("SELECT id, name, unit, kcal_per_unit, grams_per_cup FROM foods ORDER BY name;")
    st.dataframe(foods.rename(columns={
        "id":"ID","name":"Name","unit":"Unit","kcal_per_unit":"kcal per unit","grams_per_cup":"g per cup"
    }), use_container_width=True)

    st.markdown("Delete a food")
    del_id = st.selectbox("Food ID", options=[""] + list(foods["id"].astype(str)))
    if st.button("Delete"):
        if del_id != "":
            try:
                execute("DELETE FROM foods WHERE id=?;", (int(del_id),))
                st.success("Deleted.")
            except Exception as e:
                st.error(f"Error: {e}")

# ---------- Calculations & sources ----------
with tabs[4]:
    st.subheader("How calorie targets are calculated")
    st.markdown("""
**Formulas**

- Resting Energy Requirement (RER) = `70 × (body weight in kg)^0.75`. Alternative linear form `30 × BWkg + 70` is valid only for ~2–45 kg.  
- Daily Energy Requirement (DER) = `RER × factor` where the factor depends on life stage.

**Factors used here**

- Kittens 0–4 months: `2.5 × RER`  
- Kittens 4–12 months: `2.0 × RER`  
- Adult, neutered: `1.2 × RER`  
- Adult, intact: `1.4 × RER`  
- Adult, obese-prone: `1.0 × RER`

These are population estimates. Individual cats can vary widely. Monitor body condition and adjust by 10–20% at a time.

**Sources**  
- Merck Veterinary Manual: RER formulas and maintenance factors.  
- AAHA/AAFP guidelines and teaching resources noting high kitten energy needs and wide individual variance.  
- Petplace summary showing 0–4 mo `2.5 × RER` and 4–12 mo `2.0 × RER`.
""")

# ---------- Data ----------
with tabs[5]:
    st.subheader("Raw data")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Weights**")
        st.dataframe(fetch_df("SELECT * FROM weights ORDER BY dt;"), use_container_width=True)
        st.markdown("**Profile**")
        st.dataframe(fetch_df("SELECT * FROM profile;"), use_container_width=True)
    with c2:
        st.markdown("**Foods**")
        st.dataframe(fetch_df("SELECT * FROM foods ORDER BY name;"), use_container_width=True)
        st.markdown("**Diet**")
        st.dataframe(fetch_df("""
            SELECT d.id, f.name AS food, d.pct_daily_kcal
            FROM diet d JOIN foods f ON f.id=d.food_id
            ORDER BY f.name;"""), use_container_width=True)
        st.markdown("**Saved plans**")
        st.dataframe(fetch_df("SELECT * FROM plans ORDER BY dt DESC;"), use_container_width=True)
        st.markdown("**Plan items**")
        st.dataframe(fetch_df("""
            SELECT p.dt, f.name AS food, i.kcal_day, i.qty_per_meal, i.unit, i.grams_per_meal
            FROM plan_items i
            JOIN plans p ON p.id=i.plan_id
            JOIN foods f ON f.id=i.food_id
            ORDER BY p.dt DESC, f.name;"""), use_container_width=True)
