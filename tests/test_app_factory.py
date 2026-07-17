"""
tests/test_app_factory.py — Régression C21 : create_app() doit rester
appelable plusieurs fois dans le même processus.

Bug réel rencontré en développant le monitorage Prometheus (C20) : chaque
fichier de test qui fait `from api.app import create_app; app =
create_app()` déclenche une nouvelle instrumentation Prometheus. Comme
`prometheus_flask_exporter.PrometheusMetrics` enregistre ses métriques
dans le registre global `prometheus_client.REGISTRY` par défaut, le
DEUXIÈME appel à `create_app()` dans le même processus pytest levait
`ValueError: Duplicated timeseries in CollectorRegistry` — 61 tests en
échec d'un coup dans `tests/test_non_regression.py`, pas un crash
silencieux.

Fix : un `CollectorRegistry()` neuf à chaque appel de `create_app()`
plutôt que le registre global partagé (`api/app.py`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.app import create_app


def test_create_app_appelable_plusieurs_fois_sans_collision():
    """
    Reproduit exactement le scénario qui plantait : deux instances d'app
    créées dans le même processus (comme quand pytest importe plusieurs
    fichiers de test qui appellent chacun create_app()).
    """
    app1 = create_app()
    app2 = create_app()   # levait ValueError avant le fix
    assert app1 is not app2

    client2 = app2.test_client()
    resp = client2.get("/metrics")
    assert resp.status_code == 200
    assert b"flask_http_request_total" in resp.data or b"# HELP" in resp.data


def test_create_app_trois_fois_de_suite():
    # Marge de sécurité au-delà du cas à 2 instances ci-dessus
    for _ in range(3):
        create_app()
