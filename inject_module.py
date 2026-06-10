"""
inject_module.py
----------------
Automatically injects reportModuleComplete (COURSE_MODULE_COMPLETE postMessage)
into HTML gamification files.

Handles these patterns:
  A) ans() with mids[] and state.done[mid]  — Pattern A (minified or formatted)
  B) completeAndGo() with courseState.modulesCompleted.includes()
  C) completeAndGo() with window.courseState.modulesCompleted.includes()
  D) completeModule(n) with numeric module IDs (Bridge duties style)
  E) submitQuiz() with state.completed.includes(current) — missions[] style
  F) quizPick() with state.completed — COLREGS/Radar style

Usage:
  python inject_module.py                  # processes all .html in current dir
  python inject_module.py path/to/folder   # processes folder
"""

import os, re, shutil, sys

FOLDER = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

FUNCTION_BODY = (
    'function reportModuleComplete({moduleIndex,moduleTitle,score,maxScore,passingScore,totalModules,completedModules}){'
    'const percentage=Math.round((score/maxScore)*100);'
    'const message={type:"COURSE_MODULE_COMPLETE",source:"course",'
    'payload:{moduleIndex,moduleTitle,score,maxScore,percentage,'
    'status:percentage>=passingScore?"passed":"failed",'
    'totalModules,completedModules,allModulesComplete:completedModules===totalModules}};'
    'if(window.parent&&window.parent!==window){window.parent.postMessage(message,"*");}}'
)

def already_done(txt):
    return 'reportModuleComplete' in txt

def extract_module_titles_from_html(txt):
    """Pull module titles from <h2>Module N: Title</h2> headings."""
    titles = {}
    for m in re.finditer(r'<h2[^>]*>.*?Module\s+(\d+)\s*[:\-–]\s*([^<]+)</h2>', txt, re.IGNORECASE):
        n   = int(m.group(1))
        mid = f'm{n}'
        titles[mid] = re.sub(r'[🔥💨💧🧪⚠️📚⚙️🔌📡✅🧭💬⚙️👥🌉📋🗣️🌐🗂️♻️🚫📘⚓🕵️]+', '', m.group(2)).strip()
    return titles

def build_titles_dict_js(titles, var_name):
    """Build a JS object literal string from a dict."""
    pairs = ','.join(f'{k}:"{v}"' for k, v in sorted(titles.items()))
    return f'const {var_name}={{{pairs}}};'

def build_ids_array_js(titles, var_name):
    ids = ','.join(f'"{k}"' for k in sorted(titles.keys()))
    return f'const {var_name}=[{ids}];'

# ── Pattern A: ans() with state.done[mid] ────────────────────────────────────

PATTERN_A_DETECT = r'function ans\(mid,type,choice,correct,btn\)'

# Minified version
PATTERN_A_MIN = re.compile(
    r"(if\(type==='act'&&!state\.done\[mid\]\)\{state\.done\[mid\]=true;state\.xp\+=20;)"
)
# Formatted version
PATTERN_A_FMT = re.compile(
    r"(if \(type === ['\"]act['\"] && !state\.done\[mid\]\) \{[\s\n]*"
    r"state\.done\[mid\] = true;[\s\n]*"
    r"state\.xp \+= 20;)",
    re.DOTALL
)

def handle_pattern_a(txt, titles_var, ids_var, passing=80):
    # Minified
    m = PATTERN_A_MIN.search(txt)
    if m:
        replacement = (
            m.group(1)
            + f'const completedModules=mids.filter(m=>state.done[m]).length;'
            + f'reportModuleComplete({{moduleIndex:mids.indexOf(mid),moduleTitle:{titles_var}[mid],'
            + f'score:1,maxScore:1,passingScore:{passing},totalModules:mids.length,completedModules}});'
        )
        return txt[:m.start()] + replacement + txt[m.end():], True

    # Formatted
    m = PATTERN_A_FMT.search(txt)
    if m:
        block = m.group(1)
        addition = (
            f'\n            const completedModules = mids.filter((m) => state.done[m]).length;\n'
            f'            reportModuleComplete({{ moduleIndex: mids.indexOf(mid),'
            f' moduleTitle: {titles_var}[mid], score: 1, maxScore: 1,'
            f' passingScore: {passing}, totalModules: mids.length, completedModules }});'
        )
        return txt[:m.end()] + addition + txt[m.end():], True

    return txt, False

