/* Smart Meal Planner - front end.
   Plain JavaScript, no build step. Each view asks app.py for JSON
   and draws it into <main>. All the real logic stays in the Python modules. */

const main = document.getElementById('main');
const modal = document.getElementById('modal');
const toastEl = document.getElementById('toast');

const CATEGORIES = ['breakfast', 'lunch', 'dinner'];
const STATUS_CLASS = { 'Ready now': 'ready', 'Almost there': 'almost', 'Needs shopping': 'shop' };
const ICON = {
  check: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.4l2.3 2.3 4.7-5"/></svg>',
  plus: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2.5v7M2.5 6h7"/></svg>',
};

const state = {
  cook: { category: '', status: 'all', intro: true },
  plan: { avoid: 3, data: null },
  recipes: { all: [], q: '', category: '' },
};

/* ---------- small helpers ---------- */

const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = n => (Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2))));
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || 'Something went wrong. Try again.');
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  toastEl.textContent = message;
  toastEl.className = 'show' + (isError ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.className = ''; }, 3200);
}

/* run an action; show a toast instead of crashing if the server refuses it */
async function attempt(action) {
  try { return await action(); } catch (err) { toast(err.message, true); }
}

function openModal(html, onSubmit) {
  modal.innerHTML = html;
  const form = modal.querySelector('form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const box = modal.querySelector('.form-error');
    box.textContent = '';
    try {
      await onSubmit(new FormData(form));
      modal.close();
    } catch (err) {
      box.textContent = err.message;
    }
  });
  modal.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => modal.close()));
  modal.showModal();
}

function confirmDialog(title, text, action, danger = true) {
  return new Promise(resolve => {
    let confirmed = false;
    openModal(
      `<form class="dlg"><h2>${esc(title)}</h2><p>${text}</p><p class="form-error" role="alert"></p>
       <div class="actions"><button type="button" class="btn ghost" data-close>Cancel</button>
       <button class="btn ${danger ? 'danger' : ''}">${esc(action)}</button></div></form>`,
      async () => { confirmed = true; },
    );
    modal.addEventListener('close', () => resolve(confirmed), { once: true });
  });
}

const pageHead = (title, sub, actions = '') =>
  `<header class="page-head ${actions ? 'row' : ''}"><div><h1>${title}</h1>${sub ? `<p class="sub">${sub}</p>` : ''}</div>${actions}</header>`;

const chipsHtml = items => items.map(i => `<li class="chip plain">${esc(i)}</li>`).join('');

/* ================= Cook now (match and rank) ================= */

async function viewCook() {
  const { category } = state.cook;
  const data = await api('/api/match' + (category ? `?category=${category}` : ''));
  renderCook(data);
}

function renderCook(data, refocus) {
  const { category, status } = state.cook;
  const items = data.items;
  const count = s => items.filter(i => i.status === s).length;
  const ready = count('Ready now');
  const headline = ready === 0 ? 'Nothing is ready to cook yet.' : `You can cook ${plural(ready, 'dish', 'dishes')} right now.`;
  const tabs = [
    ['all', 'All', items.length],
    ['Ready now', 'Ready now', ready],
    ['Almost there', 'Almost there', count('Almost there')],
    ['Needs shopping', 'Needs shopping', count('Needs shopping')],
  ];
  const shown = status === 'all' ? items : items.filter(i => i.status === status);

  let list;
  if (!items.length) {
    list = `<div class="empty"><p>No recipes found. Add a recipe to start matching.</p><a class="btn" href="#recipes">Go to Recipes</a></div>`;
  } else if (!shown.length) {
    list = `<div class="empty"><p>No recipes with this status.</p></div>`;
  } else {
    list = `<ol class="matches ${state.cook.intro ? 'intro' : ''}">${shown.map(matchRow).join('')}</ol>`;
  }

  main.innerHTML =
    pageHead(headline, `Compared with the ${plural(data.pantry_size, 'ingredient', 'ingredients')} in your pantry, best match first.`) +
    `<div class="toolbar">
       <div class="tabs" role="group" aria-label="Filter by readiness">
         ${tabs.map(([key, label, n]) => `<button data-status="${key}" aria-pressed="${status === key}"><b>${n}</b><span>${label}</span></button>`).join('')}
       </div>
       <div class="seg" role="group" aria-label="Meal type">
         ${['', ...CATEGORIES].map(c => `<button data-cat="${c}" aria-pressed="${category === c}">${c ? cap(c) : 'All meals'}</button>`).join('')}
       </div>
     </div>` + list;

  state.cook.intro = false;
  main.querySelectorAll('[data-status]').forEach(b => b.addEventListener('click', () => {
    state.cook.status = b.dataset.status;
    renderCook(data);
    main.querySelector(`[data-status="${b.dataset.status}"]`).focus();
  }));
  main.querySelectorAll('[data-cat]').forEach(b => b.addEventListener('click', async () => {
    state.cook.category = b.dataset.cat;
    await attempt(viewCook);
    main.querySelector(`[data-cat="${b.dataset.cat}"]`).focus();
  }));
}

