"""pytest runs ONLY the pure unit tests (services/ rules, no database).

DocType integration tests need a site, so they run through Frappe's own runner:
    bench --site fleeto.localhost run-tests --app sas_forcex_fleeto

_dev/ holds local helper scripts (git-excluded); never collect them.
"""

collect_ignore_glob = [
    "sas_forcex_fleeto/forcex_fleeto/doctype/*/test_*.py",
    "sas_forcex_fleeto/forcex_fleeto/integrations/test_*.py",
    "_dev/*",
]