# ── Pattern B/C: completeAndGo() with modulesCompleted.includes() ─────────────

PATTERN_B_DETECT = r'function completeAndGo\('
PATTERN_B_PUSH   = re.compile(
    r'((?:courseState|window\.courseState)\.modulesCompleted\.push\((\w+)\)\s*;)'
)

def handle_pattern_b(txt, titles_var, ids_var, passing=70):
    m = PATTERN_B_PUSH.search(txt)
    if not m:
        return txt, False
    param = m.group(2)   # the variable name passed to push (e.g. moduleId, module, currentModule)
    total = len(re.findall(r'\bid="m\d"', txt)) or 5
    state_prefix = 'window.courseState' if 'window.courseState' in txt else 'courseState'
    addition = (
        f'\n                const mi={ids_var}.indexOf({param});'
        f'\n                if(mi>=0){{reportModuleComplete({{moduleIndex:mi,'
        f'moduleTitle:{titles_var}[{param}],score:1,maxScore:1,'
        f'passingScore:{passing},totalModules:{ids_var}.length,'
        f'completedModules:{state_prefix}.modulesCompleted.length}});}}'
    )
    return txt[:m.end()] + addition + txt[m.end():], True

# ── Pattern D: completeModule(n) with numeric n (Bridge duties) ───────────────

PATTERN_D_DETECT = r'function completeModule\(\s*n\s*\)'
PATTERN_D_PUSH   = re.compile(
    r'(courseState\.modulesCompleted\.push\(n\)\s*;)'
)

def handle_pattern_d(txt, titles_var, passing=70):
    m = PATTERN_D_PUSH.search(txt)
    if not m:
        return txt, False
    addition = (
        f'\n    reportModuleComplete({{moduleIndex:n-1,moduleTitle:{titles_var}[n],'
        f'score:1,maxScore:1,passingScore:{passing},totalModules:5,'
        f'completedModules:courseState.modulesCompleted.length}});'
    )
    return txt[:m.end()] + addition + txt[m.end():], True

# ── Pattern E: submitQuiz() with missions[]/state.completed ───────────────────

PATTERN_E_DETECT = r'function submitQuiz\('
PATTERN_E_PUSH   = re.compile(
    r'((?:state|window\.state)\.completed\.push\(current\)\s*;)'
)

def handle_pattern_e(txt, passing=80):
    m = PATTERN_E_PUSH.search(txt)
    if not m:
        return txt, False
    addition = (
        '\n            reportModuleComplete({moduleIndex:current,'
        'moduleTitle:missions[current].title,score:1,maxScore:1,'
        f'passingScore:{passing},totalModules:missions.length,'
        'completedModules:state.completed.length});'
    )
    return txt[:m.end()] + addition + txt[m.end():], True

# ── Pattern F: quizPick() with state.completed — COLREGS/Radar style ──────────

PATTERN_F_DETECT = r'function quizPick\('
PATTERN_F_PUSH   = re.compile(
    r'(state\.completed\.push\(i\)\s*;[\s\S]{0,50}?state\.completed\.sort[^;]+;)'
)

def handle_pattern_f(txt, passing=80):
    m = PATTERN_F_PUSH.search(txt)
    if not m:
        return txt, False
    addition = (
        '\n            reportModuleComplete({moduleIndex:i,'
        'moduleTitle:course[i].title,score:1,maxScore:1,'
        f'passingScore:{passing},totalModules:course.length,'
        'completedModules:state.completed.length});'
    )
    return txt[:m.end()] + addition + txt[m.end():], True

# ── Pattern G: goTo() navigation — renderModuleQuiz/selMCQ style ─────────────
# These files have no per-module pass/fail; completion fires on first
# navigation away from each module screen.