function matchRow(r) {
  const total = r.have.length + r.missing.length;
  const segs = r.have.map((_, i) => `<i class="on" style="--i:${i}"></i>`).join('') + r.missing.map(() => '<i></i>').join('');
  const chips =
    r.have.map(i => `<li class="chip have">${ICON.check}<span class="sr">In pantry: </span>${esc(i)}</li>`).join('') +
    r.missing.map(i => `<li class="chip miss">${ICON.plus}<span class="sr">Missing: </span>${esc(i)}</li>`).join('');
  return `<li class="match s-${STATUS_CLASS[r.status]}">
    <div class="meter" role="img" aria-label="${r.have.length} of ${total} ingredients in your pantry">
      <span class="pct">${Math.round(r.score * 100)}%</span><span class="segs">${segs}</span>
    </div>
    <div class="info">
      <div class="head"><h3>${esc(r.name)}</h3><span class="pill">${esc(r.status)}</span></div>
      <p class="facts"><span>${cap(r.category)}</span><span>${r.cook_time} min</span><span>${r.calories} kcal</span></p>
      <ul class="chips" aria-label="Ingredients">${chips}</ul>
    </div></li>`;
}

/* ================= Week plan ================= */

async function viewPlan() {
  const data = await api(`/api/plan?avoid_repeat_days=${state.plan.avoid}`);
  state.plan.data = data;
  const entry = {};
  data.plan.forEach(e => { entry[`${e.day}|${e.slot}`] = e; });

  const rows = data.days.map(day => {
    const cells = data.slots.map(slot => entry[`${day}|${slot}`]);
    const kcal = cells.reduce((sum, e) => sum + e.calories, 0);
    return `<div role="row"><div class="day" role="rowheader"><b>${day}</b><span>${kcal.toLocaleString()} kcal</span></div>${cells.map(planCell).join('')}</div>`;
  }).join('');

  const shopping = data.shopping.length
    ? `<ul class="shop">${data.shopping.map(s => `<li><label><input type="checkbox"><span>${esc(s.ingredient)}</span></label><span class="count">${plural(s.count, 'meal', 'meals')}</span></li>`).join('')}</ul>`
    : `<p>Your pantry covers every meal in this plan.</p>`;

  main.innerHTML =
    pageHead('Weekly plan', 'Seven days of breakfast, lunch and dinner, built from the best matches for your pantry.',
      '<button class="btn" id="save-plan">Save to history</button>') +
    `<div class="toolbar"><label class="inline">Don't repeat a dish within
       <select id="avoid">${[1, 2, 3, 4, 5, 6, 7].map(n => `<option ${n === data.avoid ? 'selected' : ''}>${n}</option>`).join('')}</select> days</label></div>
     <div class="week" role="table" aria-label="Weekly meal plan">
       <div role="row" class="hdr"><span role="columnheader">Day</span>${data.slots.map(s => `<span role="columnheader">${cap(s)}</span>`).join('')}</div>
       ${rows}
     </div>
     <section class="panel shop-panel"><h2>Shopping list</h2>
       <p>What the plan needs that your pantry doesn't have. The number shows how many planned meals use it.</p>${shopping}</section>`;

  document.getElementById('avoid').addEventListener('change', e => {
    state.plan.avoid = Number(e.target.value);
    attempt(viewPlan);
  });
  document.getElementById('save-plan').addEventListener('click', () => attempt(async () => {
    const plan = data.plan.map(({ day, slot, recipe }) => ({ day, slot, recipe }));
    const res = await api('/api/plan/save', { method: 'POST', body: { plan } });
    toast(`Saved ${plural(res.saved, 'meal', 'meals')} to history`);
  }));
}

