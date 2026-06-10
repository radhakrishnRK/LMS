"""
check_postmessage.py
--------------------
Audits all HTML files to verify COURSE_MODULE_COMPLETE and
COURSE_ASSESSMENT_COMPLETE postMessage implementations are correct.

Checks for each file:
  MODULE   — reportModuleComplete function defined, correct type/source/postMessage,
             called with all required args, guard against re-send
  ASSESS   — reportAssessment function defined, correct type/source/postMessage,
             called with required args, guard against re-send

Usage:
  python check_postmessage.py                   # checks all .html in current dir
  python check_postmessage.py path/to/folder    # checks folder
  python check_postmessage.py --verbose         # show per-check detail
"""

import os, re, sys

FOLDER  = "."
VERBOSE = False

for arg in sys.argv[1:]:
    if arg == "--verbose":
        VERBOSE = True
    elif not arg.startswith("-"):
        FOLDER = arg

if FOLDER == ".":
    FOLDER = os.path.dirname(os.path.abspath(__file__))

# ── Check helpers ─────────────────────────────────────────────────────────────

def check_module(txt):
    """Return list of (check_name, passed, detail) for module postMessage."""
    issues = []

    def chk(name, condition, detail=""):
        issues.append((name, bool(condition), detail))

    # 1. Function defined
    has_def = bool(re.search(r'function reportModuleComplete\s*\(', txt))
    chk("fn_defined", has_def, "reportModuleComplete not found")

    if not has_def:
        return issues  # rest won't pass anyway

    # 2. Correct message type
    chk("msg_type",
        'COURSE_MODULE_COMPLETE' in txt,
        'type "COURSE_MODULE_COMPLETE" missing')

    # 3. source field
    chk("source_field",
        re.search(r'source\s*:\s*["\']course["\']', txt),
        'source:"course" missing')

    # 4. postMessage call
    chk("postmessage",
        re.search(r'window\.parent\.postMessage\s*\(', txt),
        'window.parent.postMessage not called')

    # 5. parent-window guard
    chk("parent_guard",
        re.search(r'window\.parent\s*&&\s*window\.parent\s*!==\s*window', txt),
        'parent-window guard (window.parent && window.parent !== window) missing')

    # 6. allModulesComplete field present
    chk("all_modules_complete_field",
        'allModulesComplete' in txt,
        'allModulesComplete field missing from payload')

    # 7. Call site present
    chk("call_site",
        bool(re.search(r'reportModuleComplete\s*\(\s*\{', txt)),
        'reportModuleComplete({...}) never called')

    # 8. Call site includes all required params
    call_m = re.search(r'reportModuleComplete\s*\(\s*\{([^}]+)\}', txt, re.DOTALL)
    if call_m:
        args_txt = call_m.group(1)
        required = ['moduleIndex', 'moduleTitle', 'score', 'maxScore',
                    'passingScore', 'totalModules', 'completedModules']
        missing = [a for a in required if a not in args_txt]
        chk("call_args", not missing,
            f'call missing args: {missing}' if missing else "")
    else:
        chk("call_args", False, "no call site to inspect")

    # 9. once-only guard (state.done / .includes / guard var / boolean array / Set)
    has_guard = bool(
        re.search(r'state\.done\[', txt) or
        re.search(r'modulesCompleted\.includes\(', txt) or
        re.search(r'state\.completed\.includes\(', txt) or
        re.search(r'Reported\s*=\s*true', txt) or
        re.search(r'state\.\w*[Pp]ass\[', txt) or   # e.g. state.actpass[i], state.qpass[i]
        re.search(r'modsDone\.(has|add)\(', txt) or  # Pattern G Set guard
        re.search(r'!\s*state\.\w+\[\w+\]\s*&&', txt)  # generic boolean array guard
    )
    chk("once_guard", has_guard,
        "no once-only guard found (state.done / .includes / Reported flag / boolean array)")

    return issues


