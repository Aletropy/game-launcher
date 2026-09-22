"""Feature tests, one module per area.

``tests/smoke.py`` imports every ``test_*.py`` module here and hands it
the same helpers it uses itself (``test``, ``qt_app``, ``sandbox``,
``pump``), so the suite still runs with one command and nothing here
can touch the real library. Keep tests dependency-free and headless.
"""
