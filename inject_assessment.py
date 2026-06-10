"""
inject_assessment.py
--------------------
Automatically injects reportAssessment (COURSE_ASSESSMENT_COMPLETE postMessage)
into HTML gamification files.

Handles these patterns:
  A) submitFinal()  — Pattern A files with mids[] (minified or formatted)
  B) submitAssessment() with courseState.assessmentScore
  C) submitA() — complex timed-assessment files (18 questions / 75%)
  D) submitAssess() — MARPOL Annex 5 style

Usage:
  python inject_assessment.py                  # processes all .html in current dir
  python inject_assessment.py path/to/folder   # processes folder
"""

import os, re, shutil, sys

FOLDER = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

FUNCTION_BODY = (
    'function reportAssessment({score,maxScore,passingScore}){'
    'const percentage=Math.round((score/maxScore)*100);'
    'const message={type:"COURSE_ASSESSMENT_COMPLETE",source:"course",'
    'payload:{score,maxScore,percentage,status:percentage>=passingScore?"passed":"failed"}};'
    'if(window.parent&&window.parent!==window){window.parent.postMessage(message,"*");}}'
)

def already_done(txt):
    return 'reportAssessment' in txt

def inject_function_near(txt, anchor_pattern, fn_body):
    """Insert fn_body on a new line before the first match of anchor_pattern."""
    m = re.search(anchor_pattern, txt)
    if not m:
        return txt, False
    insert_at = m.start()
    return txt[:insert_at] + fn_body + '\n      ' + txt[insert_at:], True

# ── Pattern A: submitFinal() with mids[] ─────────────────────────────────────
# Detects:  if(p>=80){mids.forEach(m=>state.done[m]=true);state.xp+=50;save();}
# Adds guard + call before cert scroll, fixes save() placement.

PATTERN_A_DETECT   = r'function submitFinal\('
PATTERN_A_OLD      = re.compile(
    r'(if\s*\(\s*p\s*>=\s*80\s*\)\s*\{[^}]*mids\.forEach[^}]*state\.xp\s*\+=\s*50\s*;?\s*save\s*\(\s*\)\s*;\s*\})'
    r'(\s*document\.getElementById\([\'"](cert|score)[\'"]\))',
    re.DOTALL
)
PATTERN_A_OLD_MIN  = re.compile(
    r"(if\(p>=80\)\{mids\.forEach\(m=>state\.done\[m\]=true\);state\.xp\+=50;save\(\);\})",
)

def handle_pattern_a(txt, fname, guard_var):
    """submitFinal() — minified or formatted."""
    # Try minified first
    m = PATTERN_A_OLD_MIN.search(txt)
    if m:
        replacement = (
            "if(p>=80){mids.forEach(m=>state.done[m]=true);state.xp+=50;}"
            f"if(!state.{guard_var}){{state.{guard_var}=true;"
            "reportAssessment({score:c,maxScore:10,passingScore:80});}}"
            "save();"
        )
        txt = txt[:m.start()] + replacement + txt[m.end():]
        return txt, True

    # Try formatted
    m = PATTERN_A_OLD.search(txt)
    if m:
        block     = m.group(1)
        after     = m.group(2)
        new_block = (
            block
            .replace('save();', '')
            .rstrip()
            .rstrip('}')
            .rstrip()
            + '}\n        '
            + f'if (!state.{guard_var}) {{\n          state.{guard_var} = true;\n'
            + '          reportAssessment({ score: c, maxScore: 10, passingScore: 80 });\n'
            + '        }\n        save();'
        )
        txt = txt[:m.start()] + new_block + after + txt[m.end():]
        return txt, True

    return txt, False

# ── Pattern B: submitAssessment() with courseState.assessmentScore ───────────
PATTERN_B_DETECT = r'function submitAssessment\('
PATTERN_B_SCORE  = re.compile(
    r'(courseState\.assessmentScore\s*=\s*\w+\s*;)'
    r'(\s*courseState\.assessmentPassed\s*=\s*[^;]+;)?',
    re.DOTALL
)

def handle_pattern_b(txt, guard_var, score_var, max_expr, passing):
    m = PATTERN_B_SCORE.search(txt)
    if not m:
        return txt, False
    insert_after = m.end()
    guard_code = (
        f'\n            if (!courseState.{guard_var}) {{'
        f' courseState.{guard_var} = true;'
        f' reportAssessment({{score: {score_var}, maxScore: {max_expr}, passingScore: {passing}}}); }}'
    )
    txt = txt[:insert_after] + guard_code + txt[insert_after:]
    return txt, True

def detect_b_params(txt):
    """Extract score variable, maxScore expression, passing threshold."""
    # score variable: const score = Math.round(...)  OR  const pct = Math.round(...)
    m = re.search(r'const\s+(score|pct|percentage)\s*=\s*Math\.round\(\((\w+)\s*/\s*([^)]+)\)', txt)
    if not m:
        return None
    score_name = m.group(2)           # raw correct count
    max_expr   = m.group(3).strip()   # e.g. assessmentQuestions.length
    # passing threshold
    p = re.search(r'(?:score|pct|percentage)\s*>=\s*(\d+)', txt)
    passing = p.group(1) if p else '70'
    return score_name, max_expr, passing

