"""LeanGate shared implementation."""


def main() -> None:
    # Lazy import avoids a circular import during normal `leangate.core` use.
    from pathlib import Path
    import runpy

    runpy.run_path(str(Path(__file__).resolve().parents[1] / "leangate.py"),
                   run_name="__main__")