function planCell(e) {
  const slot = cap(e.slot);
  if (!e.recipe) return `<div class="cell" role="cell" data-slot="${slot}"><span class="none">No ${e.slot} recipe yet. Add one in Recipes.</span></div>`;
  const note = e.missing.length ? `Missing ${e.missing.map(esc).join(', ')}` : 'Ready now';
  return `<div class="cell s-${STATUS_CLASS[e.status]}" role="cell" data-slot="${slot}"><b>${esc(e.recipe)}</b><span class="st"><i class="dot"></i>${note}</span></div>`;
}

/* ================= Recipes ================= */

async function viewRecipes() {
  state.recipes.all = await api('/api/recipes');
  const { q, category } = state.recipes;
  main.innerHTML =
    pageHead('Recipes', '<span id="rcount"></span>', '<button class="btn" id="add-recipe">Add recipe</button>') +
    `<div class="toolbar">
       <input type="search" id="rsearch" placeholder="Search by name or ingredient" aria-label="Search recipes" value="${esc(q)}">
       <div class="seg" role="group" aria-label="Meal type">
         ${['', ...CATEGORIES].map(c => `<button data-rcat="${c}" aria-pressed="${category === c}">${c ? cap(c) : 'All meals'}</button>`).join('')}
       </div>
     </div><div id="rlist"></div>`;

  document.getElementById('add-recipe').addEventListener('click', () => recipeDialog());
  document.getElementById('rsearch').addEventListener('input', e => { state.recipes.q = e.target.value; renderRecipeList(); });
  main.querySelectorAll('[data-rcat]').forEach(b => b.addEventListener('click', () => {
    state.recipes.category = b.dataset.rcat;
    main.querySelectorAll('[data-rcat]').forEach(x => x.setAttribute('aria-pressed', x === b));
    renderRecipeList();
  }));
  document.getElementById('rlist').addEventListener('click', e => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const recipe = visibleRecipes()[Number(btn.dataset.i)];
    if (btn.dataset.act === 'edit') recipeDialog(recipe);
    else deleteRecipe(recipe);
  });
  renderRecipeList();
}

function visibleRecipes() {
  const { all, q, category } = state.recipes;
  const term = q.trim().toLowerCase();
  return all.filter(r =>
    (!category || r.category === category) &&
    (!term || r.name.toLowerCase().includes(term) || r.ingredients.some(i => i.includes(term))));
}

function renderRecipeList() {
  const list = visibleRecipes();
  document.getElementById('rcount').textContent = `${list.length} of ${plural(state.recipes.all.length, 'recipe', 'recipes')}`;
  document.getElementById('rlist').innerHTML = list.length
    ? `<table class="rtable"><thead><tr><th>Recipe</th><th>Meal</th><th class="num">Time</th><th class="num">Calories</th><th>Ingredients</th><th><span class="sr">Actions</span></th></tr></thead><tbody>
        ${list.map((r, i) => `<tr>
          <td class="nm">${esc(r.name)}</td><td>${cap(r.category)}</td>
          <td class="num">${r.cook_time} min</td><td class="num">${r.calories} kcal</td>
          <td class="ing"><ul class="chips">${chipsHtml(r.ingredients)}</ul></td>
          <td class="acts"><button class="link" data-act="edit" data-i="${i}" aria-label="Edit ${esc(r.name)}">Edit</button>
            <button class="link danger" data-act="delete" data-i="${i}" aria-label="Delete ${esc(r.name)}">Delete</button></td></tr>`).join('')}
       </tbody></table>`
    : `<div class="empty"><p>No recipes match your search.</p></div>`;
}