# ── Pattern C: submitA() — complex timed files (18q 75%) ─────────────────────
PATTERN_C_DETECT = r'function submitA\s*\('
PATTERN_C_END    = re.compile(
    r"(if\s*\(passed\)\s*document\.getElementById\(['\"]cert['\"].*?\.className\s*=\s*['\"]cert show['\"];)"
    r"\s*(\n\s*panel\.scrollIntoView)",
    re.DOTALL
)

def handle_pattern_c(txt, guard_var):
    m = PATTERN_C_END.search(txt)
    if not m:
        return txt, False
    insert_at = m.start(2)
    guard_code = (
        f'\n  if(!{guard_var}){{{guard_var}=true;'
        'reportAssessment({score:correct,maxScore:18,passingScore:75});}}'
    )
    txt = txt[:insert_at] + guard_code + txt[insert_at:]
    return txt, True

# ── Pattern D: submitAssess() — MARPOL Annex 5 style ─────────────────────────
PATTERN_D_DETECT = r'function submitAssess\s*\('

def handle_pattern_d(txt, guard_var, max_expr, passing):
    # Find: if(pct>=80){  or similar near assessment result display
    m = re.search(r"(let\s+r\s*=\s*document\.getElementById\(['\"](result|results)['\"])", txt)
    if not m:
        return txt, False
    # inject guard just before the result display
    insert_at = m.start()
    guard_code = (
        f'if(!state.{guard_var}){{state.{guard_var}=true;'
        f'reportAssessment({{score,maxScore:{max_expr},passingScore:{passing}}})}}\n'
    )
    txt = txt[:insert_at] + guard_code + txt[insert_at:]
    return txt, True

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

    modified = False
    guard_var = fname.replace(' ', '_').replace('.html', '').replace('&', 'and')[:20] + 'AssessReported'
    guard_var = re.sub(r'[^a-zA-Z0-9_]', '_', guard_var)

    # --- Inject function definition ---
    # Place it just before the detected submit function
    if re.search(PATTERN_A_DETECT, txt):
        fn_anchor = r'function submitFinal\('
        txt, injected = inject_function_near(txt, fn_anchor, FUNCTION_BODY)
        if injected:
            txt, modified = handle_pattern_a(txt, fname, guard_var)

    elif re.search(PATTERN_B_DETECT, txt):
        fn_anchor = r'function submitAssessment\('
        txt, _ = inject_function_near(txt, fn_anchor, FUNCTION_BODY)
        params = detect_b_params(txt)
        if params:
            score_var, max_expr, passing = params
            # Also add guard var declaration if courseState exists
            if 'courseState' in txt:
                guard_var = 'assessmentReported'
            txt, modified = handle_pattern_b(txt, guard_var, score_var, max_expr, passing)
        else:
            print(f"  MANUAL NEEDED        {fname}  (submitAssessment — could not detect score vars)")
            manual_count += 1
            continue

    elif re.search(PATTERN_C_DETECT, txt):
        # Add var declaration near existing assessAnswers var
        txt = re.sub(
            r'(var assessAnswers\s*=\s*\{\}\s*,?\s*assessTimer[^;]+;)',
            r'\1\nvar ' + guard_var + '=false;\n' + FUNCTION_BODY,
            txt, count=1
        )
        txt, modified = handle_pattern_c(txt, guard_var)

    elif re.search(PATTERN_D_DETECT, txt):
        fn_anchor = r'function submitAssess\s*\('
        txt, _ = inject_function_near(txt, fn_anchor, FUNCTION_BODY)
        m = re.search(r'score\s*/\s*([\w.]+\.\w+)', txt)
        max_expr = m.group(1) if m else 'assessQuestions.length'
        p = re.search(r'pct\s*>=\s*(\d+)', txt)
        passing = p.group(1) if p else '80'
        guard_var2 = 'assessmentReported'
        txt = txt.replace(
            'let state={',
            f'let state={{',
            1
        )
        txt, modified = handle_pattern_d(txt, guard_var2, max_expr, passing)

    else:
        print(f"  MANUAL NEEDED        {fname}  (no recognised assessment pattern)")
        manual_count += 1
        continue

    if modified:
        shutil.copy2(path, path + '.bak')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(txt)
        print(f"  DONE                 {fname}")
        done_count += 1
    else:
        print(f"  MANUAL NEEDED        {fname}  (pattern detected but injection failed)")
        manual_count += 1

print(f"\n{'='*55}")
print(f"  Modified  : {done_count}")
print(f"  Skipped   : {skip_count}  (already had reportAssessment)")
print(f"  Manual    : {manual_count}  (check these manually)")
print(f"{'='*55}\n")
