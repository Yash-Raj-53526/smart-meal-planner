"""
app.py

Web frontend for the Smart Recipe & Meal Planner.

Flask serves one page (templates/index.html) plus a small JSON API. The API
does not re-implement any logic: it calls the same functions the command-line
version uses (recipe_database, pantry_manager, matching_engine, meal_planner,
reports). Only the interactive input() prompts are replaced by validated
request data, with the same validation rules as the menus.

Run:  python app.py        (opens http://127.0.0.1:5000 in your browser)
"""

import math
import os
import tempfile
import threading
import webbrowser

from flask import Flask, jsonify, render_template, request, send_file

import matching_engine as me
import meal_planner as mp
import pantry_manager as pm
import recipe_database as rdb
import reports as rpt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("MEAL_PLANNER_DATA", BASE_DIR)   # override is used by the tests
RECIPES_FILE = os.path.join(DATA_DIR, "recipes.csv")
PANTRY_FILE = os.path.join(DATA_DIR, "pantry.csv")
HISTORY_FILE = os.path.join(DATA_DIR, "meal_history.csv")

app = Flask(__name__)
write_lock = threading.Lock()   # one request changes the CSV files at a time


# ----------------------------------------------------------------- helpers

def error(message, status=400, **extra):
    return jsonify({"error": message, **extra}), status


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def parse_positive_int(value):
    """'250' -> 250. Rejects booleans, decimals, zero and negatives (like the CLI)."""
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if number > 0 else None


def parse_number(value, allow_zero=False):
    """'1.5' -> 1.5. Positive only, or non-negative when allow_zero is True."""
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        return None
    return number


def parse_ingredients(value):
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value if str(item).strip()}


def shown(number):
    """2.0 -> '2', 1.5 -> '1.5' (for messages)."""
    return str(int(number)) if float(number).is_integer() else str(number)


def recipe_json(name, info):
    return {
        "name": name,
        "category": info["category"],
        "calories": info["calories"],
        "cook_time": info["cook_time"],
        "ingredients": sorted(info["ingredients"]),
    }


def pantry_json(name, info):
    return {"name": name, "quantity": info["quantity"], "unit": info["unit"]}


def validate_recipe_fields(data):
    """Same rules as recipe_database.add_recipe(). Returns (fields, error_message)."""
    ingredients = parse_ingredients(data.get("ingredients"))
    if not ingredients:
        return None, "Enter at least one ingredient."
    category = str(data.get("category", "")).strip().lower()
    if category not in rdb.VALID_CATEGORIES:
        return None, "Choose breakfast, lunch or dinner."
    calories = parse_positive_int(data.get("calories"))
    if calories is None:
        return None, "Calories must be a positive whole number."
    cook_time = parse_positive_int(data.get("cook_time"))
    if cook_time is None:
        return None, "Cook time must be a positive whole number of minutes."
    return {
        "ingredients": ingredients,
        "category": category,
        "calories": calories,
        "cook_time": cook_time,
    }, None


# ------------------------------------------------------------------- page

@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------- recipes

@app.get("/api/recipes")
def list_recipes():
    recipes = rdb.load_recipes(RECIPES_FILE)
    ordered = sorted(recipes.items(), key=lambda pair: pair[0].lower())
    return jsonify([recipe_json(name, info) for name, info in ordered])


@app.post("/api/recipes")
def add_recipe():
    data = body()
    name = str(data.get("name", "")).strip()
    if not name:
        return error("Recipe name can't be empty.")
    with write_lock:
        recipes = rdb.load_recipes(RECIPES_FILE)
        if name in recipes:
            return error(f"A recipe called '{name}' already exists. Choose a different name.", 409)
        fields, problem = validate_recipe_fields(data)
        if problem:
            return error(problem)
        recipes[name] = fields
        rdb.save_recipes(recipes, RECIPES_FILE)
    return jsonify(recipe_json(name, fields)), 201


@app.put("/api/recipes/<path:name>")
def edit_recipe(name):
    with write_lock:
        recipes = rdb.load_recipes(RECIPES_FILE)
        if name not in recipes:
            return error(f"No recipe called '{name}' found.", 404)
        fields, problem = validate_recipe_fields(body())
        if problem:
            return error(problem)
        recipes[name] = fields
        rdb.save_recipes(recipes, RECIPES_FILE)
    return jsonify(recipe_json(name, fields))


@app.delete("/api/recipes/<path:name>")
def delete_recipe(name):
    with write_lock:
        recipes = rdb.load_recipes(RECIPES_FILE)
        if name not in recipes:
            return error(f"No recipe called '{name}' found.", 404)
        del recipes[name]
        rdb.save_recipes(recipes, RECIPES_FILE)
    return jsonify({"deleted": name})


# ----------------------------------------------------------------- pantry

@app.get("/api/pantry")
def list_pantry():
    pantry = pm.load_pantry(PANTRY_FILE)
    return jsonify([pantry_json(name, pantry[name]) for name in sorted(pantry)])


@app.post("/api/pantry")
def add_pantry_item():
    data = body()
    name = str(data.get("name", "")).strip().lower()
    if not name:
        return error("Ingredient name can't be empty.")
    quantity = parse_number(data.get("quantity"))
    if quantity is None:
        return error("Quantity must be a positive number.")
    unit = str(data.get("unit", "")).strip() or "pcs"

    with write_lock:
        pantry = pm.load_pantry(PANTRY_FILE)
        existing = pantry.get(name)
        merged = False
        if existing and existing["unit"].lower() == unit.lower():
            existing["quantity"] += quantity          # same unit: add to the stock
            merged = True
        elif existing and not data.get("overwrite"):  # different unit: ask first
            return error(
                f"'{name}' is already stored as {shown(existing['quantity'])} {existing['unit']}.",
                409, conflict=True, existing=pantry_json(name, existing),
            )
        else:
            pantry[name] = {"quantity": quantity, "unit": unit}
        pm.save_pantry(pantry, PANTRY_FILE)

    return jsonify({**pantry_json(name, pantry[name]), "merged": merged}), 201


