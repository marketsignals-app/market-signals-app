"""The publish gate: python tools/verify_build.py BUILD_FOLDER. Exits 1 (so the site is not published) only when the build is not intact: manifest, hashes, valid JSON, required files.
The QA sweep is printed as a report. Its findings are data-quality notes about records carried over from older builds; they must not stop alerts and state from being saved."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import manifest  # noqa: E402


def main(folder):
    problems = manifest.verify(folder)
    for problem in problems:
        print("FAIL", problem)
    subprocess.run([sys.executable, str(Path(__file__).with_name("qa_sweep.py")), folder])      # a report: its result does not block publishing
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else 2)