PATTERN_G_DETECT = r'function goTo\s*\(\s*dest\s*\)'
PATTERN_G_BODY   = re.compile(
    r'(function goTo\s*\(\s*dest\s*\)\s*\{)\s*'
    r"(document\.querySelectorAll\s*\(\s*['\"]\.screen['\"])"
)

def extract_mhti_titles(txt):
    """Extract titles from <div class="mhti"> within each module screen."""
    titles = {}
    for m in re.finditer(r'<div class="screen"[^>]*id="screen-(m\d+)"', txt):
        mid = m.group(1)
        # Find mhti div after this screen start
        rest = txt[m.start():]
        t = re.search(r'class="mhti">([^<]+)<', rest)
        if t:
            title = re.sub(r'[^\x00-\x7F]+', '', t.group(1)).strip(' -–:')
            titles[mid] = title
    return titles

def handle_pattern_g(txt, titles_var, passing=70):
    mods = sorted(set(re.findall(r'\b(m\d+)\s*:', re.search(r'var pm\s*=\s*\{([^}]+)\}', txt).group(1))))
    m = PATTERN_G_BODY.search(txt)
    if not m:
        return txt, False
    mods_js  = '[' + ','.join(f"'{k}'" for k in mods) + ']'
    inject = (
        f'\n  var _cur=document.querySelector(".screen.active");'
        f'var _cid=_cur?_cur.id.replace("screen-",""):"";'
        f'var _ml={mods_js};'
        f'if(_ml.indexOf(_cid)>=0&&!modsDone.has(_cid)){{'
        f'modsDone.add(_cid);var _ix=_ml.indexOf(_cid);'
        f'reportModuleComplete({{moduleIndex:_ix,moduleTitle:{titles_var}[_cid],'
        f'score:1,maxScore:1,passingScore:{passing},'
        f'totalModules:_ml.length,completedModules:modsDone.size}});}}\n  '
    )
    insert_pos = m.start(2)
    return txt[:insert_pos] + inject + txt[insert_pos:], True

# ── Helper: inject function definition before anchor ─────────────────────────

def inject_function_before(txt, anchor_pattern):
    m = re.search(anchor_pattern, txt)
    if not m:
        return txt, False
    pos = m.start()
    return txt[:pos] + FUNCTION_BODY + '\n      ' + txt[pos:], True

# ── Main ──────────────────────────────────────────────────────────────────────

html_files = [f for f in os.listdir(FOLDER) if f.lower().endswith('.html')]
html_files.sort()

done_count = skip_count = manual_count = 0

print(f"\nScanning {len(html_files)} HTML files in: {FOLDER}\n")

