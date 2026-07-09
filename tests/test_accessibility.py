"""
tests/test_accessibility.py — Garde-fou de non-régression accessibilité (C14).

Vérifie mécaniquement, sur templates/index.html, les correctifs RGAA
appliqués (labels liés, zones aria-live, rôles d'onglets). Ne remplace pas
un audit manuel/outillé (contraste, navigation clavier réelle) — c'est un
filet de sécurité contre une régression future, pas une preuve de
conformité complète.
"""

import os
import re

import pytest

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "index.html",
)


@pytest.fixture(scope="module")
def html():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


LABEL_RE = re.compile(r"<label\b[^>]*>", re.IGNORECASE)
FOR_RE   = re.compile(r'\bfor\s*=\s*"', re.IGNORECASE)

LIVE_REGION_IDS = [
    "login-err", "manual-res", "ocr-res", "nc-res",
    "c-prevs", "e-prevs", "clis-list", "cd-list", "cd-prevs", "api-endpoints",
    "e-audit",
]

TAB_IDS = ["dash", "prevs", "clis", "cliDash", "api", "audit"]


class TestLabels:

    def test_toutes_les_balises_label_statiques_sont_liees(self, html):
        """Chaque <label> présent tel quel dans le template a un attribut for=."""
        unbound = [tag for tag in LABEL_RE.findall(html) if not FOR_RE.search(tag)]
        assert not unbound, f"Labels non liés à un input : {unbound}"

    def test_labels_generes_en_js_ont_un_for_coherent(self, html):
        """Les labels construits en template string JS (mf-, __pp__, __qp__) restent liés."""
        assert 'for="mf-${f.k}"' in html
        assert 'for="${id}__pp__${p.name}"' in html
        assert 'for="${id}__qp__${p.name}"' in html


class TestLiveRegions:

    @pytest.mark.parametrize("elem_id", LIVE_REGION_IDS)
    def test_conteneur_dynamique_a_aria_live(self, html, elem_id):
        match = re.search(rf'id="{re.escape(elem_id)}"[^>]*>', html)
        assert match, f"Conteneur #{elem_id} introuvable"
        assert "aria-live" in match.group(0), f"#{elem_id} n'a pas aria-live"


class TestTabs:

    def test_nav_a_un_role_tablist(self, html):
        assert 'id="expert-tabs"' in html
        nav_tag = re.search(r'<nav id="expert-tabs"[^>]*>', html).group(0)
        assert 'role="tablist"' in nav_tag

    def test_boutons_onglets_ont_role_tab(self, html):
        tab_buttons = re.findall(r'<button[^>]*data-tab="[a-zA-Z]+"[^>]*>', html)
        assert len(tab_buttons) == len(TAB_IDS)
        for btn in tab_buttons:
            assert 'role="tab"' in btn
            assert "aria-selected" in btn

    def test_panneaux_ont_role_tabpanel(self, html):
        for tab_id in TAB_IDS:
            match = re.search(rf'id="tab-{re.escape(tab_id)}"[^>]*>', html)
            assert match, f"Panneau tab-{tab_id} introuvable"
            assert 'role="tabpanel"' in match.group(0)

    def test_showtab_met_a_jour_aria_selected(self, html):
        assert "setAttribute('aria-selected'" in html


class TestKeyboardTraps:

    def test_ligne_client_dashboard_accessible_au_clavier(self, html):
        assert "cd-cli-row" in html
        block = html[html.index("cd-cli-row"):html.index("cd-cli-row") + 400]
        assert 'role="button"' in block
        assert 'tabindex="0"' in block
        assert "onkeydown" in block

    def test_expandeur_api_explorer_accessible_au_clavier(self, html):
        idx = html.index("toggleApiEp('${id}')")
        block = html[idx:idx + 300]
        assert 'role="button"' in block
        assert 'tabindex="0"' in block
        assert "onkeydown" in block


class TestHeading:

    def test_h1_present_a_la_fois_sur_le_login_et_dans_l_application(self, html):
        """Un <h1> existait déjà sur l'écran de connexion ; il doit aussi en exister
        un dans la vue application (absent avant correctif — un seul <h1> total)."""
        assert len(re.findall(r"<h1\b", html)) >= 2
