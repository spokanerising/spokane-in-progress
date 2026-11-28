"""Runs every test file in this folder, several at a time, and reports each.
  python3 tests/run.py            all of them
  python3 tests/run.py filters    just the ones whose name contains "filters"
  TEST_WORKERS=1 python3 tests/run.py   one at a time

Each file works in its own temporary copy of the site, so they can run side
by side. The slowest start first, so the run ends sooner (issue #41: GitHub's
machines have 4 processors, and one at a time the suite took ~3 minutes).
"""
import glob, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

here = os.path.dirname(os.path.abspath(__file__))
pick = sys.argv[1] if len(sys.argv) > 1 else ""
workers = int(os.environ.get("TEST_WORKERS") or min(4, os.cpu_count() or 1))
SLOW_FIRST = ["test_accessibility.py", "test_filters.py", "test_map_image.py", "test_info_pages.py",
              "test_editor.py", "test_share_download.py", "test_map_tools.py", "test_chart_images.py"]

paths = [p for p in sorted(glob.glob(os.path.join(here, "test_*.py"))) if pick in os.path.basename(p)]
paths.sort(key=lambda p: SLOW_FIRST.index(os.path.basename(p)) if os.path.basename(p) in SLOW_FIRST else len(SLOW_FIRST))


def run(path):
    start = time.time()
    result = subprocess.run([sys.executable, path], capture_output=True, text=True)
    return path, result, time.time() - start


began = time.time()
failed = []
with ThreadPoolExecutor(max_workers=workers) as pool:
    for future in as_completed([pool.submit(run, p) for p in paths]):
        path, result, took = future.result()
        last = (result.stdout.strip().splitlines() or [""])[-1]
        status = "ok  " if result.returncode == 0 else "FAIL"
        print(f"{status} {os.path.basename(path):26s} {took:5.1f}s  {last}", flush=True)
        if result.returncode:
            failed.append((path, result))

for path, result in failed:
    print(f"\n==== {os.path.basename(path)}", result.stdout[-2000:], result.stderr[-4000:], sep="\n")
print(f"\n{len(paths) - len(failed)} of {len(paths)} files passed in {time.time() - began:.0f}s ({workers} at a time).")
sys.exit(1 if failed else 0)