function recipeDialog(recipe) {
  const editing = Boolean(recipe);
  const r = recipe || { name: '', ingredients: [], category: 'dinner', calories: '', cook_time: '' };
  openModal(
    `<form class="dlg">
      <h2>${editing ? 'Edit recipe' : 'Add recipe'}</h2>
      <label>Name<input name="name" required autocomplete="off" value="${esc(r.name)}" ${editing ? 'readonly' : ''}></label>
      <label>Ingredients<input name="ingredients" required autocomplete="off" placeholder="rice, egg, onion" value="${esc(r.ingredients.join(', '))}"><small>Separate ingredients with commas.</small></label>
      <div class="two">
        <label>Meal<select name="category">${CATEGORIES.map(c => `<option value="${c}" ${c === r.category ? 'selected' : ''}>${cap(c)}</option>`).join('')}</select></label>
        <label>Calories<input name="calories" type="number" min="1" step="1" required value="${r.calories}"></label>
        <label>Minutes<input name="cook_time" type="number" min="1" step="1" required value="${r.cook_time}"></label>
      </div>
      <p class="form-error" role="alert"></p>
      <div class="actions"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn">${editing ? 'Save changes' : 'Add recipe'}</button></div>
    </form>`,
    async form => {
      const body = Object.fromEntries(form);
      if (editing) await api('/api/recipes/' + encodeURIComponent(r.name), { method: 'PUT', body });
      else await api('/api/recipes', { method: 'POST', body });
      toast(editing ? 'Changes saved' : 'Recipe added');
      await viewRecipes();
    },
  );
}

async function deleteRecipe(recipe) {
  const ok = await confirmDialog('Delete recipe?', `<strong>${esc(recipe.name)}</strong> will be removed from recipes.csv.`, 'Delete recipe');
  if (!ok) return;
  await attempt(async () => {
    await api('/api/recipes/' + encodeURIComponent(recipe.name), { method: 'DELETE' });
    toast('Recipe deleted');
    await viewRecipes();
  });
}

/* ================= Pantry ================= */

async function viewPantry() {
  const items = await api('/api/pantry');
  main.innerHTML =
    pageHead('Pantry', `${plural(items.length, 'ingredient', 'ingredients')}. Recipes are matched against this list.`) +
    `<form class="addbar" id="pantry-add">
       <label>Ingredient<input name="name" required autocomplete="off" placeholder="e.g. flour"></label>
       <label>Quantity<input name="quantity" type="number" min="0" step="any" required inputmode="decimal"></label>
       <label>Unit<input name="unit" list="units" placeholder="pcs" autocomplete="off"></label>
       <datalist id="units"><option value="kg"><option value="g"><option value="pcs"><option value="litre"><option value="cup"><option value="bulb"><option value="loaf"><option value="bottle"></datalist>
       <button class="btn">Add to pantry</button>
     </form>` +
    (items.length
      ? `<ul class="pantry">${items.map(it => `<li>
           <span class="name">${esc(it.name)}</span>
           <span class="qty"><input type="number" min="0" step="any" value="${num(it.quantity)}" data-name="${esc(it.name)}" data-unit="${esc(it.unit)}" aria-label="Quantity of ${esc(it.name)}"><span class="unit">${esc(it.unit)}</span></span>
           <button class="link danger" data-remove="${esc(it.name)}" aria-label="Remove ${esc(it.name)}">Remove</button></li>`).join('')}</ul>`
      : `<div class="empty"><p>Your pantry is empty. Add what you have at home to see what you can cook.</p></div>`);

  document.getElementById('pantry-add').addEventListener('submit', e => {
    e.preventDefault();
    addPantryItem(Object.fromEntries(new FormData(e.target)));
  });
  const list = main.querySelector('.pantry');
  if (!list) return;
  list.addEventListener('change', e => {
    const input = e.target.closest('input[data-name]');
    if (!input) return;
    attempt(async () => {
      try {
        const res = await api('/api/pantry/' + encodeURIComponent(input.dataset.name), { method: 'PUT', body: { quantity: input.value } });
        toast(`${cap(res.name)} is now ${num(res.quantity)} ${res.unit}`);
      } catch (err) {
        await viewPantry();   // put the old value back
        throw err;
      }
    });
  });
  list.addEventListener('click', async e => {
    const btn = e.target.closest('[data-remove]');
    if (!btn) return;
    const name = btn.dataset.remove;
    if (!(await confirmDialog('Remove ingredient?', `<strong>${esc(name)}</strong> will be removed from your pantry.`, 'Remove'))) return;
    await attempt(async () => {
      await api('/api/pantry/' + encodeURIComponent(name), { method: 'DELETE' });
      toast(`${cap(name)} removed`);
      await viewPantry();
    });
  });
}

