"""One-time setup: builds MATLAB's Engine API for Python into this project's venv.

Why this exists: matlab.engine is NOT a normal installable PyPI package — it ships
bundled inside your MATLAB installation (in extern/engines/python), and its own
setup.py resolves the MATLAB bin/win64 directory via a path RELATIVE TO ITS OWN
LOCATION. That means it must be built while running from inside the real MATLAB
install folder — building it from a copied location fails with
"The installation of MATLAB is corrupted" even though nothing is actually wrong.

This script automates the exact steps: locate MATLAB, build from its real
location (writing build output to a writable temp dir, since MATLAB's own
install folder is normally read-only), then install into this venv.

Run this:
  - After a fresh `uv sync` / fresh clone, if you want MATLAB support.
  - After `.venv` is deleted and recreated.
  - After upgrading MATLAB to a new release (the engine binary is version-locked
    to the exact MATLAB release it ships with).

Usage:
    uv run python setup_matlab_engine.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def find_matlab_engine_dir() -> Path | None:
    matlab_exe = shutil.which("matlab")
    if not matlab_exe:
        return None
    # matlab.exe lives at <MATLABROOT>/bin/matlab.exe (or bin/win64/matlab.exe on
    # some installs) — the engine sources are at <MATLABROOT>/extern/engines/python.
    matlab_bin = Path(matlab_exe).resolve().parent
    matlab_root = matlab_bin.parent if matlab_bin.name.lower() != "bin" else matlab_bin.parent
    candidate = matlab_root / "extern" / "engines" / "python"
    if candidate.exists():
        return candidate
    # Handle the bin/win64/matlab.exe layout.
    candidate2 = matlab_bin.parent.parent / "extern" / "engines" / "python"
    return candidate2 if candidate2.exists() else None


def main() -> int:
    engine_dir = find_matlab_engine_dir()
    if engine_dir is None:
        print("MATLAB installation not found on PATH (or its extern/engines/python "
              "folder is missing) — skipping MATLAB engine setup. The app still "
              "works fine for Python/NLP; MATLAB execution just won't be available.")
        return 0

    print(f"Found MATLAB engine sources at: {engine_dir}")

    with tempfile.TemporaryDirectory(prefix="matlab_engine_build_") as build_dir:
        cmd = [
            sys.executable, "setup.py",
            "build", "--build-base", build_dir,
            "install",
        ]
        print("Building and installing (this can take a minute)...")
        result = subprocess.run(cmd, cwd=str(engine_dir), check=False,
                                 capture_output=True, text=True)
        output = result.stdout + result.stderr

        # The final "egg_info" step fails because it tries to write metadata back
        # into MATLAB's own (read-only) install folder — the actual package files
        # are already fully installed into the venv by that point, so this
        # specific failure is expected and safe to ignore.
        if "could not create" in output and "egg-info" in output:
            print("(egg-info metadata step failed as expected — package files "
                  "were already installed successfully before that point.)")
        elif result.returncode != 0:
            print("Build/install failed:")
            print(output[-3000:])
            return 1

    try:
        subprocess.run(
            [sys.executable, "-c", "import matlab.engine; print('matlab.engine OK:', matlab.engine.__file__)"],
            check=True,
        )
    except subprocess.CalledProcessError:
        print("Install finished but `import matlab.engine` still fails — check the output above.")
        return 1

    print("MATLAB engine setup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
