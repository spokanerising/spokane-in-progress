"""Runs every test file in this folder and stops at the first failure.
  python3 tests/run.py            all of them
  python3 tests/run.py filters    just the ones whose name contains "filters"
"""
import glob, os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
pick = sys.argv[1] if len(sys.argv) > 1 else ""
failed = []
for path in sorted(glob.glob(os.path.join(here, "test_*.py"))):
    if pick not in os.path.basename(path):
        continue
    start = time.time()
    result = subprocess.run([sys.executable, path], capture_output=True, text=True)
    last = (result.stdout.strip().splitlines() or [""])[-1]
    status = "ok  " if result.returncode == 0 else "FAIL"
    print(f"{status} {os.path.basename(path):24s} {time.time() - start:5.1f}s  {last}")
    if result.returncode:
        print(result.stdout[-2000:], result.stderr[-4000:], sep="\n")
        failed.append(path)
sys.exit(1 if failed else 0)