async function addPantryItem(body) {
  try {
    const res = await api('/api/pantry', { method: 'POST', body });
    toast(res.merged ? `${cap(res.name)} is now ${num(res.quantity)} ${res.unit}` : `${cap(res.name)} added`);
  } catch (err) {
    if (err.status !== 409 || !err.data.conflict) return toast(err.message, true);
    const old = err.data.existing;
    const unit = body.unit.trim() || 'pcs';
    const ok = await confirmDialog(
      'Replace stored amount?',
      `<strong>${esc(old.name)}</strong> is stored as ${num(old.quantity)} ${esc(old.unit)}. Replace it with ${esc(body.quantity)} ${esc(unit)}?`,
      'Replace', false);
    if (!ok) return;
    await attempt(async () => {
      await api('/api/pantry', { method: 'POST', body: { ...body, overwrite: true } });
      toast(`${cap(old.name)} replaced`);
    });
  }
  await attempt(viewPantry);
}

/* ================= Reports ================= */

async function viewReports() {
  const d = await api('/api/reports');
  if (!d.total_meals) {
    main.innerHTML = pageHead('Reports', '') +
      `<div class="empty"><p>No saved plans yet. Build a weekly plan and save it to history to see reports.</p><a class="btn" href="#plan">Go to Week plan</a></div>`;
    return;
  }
  const maxCooked = Math.max(...d.most_cooked.map(r => r.count));
  const bars = rows => `<div class="hbars">${rows.map(([label, n, max]) =>
    `<div class="hbar"><span class="lbl" title="${esc(label)}">${esc(label)}</span><span class="track"><span class="fill" style="display:block;width:${(n / max) * 100}%"></span></span><span class="val">${n}</span></div>`).join('')}</div>`;

  const cats = CATEGORIES.map(c => [cap(c), d.categories[c] || 0]);
  const maxCat = Math.max(...cats.map(c => c[1]), 1);
  const days = d.nutrition.per_day;
  const maxKcal = Math.max(...days.map(x => x.calories), 1);
  const avgFrac = Math.min(d.nutrition.average / maxKcal, 1);

  main.innerHTML =
    pageHead('Reports', `${plural(d.total_meals, 'planned meal', 'planned meals')} across your saved plans.`) +
    `<div class="grid2">
       <section class="panel"><h2>Most cooked recipes</h2><p>Counted from the plans you saved.</p>
         ${bars(d.most_cooked.map(r => [r.recipe, r.count, maxCooked]))}</section>
       <section class="panel"><h2>Meals by category</h2><p>How your planned meals split across the day.</p>
         ${bars(cats.map(([label, n]) => [label, n, maxCat]))}</section>
     </div>
     <section class="panel"><h2>Calories per day</h2>
       <p>${d.nutrition.total.toLocaleString()} kcal planned in total, ${d.nutrition.average.toLocaleString()} kcal on an average day.</p>
       <div class="plot" style="--f:${avgFrac}">
         ${days.map(x => `<div class="colw"><div class="bar" style="height:${(x.calories / maxKcal) * 100}%"><span>${x.calories.toLocaleString()}</span></div></div>`).join('')}
         <div class="avgline"></div>
       </div>
       <div class="dlabels">${days.map(x => `<span>${x.day.slice(0, 3)}</span>`).join('')}</div>
       <p class="legend">Average day (${d.nutrition.average.toLocaleString()} kcal)</p>
       <details class="chart"><summary>Show the matplotlib chart</summary>
         <img alt="Bar chart of the most cooked recipes" src="/api/reports/chart.png?t=${Date.now()}" loading="lazy"></details>
     </section>`;

  main.querySelector('details.chart img').addEventListener('error', e => {
    e.target.replaceWith(Object.assign(document.createElement('p'), { className: 'muted', textContent: 'The chart needs matplotlib. Run: pip install matplotlib' }));
  });
}

/* ================= router ================= */

const views = { cook: viewCook, plan: viewPlan, recipes: viewRecipes, pantry: viewPantry, reports: viewReports };
const titles = { cook: 'Cook now', plan: 'Week plan', recipes: 'Recipes', pantry: 'Pantry', reports: 'Reports' };

async function route() {
  const name = location.hash.slice(1) in views ? location.hash.slice(1) : 'cook';
  document.querySelectorAll('.rail a').forEach(a => {
    if (a.dataset.view === name) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  document.title = `${titles[name]} - Smart Meal Planner`;
  main.innerHTML = '<p class="loading">Loading…</p>';
  try {
    await views[name]();
  } catch (err) {
    main.innerHTML = `<div class="empty"><p>Couldn't load this page. Check that app.py is still running.</p><button class="btn" id="retry">Try again</button></div>`;
    document.getElementById('retry').addEventListener('click', route);
  }
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
route();
