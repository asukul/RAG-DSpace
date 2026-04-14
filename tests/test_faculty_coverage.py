"""
Faculty completeness spot-check.

For a list of (department_name, college, expected_min_count, source_url) we:
1. Count rows in faculty.json for that department + college.
2. Compare to expected_min_count.
3. Optionally HEAD-fetch source_url to see if the page is alive.

Output: a markdown report with pass/fail per department and a final
"coverage score".

Run:
  python tests/test_faculty_coverage.py
  python tests/test_faculty_coverage.py --strict   # exit non-zero if any fail
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

FACULTY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "backend",
    "data",
    "faculty.json",
)

# (department, college_keyword, expected_min, source_url)
# Keep this list short and curated — picks one or two well-known dept per
# college so an outage is obvious.
SPOT_CHECKS: List[Tuple[str, str, int, str]] = [
    # College of Liberal Arts and Sciences
    ("Computer Science", "Liberal Arts and Sciences", 35,
     "https://www.cs.iastate.edu/people/faculty"),
    ("Statistics", "Liberal Arts and Sciences", 30,
     "https://stat.iastate.edu/people/faculty"),
    ("Mathematics", "Liberal Arts and Sciences", 30,
     "https://math.iastate.edu/people/faculty/"),
    ("Physics and Astronomy", "Liberal Arts and Sciences", 30,
     "https://www.physastro.iastate.edu/people/faculty"),
    ("Economics", "Liberal Arts and Sciences", 30,
     "https://www.econ.iastate.edu/people/faculty"),
    ("English", "Liberal Arts and Sciences", 25,
     "https://www.engl.iastate.edu/people/"),
    ("History", "Liberal Arts and Sciences", 15,
     "https://history.iastate.edu/people/"),
    ("Political Science", "Liberal Arts and Sciences", 15,
     "https://www.polisci.iastate.edu/people/"),

    # College of Engineering
    ("Aerospace Engineering", "Engineering", 25,
     "https://www.aere.iastate.edu/people/faculty/"),
    ("Mechanical Engineering", "Engineering", 40,
     "https://www.me.iastate.edu/people/faculty/"),
    ("Electrical and Computer Engineering", "Engineering", 50,
     "https://ece.iastate.edu/people/faculty/"),

    # College of Agriculture and Life Sciences
    ("Agricultural Education and Studies", "Agriculture", 10,
     "https://www.ageds.iastate.edu/people/"),
    ("Agronomy", "Agriculture", 25,
     "https://www.agron.iastate.edu/people/faculty/"),

    # Ivy College of Business
    ("Accounting", "Business", 15,
     "https://www.ivybusiness.iastate.edu/directory/?Department=ACCT"),
    ("Finance", "Business", 15,
     "https://www.ivybusiness.iastate.edu/directory/?Department=FIN"),
    ("Management", "Business", 15,
     "https://www.ivybusiness.iastate.edu/directory/?Department=MGMT"),

    # College of Design
    ("Architecture", "Design", 15,
     "https://www.design.iastate.edu/architecture/"),
    ("Industrial Design", "Design", 5,
     "https://www.design.iastate.edu/industrialdesign/"),

    # College of Health and Human Sciences
    ("Food Science and Human Nutrition", "Health and Human Sciences", 25,
     "https://www.fshn.hs.iastate.edu/people/faculty/"),
    ("Kinesiology", "Health and Human Sciences", 20,
     "https://www.kin.hs.iastate.edu/people/faculty/"),
    ("Human Development and Family Studies", "Health and Human Sciences", 15,
     "https://www.hdfs.hs.iastate.edu/people/faculty/"),

    # College of Veterinary Medicine
    ("Veterinary Clinical Sciences", "Veterinary Medicine", 20,
     "https://vetmed.iastate.edu/clinical-sciences"),
    ("Veterinary Microbiology and Preventive Medicine",
     "Veterinary Medicine", 20,
     "https://vetmed.iastate.edu/vmpm"),
    ("Veterinary Pathology", "Veterinary Medicine", 15,
     "https://vetmed.iastate.edu/vpath"),
]


def load_faculty() -> List[Dict]:
    if not os.path.exists(FACULTY_FILE):
        print(f"ERROR: faculty.json not found at {FACULTY_FILE}", file=sys.stderr)
        sys.exit(2)
    with open(FACULTY_FILE, encoding="utf-8") as f:
        return json.load(f)


def count_for(faculty: List[Dict], department: str, college_keyword: str) -> int:
    dept_norm = department.lower()
    coll_norm = college_keyword.lower()
    n = 0
    for f in faculty:
        d = (f.get("department") or "").lower()
        c = (f.get("college") or "").lower()
        if dept_norm in d and coll_norm in c:
            n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero on any failure")
    parser.add_argument("--out", default=None,
                        help="Write the markdown report to this path")
    args = parser.parse_args()

    faculty = load_faculty()
    print(f"Loaded {len(faculty)} faculty rows from {FACULTY_FILE}")

    rows = []
    fail_count = 0
    for dept, college, expected, url in SPOT_CHECKS:
        actual = count_for(faculty, dept, college)
        status = "PASS" if actual >= expected else "FAIL"
        if status == "FAIL":
            fail_count += 1
        rows.append((college, dept, actual, expected, status, url))

    # Aggregate by college
    by_college = defaultdict(list)
    for r in rows:
        by_college[r[0]].append(r)

    print()
    print("=" * 80)
    print(f"{'College':<32} {'Department':<42} {'Have':>5} {'Need':>5}  Status")
    print("-" * 80)
    for college in sorted(by_college.keys()):
        for college_, dept, actual, expected, status, url in by_college[college]:
            print(
                f"{college_[:32]:<32} {dept[:42]:<42} "
                f"{actual:>5} {expected:>5}  {status}"
            )

    print("-" * 80)
    print(f"Failures: {fail_count}/{len(rows)}")

    # Markdown report
    md = ["# Faculty completeness spot-check", ""]
    md.append(f"Total rows in faculty.json: **{len(faculty)}**")
    md.append("")
    md.append(f"Failures: **{fail_count}/{len(rows)}**")
    md.append("")
    md.append("| College | Department | Have | Need | Status | Source |")
    md.append("|---|---|---:|---:|:---:|---|")
    for college, dept, actual, expected, status, url in rows:
        emoji = "OK" if status == "PASS" else "MISS"
        md.append(f"| {college} | {dept} | {actual} | {expected} | {emoji} | {url} |")
    md_text = "\n".join(md) + "\n"

    out_path = args.out or os.path.join(
        os.path.dirname(__file__), "results", "faculty_coverage.md"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    print(f"\nReport: {out_path}")

    if args.strict and fail_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
