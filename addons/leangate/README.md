# LeanGate

LeanGate is the optional Lean 4 formal-verification addon for AutoMCM-Pro.
It is disabled by default. The checked-in core uses exact integers and Lean's
standard library; solver-specific floating-point output must be converted by an
explicit, recorded scaling/rounding policy before it becomes a certificate.

Run `python scripts/leangate.py doctor` from the repository, or initialize a
contest workspace with `python scripts/leangate.py init --policy selected`.
