"""
test_web_api.py

Tests for the web frontend's JSON API (app.py). Every test runs against a
temporary copy of the CSV files, so the real recipes.csv / pantry.csv /
meal_history.csv are never modified.

Usage (from the project root):
    python tests/test_web_api.py        (needs: pip install flask)
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = tempfile.mkdtemp()
for name in ("recipes.csv", "pantry.csv", "meal_history.csv"):
    shutil.copy(os.path.join(ROOT, name), DATA)
os.environ["MEAL_PLANNER_DATA"] = DATA      # must be set before app is imported

import app as web   # noqa: E402


class WebApiTests(unittest.TestCase):
    def setUp(self):
        for name in ("recipes.csv", "pantry.csv", "meal_history.csv"):
            shutil.copy(os.path.join(ROOT, name), DATA)
        self.client = web.app.test_client()

    def test_page_loads(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Smart Meal Planner", res.data)

    def test_match_is_ranked_with_have_and_missing(self):
        items = self.client.get("/api/match").get_json()["items"]
        self.assertEqual(len(items), 20)
        scores = [i["score"] for i in items]
        self.assertEqual(scores, sorted(scores, reverse=True))
        ready = [i for i in items if i["status"] == "Ready now"]
        self.assertTrue(ready and all(not i["missing"] for i in ready))

    def test_match_category_filter(self):
        items = self.client.get("/api/match?category=lunch").get_json()["items"]
        self.assertTrue(items and all(i["category"] == "lunch" for i in items))

    def test_add_recipe_and_rules(self):
        good = {"name": "Poha", "ingredients": "rice flakes, onion", "category": "breakfast",
                "calories": "250", "cook_time": "10"}
        self.assertEqual(self.client.post("/api/recipes", json=good).status_code, 201)
        self.assertEqual(self.client.post("/api/recipes", json=good).status_code, 409)      # duplicate
        for change in ({"name": " "}, {"category": "snack"}, {"calories": "-5"},
                       {"calories": "2.5"}, {"cook_time": "0"}, {"ingredients": " , "}):
            res = self.client.post("/api/recipes", json={**good, "name": "X", **change})
            self.assertEqual(res.status_code, 400, change)
        self.assertEqual(len(self.client.get("/api/recipes").get_json()), 21)

    def test_edit_and_delete_recipe(self):
        edit = {"ingredients": ["rice", "egg"], "category": "lunch", "calories": 300, "cook_time": 12}
        self.assertEqual(self.client.put("/api/recipes/Egg Fried Rice", json=edit).status_code, 200)
        self.assertEqual(self.client.put("/api/recipes/Nope", json=edit).status_code, 404)
        self.assertEqual(self.client.delete("/api/recipes/Egg Fried Rice").status_code, 200)
        self.assertEqual(self.client.delete("/api/recipes/Egg Fried Rice").status_code, 404)

    def test_pantry_merge_conflict_overwrite(self):
        rice = lambda **kw: self.client.post("/api/pantry", json={"name": "Rice", "quantity": 1, **kw})
        res = rice(unit="kg")                         # same unit: quantities add up
        self.assertTrue(res.get_json()["merged"])
        self.assertEqual(res.get_json()["quantity"], 3.0)
        res = rice(unit="g")                          # different unit: ask first
        self.assertEqual(res.status_code, 409)
        self.assertTrue(res.get_json()["conflict"])
        res = rice(unit="g", overwrite=True)
        self.assertEqual((res.get_json()["quantity"], res.get_json()["unit"]), (1.0, "g"))

    def test_pantry_validation_update_remove(self):
        bad = self.client.post("/api/pantry", json={"name": "salt", "quantity": "-1", "unit": "g"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.put("/api/pantry/egg", json={"quantity": 0}).status_code, 200)   # 0 allowed
        self.assertEqual(self.client.put("/api/pantry/egg", json={"quantity": -2}).status_code, 400)
        self.assertEqual(self.client.put("/api/pantry/ghost", json={"quantity": 1}).status_code, 404)
        self.assertEqual(self.client.delete("/api/pantry/egg").status_code, 200)
        self.assertEqual(len(self.client.get("/api/pantry").get_json()), 14)

    def test_plan_shape_and_save(self):
        data = self.client.get("/api/plan").get_json()
        self.assertEqual(len(data["plan"]), 21)
        self.assertTrue(data["shopping"])
        plan = [{k: e[k] for k in ("day", "slot", "recipe")} for e in data["plan"]]
        before = len(self.client.get("/api/reports").get_json()["most_cooked"]) and \
            self.client.get("/api/reports").get_json()["total_meals"]
        self.assertEqual(self.client.post("/api/plan/save", json={"plan": plan}).get_json()["saved"], 21)
        self.assertEqual(self.client.get("/api/reports").get_json()["total_meals"], before + 21)

    def test_plan_save_rejects_bad_input(self):
        self.assertEqual(self.client.post("/api/plan/save", json={}).status_code, 400)
        bad = {"plan": [{"day": "Monday", "slot": "lunch", "recipe": "Not A Recipe"}]}
        self.assertEqual(self.client.post("/api/plan/save", json=bad).status_code, 400)

    def test_reports(self):
        data = self.client.get("/api/reports").get_json()
        self.assertEqual(data["total_meals"], 21)
        self.assertEqual(sum(data["categories"].values()), 21)
        self.assertEqual(len(data["nutrition"]["per_day"]), 7)
        self.assertEqual(data["most_cooked"][0]["count"], 3)

    def test_reports_empty_history(self):
        open(os.path.join(DATA, "meal_history.csv"), "w").close()
        data = self.client.get("/api/reports").get_json()
        self.assertEqual(data["total_meals"], 0)
        self.assertEqual(self.client.get("/api/reports/chart.png").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