def check_assessment(txt):
    """Return list of (check_name, passed, detail) for assessment postMessage."""
    issues = []

    def chk(name, condition, detail=""):
        issues.append((name, bool(condition), detail))

    # Determine if this file likely has a final assessment
    has_submit = bool(re.search(
        r'function\s+(?:submitFinal|submitAssessment|submitA|submitAssess)\s*\(', txt))

    if not has_submit:
        # Mark as N/A — these courses have no final assessment
        issues.append(("no_assessment", None, "no final-assessment function found — N/A"))
        return issues

    # 1. Function defined
    has_def = bool(re.search(r'function reportAssessment\s*\(', txt))
    chk("fn_defined", has_def, "reportAssessment not found")

    if not has_def:
        return issues

    # 2. Correct message type
    chk("msg_type",
        'COURSE_ASSESSMENT_COMPLETE' in txt,
        'type "COURSE_ASSESSMENT_COMPLETE" missing')

    # 3. source field
    chk("source_field",
        re.search(r'source\s*:\s*["\']course["\']', txt),
        'source:"course" missing')

    # 4. postMessage call
    chk("postmessage",
        re.search(r'window\.parent\.postMessage\s*\(', txt),
        'window.parent.postMessage not called')

    # 5. parent-window guard
    chk("parent_guard",
        re.search(r'window\.parent\s*&&\s*window\.parent\s*!==\s*window', txt),
        'parent-window guard missing')

    # 6. Call site present
    chk("call_site",
        bool(re.search(r'reportAssessment\s*\(\s*\{', txt)),
        'reportAssessment({...}) never called')

    # 7. Call site includes all required params
    call_m = re.search(r'reportAssessment\s*\(\s*\{([^}]+)\}', txt, re.DOTALL)
    if call_m:
        args_txt = call_m.group(1)
        required = ['score', 'maxScore', 'passingScore']
        missing = [a for a in required if a not in args_txt]
        chk("call_args", not missing,
            f'call missing args: {missing}' if missing else "")
    else:
        chk("call_args", False, "no call site to inspect")

    # 8. Once-only guard
    has_guard = bool(re.search(r'Reported\s*[=:]\s*(?:true|false)', txt))
    chk("once_guard", has_guard,
        "no once-only guard variable found (e.g. assessmentReported = true)")

    return issues


def summarise(checks):
    """Return (status, failures) where status is 'PASS'/'FAIL'/'N/A'."""
    if not checks:
        return "FAIL", ["no checks ran"]
    # N/A
    if len(checks) == 1 and checks[0][1] is None:
        return "N/A", []
    failures = [detail for (_, passed, detail) in checks if passed is False and detail]
    status = "PASS" if not failures else "FAIL"
    return status, failures


# ── Main ──────────────────────────────────────────────────────────────────────

html_files = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith('.html'))

pass_count  = 0
fail_count  = 0
na_count    = 0

COL = 48  # filename column width

print(f"\nAuditing {len(html_files)} HTML files in: {FOLDER}\n")
print(f"{'File':<{COL}}  {'MODULE':<8}  {'ASSESS':<8}")
print("-" * (COL + 22))

results = []

for fname in html_files:
    path = os.path.join(FOLDER, fname)
    with open(path, encoding='utf-8') as fh:
        txt = fh.read()

    mod_checks  = check_module(txt)
    asn_checks  = check_assessment(txt)

    mod_status,  mod_fails  = summarise(mod_checks)
    asn_status,  asn_fails  = summarise(asn_checks)

    overall = (
        "PASS" if mod_status == "PASS" and asn_status in ("PASS", "N/A")
        else "FAIL"
    )

    if overall == "PASS":
        pass_count += 1
        tag = "+"
    else:
        fail_count += 1
        tag = "!"

    short = fname if len(fname) <= COL else fname[:COL-1] + "…"
    print(f"{tag} {short:<{COL-2}}  {mod_status:<8}  {asn_status:<8}")

    if VERBOSE or overall == "FAIL":
        for detail in mod_fails:
            print(f"      [MODULE]  {detail}")
        for detail in asn_fails:
            print(f"      [ASSESS]  {detail}")

    results.append((fname, mod_status, asn_status, mod_fails, asn_fails))

print("-" * (COL + 22))
print(f"\n  PASS : {pass_count}")
print(f"  FAIL : {fail_count}")
print(f"\n  (N/A on ASSESS means the file has no final-assessment function)\n")

if fail_count:
    print("Files needing attention:")
    for fname, ms, as_, mf, af in results:
        if ms == "FAIL" or as_ == "FAIL":
            print(f"  {fname}")
            for d in mf:
                print(f"    [MODULE] {d}")
            for d in af:
                print(f"    [ASSESS] {d}")
    print()
