"""
api/app.py — Factory Flask VigiEau
"""

import os
import logging
from flask import Flask
from flasgger import Swagger
from prometheus_client import CollectorRegistry
from prometheus_flask_exporter import PrometheusMetrics
from api.models.db     import init_db
from api.routes.routes import bp

# Racine du projet (parent du dossier api/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs",
}


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(_ROOT, "templates"),
        static_folder=os.path.join(_ROOT, "static"),
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    init_db()

    app.register_blueprint(bp)

    # Monitorage applicatif (C20) : expose GET /metrics au format texte
    # Prometheus — requêtes par route/méthode/code retour, latence en
    # histogramme. Monitoring de MODÈLE distinct (MLflow, C11) — pas le
    # même périmètre, voir docs/doc_technique_e5.md.
    #
    # Registre dédié (pas le registre global par défaut) : create_app()
    # est appelée plusieurs fois dans le même processus (une fois par
    # fichier de test qui importe l'app) — avec le registre global,
    # PrometheusMetrics lève "Duplicated timeseries in CollectorRegistry"
    # dès le deuxième appel (trouvé en lançant la suite complète, pas en
    # relisant le code — voir tests/test_app_factory.py).
    metrics = PrometheusMetrics(app, group_by="endpoint", registry=CollectorRegistry())
    metrics.info("vigieau_app_info", "VigiEau — informations application", version="1.0.0")

    swagger_path = os.path.join(_ROOT, "swagger.yaml")
    Swagger(app, config=SWAGGER_CONFIG, template_file=swagger_path)

    return app
