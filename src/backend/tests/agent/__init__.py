"""US4 Person B tests: the routing graph, its nodes, budgets and prompt boundary.

This package exists so the suite can share `conftest.ScriptedModel` through a
relative import and so the modules cannot collide with same-named files elsewhere
in the suite. No test here needs a network connection, an API key, or PostgreSQL.
"""
