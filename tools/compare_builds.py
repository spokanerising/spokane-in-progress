"""Compares two projects.json files, ignoring the build time.

  python3 tools/compare_builds.py old/projects.json projects.json

Prints what differs, project by project. Exits 1 if anything does.
Used to check that moving the sheet into data/projects/ changed nothing.
"""
import json, sys


def load(path):
    data = json.load(open(path, encoding="utf-8"))
    data.pop("builtAt", None)
    return data


def main(a_path, b_path):
    a, b = load(a_path), load(b_path)
    problems = []
    if a.get("stages") != b.get("stages"):
        problems.append("stages differ")
    pa = {p["id"]: p for p in a.get("projects", [])}
    pb = {p["id"]: p for p in b.get("projects", [])}
    for pid in sorted(set(pa) - set(pb)):
        problems.append(f"only in {a_path}: {pid}")
    for pid in sorted(set(pb) - set(pa)):
        problems.append(f"only in {b_path}: {pid}")
    for pid in sorted(set(pa) & set(pb)):
        for key in sorted(set(pa[pid]) | set(pb[pid])):
            if pa[pid].get(key) != pb[pid].get(key):
                problems.append(f"{pid}.{key}: {json.dumps(pa[pid].get(key))[:200]} -> "
                                f"{json.dumps(pb[pid].get(key))[:200]}")
    order_a = [p["id"] for p in a.get("projects", [])]
    order_b = [p["id"] for p in b.get("projects", [])]
    if not problems and order_a != order_b:
        problems.append("same projects, different order")
    print(f"{len(pa)} projects vs {len(pb)} projects.")
    if problems:
        print(f"{len(problems)} difference(s):")
        for line in problems:
            print("  -", line)
        return 1
    print("Identical apart from the build time.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