for fname in html_files:
    path = os.path.join(FOLDER, fname)
    with open(path, encoding='utf-8') as fh:
        txt = fh.read()

    if already_done(txt):
        print(f"  SKIP (already done)  {fname}")
        skip_count += 1
        continue

    modified   = False
    safe_name  = re.sub(r'[^a-zA-Z0-9]', '_', fname.replace('.html', ''))[:18]
    titles_var = safe_name + 'ModTitles'
    ids_var    = safe_name + 'ModIds'

    # --- Detect pattern and apply ----

    if re.search(PATTERN_A_DETECT, txt):
        # Extract titles from moduleText if available
        mt = re.search(r'const moduleText\s*=\s*\{([^}]+)\}', txt)
        if mt:
            # Build titles from first sentence of each entry
            titles = {}
            for km in re.finditer(r'"(m\d+)"\s*:\s*"([^"]+)"', mt.group(1)):
                mid   = km.group(1)
                title = km.group(2).split('.')[0].strip()
                titles[mid] = title
        else:
            titles = extract_module_titles_from_html(txt)

        if not titles:
            print(f"  MANUAL NEEDED        {fname}  (Pattern A — could not extract module titles)")
            manual_count += 1
            continue

        # Inject titles lookup + function before ans()
        titles_js = build_titles_dict_js(titles, titles_var)
        # Insert after moduleText block or before function ans(
        txt = re.sub(r'(const moduleText\s*=\s*\{[^}]+\};)', r'\1\n      ' + titles_js, txt, count=1)
        if titles_var not in txt:
            txt, _ = inject_function_before(txt, PATTERN_A_DETECT)
        txt, _ = inject_function_before(txt, PATTERN_A_DETECT)

        # Passing score — check submitFinal for threshold
        passing = 80
        pm = re.search(r'p\s*>=\s*(\d+)', txt)
        if pm:
            passing = int(pm.group(1))

        txt, modified = handle_pattern_a(txt, titles_var, ids_var, passing)

    elif re.search(PATTERN_E_DETECT, txt):
        # missions[] pattern (Advanced Oil Tanker style)
        txt, _ = inject_function_before(txt, PATTERN_E_DETECT)
        txt, modified = handle_pattern_e(txt)

    elif re.search(PATTERN_D_DETECT, txt):
        # completeModule(n) — numeric modules
        titles = extract_module_titles_from_html(txt)
        titles_js = build_titles_dict_js({k: v for k, v in titles.items()}, titles_var)
        txt = re.sub(r'(window\.courseState\s*=\s*\{)', titles_js + '\n' + r'\1', txt, count=1)
        if titles_var not in txt:
            txt = FUNCTION_BODY + '\n' + txt
        txt, _ = inject_function_before(txt, PATTERN_D_DETECT)
        txt, modified = handle_pattern_d(txt, titles_var)

    elif re.search(PATTERN_F_DETECT, txt):
        # quizPick() — COLREGS/Radar style
        txt, _ = inject_function_before(txt, PATTERN_F_DETECT)
        txt, modified = handle_pattern_f(txt)

    elif re.search(PATTERN_G_DETECT, txt) and re.search(r'function renderModuleQuiz', txt):
        # goTo()/renderModuleQuiz/selMCQ — completion fires on navigation away from module
        titles = extract_mhti_titles(txt)
        if not titles:
            print(f"  MANUAL NEEDED        {fname}  (goTo/renderModuleQuiz — could not extract mhti titles)")
            manual_count += 1
            continue

        titles_js = build_titles_dict_js(titles, titles_var)
        # Inject: modsDone + titles dict + function before goTo
        txt, _ = inject_function_before(txt, PATTERN_G_DETECT)
        # Add modsDone var and titles dict just before reportModuleComplete function
        txt = txt.replace(
            FUNCTION_BODY,
            f'var modsDone=new Set();\n{titles_js}\n{FUNCTION_BODY}',
            1
        )
        txt, modified = handle_pattern_g(txt, titles_var)

    elif re.search(PATTERN_B_DETECT, txt):
        # completeAndGo() — most common
        titles = extract_module_titles_from_html(txt)
        if not titles:
            print(f"  MANUAL NEEDED        {fname}  (completeAndGo — no module titles found in HTML)")
            manual_count += 1
            continue

        titles_js = build_titles_dict_js(titles, titles_var)
        ids_js    = build_ids_array_js(titles, ids_var)
        state_anchor = 'window.courseState = {' if 'window.courseState = {' in txt else 'const courseState = {'
        txt = txt.replace(state_anchor, titles_js + '\n        ' + ids_js + '\n        ' + state_anchor, 1)

        # Inject function before completeAndGo
        txt, _ = inject_function_before(txt, PATTERN_B_DETECT)

        # Determine passing score from submitAssessment
        passing = 70
        pm = re.search(r'(?:score|pct|percentage)\s*>=\s*(\d+)', txt)
        if pm:
            passing = int(pm.group(1))

        txt, modified = handle_pattern_b(txt, titles_var, ids_var, passing)

    else:
        print(f"  MANUAL NEEDED        {fname}  (no recognised module-completion pattern)")
        manual_count += 1
        continue

    if modified:
        shutil.copy2(path, path + '.bak')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(txt)
        print(f"  DONE                 {fname}")
        done_count += 1
    else:
        print(f"  MANUAL NEEDED        {fname}  (pattern detected but injection point not found)")
        manual_count += 1

print(f"\n{'='*55}")
print(f"  Modified  : {done_count}")
print(f"  Skipped   : {skip_count}  (already had reportModuleComplete)")
print(f"  Manual    : {manual_count}  (check these manually)")
print(f"{'='*55}\n")