@app.put("/api/pantry/<path:name>")
def update_pantry_item(name):
    name = name.strip().lower()
    quantity = parse_number(body().get("quantity"), allow_zero=True)   # 0 = used it all up
    if quantity is None:
        return error("Quantity must be zero or a positive number.")
    with write_lock:
        pantry = pm.load_pantry(PANTRY_FILE)
        if name not in pantry:
            return error(f"No ingredient called '{name}' found in the pantry.", 404)
        pantry[name]["quantity"] = quantity
        pm.save_pantry(pantry, PANTRY_FILE)
    return jsonify(pantry_json(name, pantry[name]))


@app.delete("/api/pantry/<path:name>")
def remove_pantry_item(name):
    name = name.strip().lower()
    with write_lock:
        pantry = pm.load_pantry(PANTRY_FILE)
        if name not in pantry:
            return error(f"No ingredient called '{name}' found in the pantry.", 404)
        del pantry[name]
        pm.save_pantry(pantry, PANTRY_FILE)
    return jsonify({"removed": name})


# --------------------------------------------------- match and rank (core)

@app.get("/api/match")
def match():
    category = request.args.get("category", "").strip().lower() or None
    recipes = rdb.load_recipes(RECIPES_FILE)
    pantry = pm.load_pantry(PANTRY_FILE)

    ranked = me.rank_recipes(recipes, pm.get_ingredient_names(pantry), category=category)
    items = []
    for entry in ranked:
        ingredients = recipes[entry["name"]]["ingredients"]
        items.append({
            "name": entry["name"],
            "category": entry["category"],
            "calories": entry["calories"],
            "cook_time": entry["cook_time"],
            "score": round(entry["match_score"], 4),
            "status": entry["status"],
            "have": sorted(ingredients - entry["missing"]),
            "missing": sorted(entry["missing"]),
        })
    return jsonify({"items": items, "pantry_size": len(pantry)})


# ------------------------------------------------------------- meal plan

@app.get("/api/plan")
def plan():
    avoid = parse_positive_int(request.args.get("avoid_repeat_days", 3)) or 3
    avoid = min(avoid, 7)
    recipes = rdb.load_recipes(RECIPES_FILE)
    pantry_names = pm.get_ingredient_names(pm.load_pantry(PANTRY_FILE))

    meal_plan = mp.generate_meal_plan(recipes, pantry_names, avoid_repeat_days=avoid)
    entries = [{
        "day": entry["day"],
        "slot": entry["slot"],
        "recipe": entry["recipe"],
        "status": entry["status"],
        "missing": sorted(entry["missing"]),
        "calories": recipes[entry["recipe"]]["calories"] if entry["recipe"] else 0,
    } for entry in meal_plan]
    shopping = [{"ingredient": name, "count": count} for name, count in mp.build_shopping_list(meal_plan)]
    return jsonify({"days": mp.DAYS, "slots": mp.SLOTS, "avoid": avoid, "plan": entries, "shopping": shopping})


@app.post("/api/plan/save")
def save_plan():
    entries = body().get("plan")
    if not isinstance(entries, list) or not entries:
        return error("There is no plan to save.")
    recipes = rdb.load_recipes(RECIPES_FILE)

    clean = []
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {}
        day, slot, recipe = entry.get("day"), entry.get("slot"), entry.get("recipe")
        if day not in mp.DAYS or slot not in mp.SLOTS:
            return error("The plan contains an unknown day or meal.")
        if recipe is None:
            continue                       # empty slots are skipped, as in save_meal_plan()
        if recipe not in recipes:
            return error(f"'{recipe}' is not in the recipe database.")
        clean.append({"day": day, "slot": slot, "recipe": recipe})
    if not clean:
        return error("There are no meals to save.")

    with write_lock:
        mp.save_meal_plan(clean, HISTORY_FILE)
    return jsonify({"saved": len(clean)})


# --------------------------------------------------------------- reports

@app.get("/api/reports")
def reports():
    recipes = rdb.load_recipes(RECIPES_FILE)
    history = rpt.load_meal_history(HISTORY_FILE)
    nutrition = rpt.nutrition_summary(history, recipes)
    per_day = nutrition["per_day"]
    return jsonify({
        "total_meals": len(history),
        "most_cooked": [{"recipe": name, "count": count} for name, count in rpt.most_cooked_recipes(history)],
        "categories": rpt.category_breakdown(history, recipes),
        "nutrition": {
            "total": nutrition["total_calories"],
            "average": nutrition["average_per_day"],
            "per_day": [{"day": day, "calories": per_day[day]} for day in mp.DAYS if day in per_day],
        },
    })


@app.get("/api/reports/chart.png")
def report_chart():
    """The matplotlib bar chart from reports.plot_most_cooked(), served as an image."""
    history = rpt.load_meal_history(HISTORY_FILE)
    path = os.path.join(tempfile.gettempdir(), "smart_meal_planner_chart.png")
    try:
        result = rpt.plot_most_cooked(history, output_path=path)
    except ImportError:
        return error("matplotlib is not installed. Run: pip install matplotlib", 501)
    if result is None:
        return error("No meal history yet.", 404)
    return send_file(path, mimetype="image/png", max_age=0)


if __name__ == "__main__":
    url = "http://127.0.0.1:5000"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Smart Meal Planner is running at {url}  (press Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5000, debug=False)
