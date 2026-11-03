"""
Marks `tests/` as a package.

Python 3.11 removed namespace-package support from `unittest discover`, so
without this file `python -m unittest discover -s tests` raises
"Start directory is not importable" when the start dir differs from the
top-level dir. pytest does not need it, but keeping it makes both runners work.
"""
