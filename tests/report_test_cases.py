"""
report_test_cases.py

Runs the test cases listed in the project report's Testing section against the
real project modules and prints each result. Interactive functions are driven
with simulated keyboard input, and file functions use temporary files, so the
real recipes.csv / pantry.csv / meal_history.csv are never modified.

Usage (from the project root, or from anywhere):
    python tests/report_test_cases.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)            # the CSV files are opened by relative name
sys.path.insert(0, ROOT)  # so the project modules can be imported

import contextlib
import copy
import io
import json
import os
import tempfile
from unittest import mock

import recipe_database as rdb
import pantry_manager as pm
import matching_engine as me
import meal_planner as mp
import reports as rpt

RESULTS = []


def record(test_id, kind, test_input, expected, actual, passed):
    RESULTS.append({
        "id": test_id, "kind": kind, "input": test_input,
        "expected": expected, "actual": actual,
        "result": "Pass" if passed else "Fail",
    })


def run_with_input(func, inputs, *args):
    """Call func(*args) while feeding `inputs` to input(); return (value, printed text)."""
    buffer = io.StringIO()
    with mock.patch("builtins.input", side_effect=list(inputs)), contextlib.redirect_stdout(buffer):
        value = func(*args)
    return value, buffer.getvalue()


recipes = rdb.load_recipes("recipes.csv")
pantry = pm.load_pantry("pantry.csv")
pantry_names = pm.get_ingredient_names(pantry)

# T1 - normal: ranking with the sample pantry
ranked = me.rank_recipes(recipes, pantry_names)
ready = [r["name"] for r in ranked if r["status"] == "Ready now"]
record("T1", "Normal", "Rank all 20 recipes against the 15-item sample pantry",
       "3 recipes at 100% (Ready now) listed first; every recipe gets a status",
       f"{len(ready)} Ready now: {', '.join(ready)}; list length {len(ranked)}",
       len(ready) == 3 and len(ranked) == 20 and ranked[0]["match_score"] == 1.0)

# T2 - normal: hand-calculated worked example
curry = next(r for r in ranked if r["name"] == "Mixed Vegetable Curry")
record("T2", "Normal", "Match score for Mixed Vegetable Curry (6 ingredients, 5 in pantry)",
       "5/6 = 83.3%, Almost there, missing: spices",
       f"{curry['match_score'] * 100:.1f}%, {curry['status']}, missing: {', '.join(sorted(curry['missing']))}",
       round(curry["match_score"] * 100, 1) == 83.3 and curry["status"] == "Almost there"
       and curry["missing"] == {"spices"})

# T3 - boundary: thresholds at exactly 100%, 70% and 69%
ten = {f"i{n}" for n in range(10)}
seven = {f"i{n}" for n in range(7)}
hundred = {f"j{n}" for n in range(100)}
sixty_nine = {f"j{n}" for n in range(69)}
s100 = me.classify(me.compute_match(ten, ten)["match_score"])
s70 = me.classify(me.compute_match(ten, seven)["match_score"])
s69 = me.classify(me.compute_match(hundred, sixty_nine)["match_score"])
record("T3", "Boundary", "Scores of exactly 100%, 70% (7 of 10) and 69% (69 of 100)",
       "Ready now, Almost there, Needs shopping",
       f"{s100}, {s70}, {s69}",
       (s100, s70, s69) == ("Ready now", "Almost there", "Needs shopping"))

# T4 - boundary: empty pantry and a recipe with no ingredients
empty_rank = me.rank_recipes(recipes, set())
zero = me.compute_match(set(), pantry_names)
record("T4", "Boundary", "Empty pantry; and a recipe with an empty ingredient set",
       "All recipes 0% and Needs shopping; no ZeroDivisionError",
       f"{sum(1 for r in empty_rank if r['match_score'] == 0.0)} of {len(empty_rank)} recipes at 0%; "
       f"empty recipe returns score {zero['match_score']}",
       all(r["match_score"] == 0.0 and r["status"] == "Needs shopping" for r in empty_rank)
       and zero["match_score"] == 0.0)

# T5 - invalid input: add_recipe with a duplicate name, bad category and bad numbers
test_recipes = copy.deepcopy(recipes)
_, out = run_with_input(
    rdb.add_recipe,
    ["Egg Fried Rice", "Test Toast", "bread, butter", "brunch", "breakfast",
     "abc", "-5", "250", "5"],
    test_recipes)
added = test_recipes.get("Test Toast", {})
record("T5", "Invalid input",
       "Add recipe: duplicate name, category 'brunch', calories 'abc' then '-5', then valid values",
       "Each bad entry rejected with a message and re-prompted; recipe saved only with valid data",
       "Rejected: duplicate name, category, 'abc', '-5'. Saved: "
       f"{added.get('category')}, {added.get('calories')} kcal, {added.get('cook_time')} min",
       "already exists" in out and "Category must be one of" in out
       and "not a valid whole number" in out and "positive whole number" in out
       and added.get("calories") == 250 and added.get("category") == "breakfast")

# T6 - invalid input: add_ingredient with a non-numeric and a negative quantity
test_pantry = copy.deepcopy(pantry)
_, out = run_with_input(pm.add_ingredient, ["Sugar", "abc", "-2", "2", "kg"], test_pantry)
record("T6", "Invalid input", "Add pantry item 'Sugar' with quantity 'abc', then '-2', then '2' kg",
       "Both bad quantities rejected; item stored as lower-case 'sugar', 2.0 kg",
       f"Rejected both; stored sugar = {test_pantry.get('sugar')}",
       "not a valid number" in out and "positive number" in out
       and test_pantry.get("sugar") == {"quantity": 2.0, "unit": "kg"})

# T7 - special: same-unit quantities merge instead of overwriting
test_pantry = copy.deepcopy(pantry)
before = test_pantry["rice"]["quantity"]
run_with_input(pm.add_ingredient, ["Rice", "1", "KG"], test_pantry)
record("T7", "Special", "Add 1 KG of 'Rice' when the pantry already holds rice in kg",
       f"Quantities merge: {before} kg becomes {before + 1} kg (case-insensitive name and unit)",
       f"rice = {test_pantry['rice']['quantity']} {test_pantry['rice']['unit']}",
       test_pantry["rice"]["quantity"] == before + 1)

# T8 - special: update a missing ingredient, and update an existing one to zero
test_pantry = copy.deepcopy(pantry)
missing_result, _ = run_with_input(pm.update_quantity, [], test_pantry, "unicorn meat")
zero_result, _ = run_with_input(pm.update_quantity, ["0"], test_pantry, "egg")
record("T8", "Special", "Update 'unicorn meat' (not in pantry); then update 'egg' to 0",
       "First returns False with a message; second accepted (0 means used up)",
       f"Missing item returned {missing_result}; egg set to {test_pantry['egg']['quantity']}",
       missing_result is False and zero_result is True and test_pantry["egg"]["quantity"] == 0.0)

# T9 - special: malformed CSV row is skipped, valid row still loads
with tempfile.TemporaryDirectory() as folder:
    path = os.path.join(folder, "bad.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("name,ingredients,category,calories,cook_time\n")
        f.write("Good Toast,bread;butter,breakfast,200,5\n")
        f.write("Bad Toast,bread;butter,breakfast,abc,5\n")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        loaded = rdb.load_recipes(path)
record("T9", "Special", "recipes.csv with one valid row and one row whose calories are 'abc'",
       "Bad row skipped with a warning; valid row loaded; no crash",
       f"Loaded {len(loaded)} recipe ({', '.join(loaded)}); warning shown: {'Skipped a malformed row' in buffer.getvalue()}",
       list(loaded) == ["Good Toast"] and "Skipped a malformed row" in buffer.getvalue())

# T10 - normal: 7-day plan shape and repeat gap
plan = mp.generate_meal_plan(recipes, pantry_names)
day_index = {d: i for i, d in enumerate(mp.DAYS)}
appearances = {}
for entry in plan:
    appearances.setdefault(entry["recipe"], []).append(day_index[entry["day"]])
min_gap = min((b - a for days in appearances.values() for a, b in zip(days, days[1:])), default=None)
record("T10", "Normal", "Generate the weekly plan from the sample data",
       "21 entries (7 days x 3 slots); no recipe repeats within 3 days",
       f"{len(plan)} entries; {len(appearances)} distinct recipes; smallest gap between repeats = {min_gap} days",
       len(plan) == 21 and min_gap is not None and min_gap >= 3)

# T11 - special: meal plan with an empty recipe database
empty_plan = mp.generate_meal_plan({}, pantry_names)
record("T11", "Special", "Generate a meal plan when the recipe database is empty",
       "21 placeholder entries 'No suitable recipe found'; no crash; shopping list empty",
       f"{len(empty_plan)} placeholders; shopping list = {mp.build_shopping_list(empty_plan)}",
       len(empty_plan) == 21 and all(e["recipe"] is None for e in empty_plan)
       and mp.build_shopping_list(empty_plan) == [])

# T12 - special: reports with empty or missing meal history
history = rpt.load_meal_history("does_not_exist.csv")
summary = rpt.nutrition_summary([], recipes)
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    chart = rpt.plot_most_cooked([])
record("T12", "Special", "Open reports when meal_history.csv is missing / empty",
       "Empty results; chart skipped; total calories 0; no crash",
       f"history = {history}; chart = {chart}; total calories = {summary['total_calories']}",
       history == [] and chart is None and summary["total_calories"] == 0)

# T13 - normal: save and reload round trip (data persists)
with tempfile.TemporaryDirectory() as folder:
    rp, pp = os.path.join(folder, "r.csv"), os.path.join(folder, "p.csv")
    rdb.save_recipes(recipes, rp)
    pm.save_pantry(pantry, pp)
    same = rdb.load_recipes(rp) == recipes and pm.load_pantry(pp) == pantry
record("T13", "Normal", "Save recipes and pantry to temporary CSV files, then load them again",
       "Reloaded data identical to the original (survives a restart)",
       f"Identical: {same}", same)

for r in RESULTS:
    print(f"{r['id']:<4}{r['kind']:<14}{r['result']:<6}{r['actual']}")
print(f"\n{sum(r['result'] == 'Pass' for r in RESULTS)} of {len(RESULTS)} passed")

if os.environ.get("REPORT_JSON"):
    with open(os.environ["REPORT_JSON"], "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1)
