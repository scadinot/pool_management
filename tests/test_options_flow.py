"""Tests de l'options flow, et notamment de ses champs optionnels d'entité.

Ces champs — traitement secondaire, pompe à chaleur et son capteur de
puissance — doivent pouvoir rester vides. Le piège est que ``vol.Optional``
assorti d'un ``default`` ne se contente pas de proposer une valeur : il
injecte la clé absente puis la valide. Un ``default`` à ``None`` fait donc
échouer le sélecteur d'entité sur ``Entity None is neither a valid entity
ID nor a valid UUID``, et le champ optionnel devient obligatoire.

Le pattern correct est ``description={"suggested_value": ...}``, qui
pré-remplit sans rien injecter.
"""

import io
import json

import pytest
import voluptuous as vol

from custom_components.pool_management.options_flow import (
    PoolManagementOptionsFlowHandler,
)

# Les sept entités que l'écran exige ou accepte hors PAC.
ENTITES_SANS_PAC = {
    "temperatureWater": "sensor.temperature_eau",
    "temperatureOutdoor": "sensor.temperature_air",
    "leverSoleil": "sensor.sun_next_rising",
    "filtration": "switch.filtration",
    "traitement": "switch.traitement_chlore",
    "traitement_2": "switch.traitement_ph",
    "surpresseur": "switch.surpresseur",
}


def _handler(options: dict) -> PoolManagementOptionsFlowHandler:
    """Construit un handler prêt à afficher un formulaire.

    ``flow_id`` et ``handler`` sont normalement posés par le gestionnaire
    de flow de Home Assistant ; on les fournit pour pouvoir appeler les
    étapes isolément.
    """

    handler = PoolManagementOptionsFlowHandler()
    handler.flow_id = "test-flow"
    handler.handler = "pool_management"
    handler.options = dict(options)
    return handler


async def _schema_de_l_ecran(options: dict) -> vol.Schema:
    """Retourne le schéma du formulaire des entités."""

    resultat = await _handler(options).async_step_user()
    return resultat["data_schema"]


@pytest.mark.bugs
async def test_sans_pac_le_formulaire_est_validable():
    """Sans pompe à chaleur, l'écran doit pouvoir être validé.

    Régression : ``heatPump`` déclaré avec ``default=None`` rendait le
    champ impossible à laisser vide, bloquant tout utilisateur sans PAC.
    """

    schema = await _schema_de_l_ecran(ENTITES_SANS_PAC)

    valide = schema(dict(ENTITES_SANS_PAC))

    assert "heatPump" not in valide
    assert "heatPumpPower" not in valide


@pytest.mark.bugs
async def test_sans_second_traitement_le_formulaire_est_validable():
    """Même piège sur ``traitement_2`` pour une installation à un seul relais."""

    entites = {
        cle: valeur
        for cle, valeur in ENTITES_SANS_PAC.items()
        if cle != "traitement_2"
    }

    schema = await _schema_de_l_ecran(entites)

    valide = schema(dict(entites))

    assert "traitement_2" not in valide


async def test_les_valeurs_existantes_sont_proposees():
    """Un champ optionnel déjà renseigné est pré-rempli, sans être imposé."""

    options = {**ENTITES_SANS_PAC, "heatPump": "switch.pac"}

    schema = await _schema_de_l_ecran(options)

    suggestions = {
        cle.schema: cle.description["suggested_value"]
        for cle in schema.schema
        if getattr(cle, "description", None)
    }
    assert suggestions["heatPump"] == "switch.pac"
    assert suggestions["traitement_2"] == "switch.traitement_ph"


async def test_les_champs_requis_le_restent():
    """Le correctif ne doit pas rendre facultatif ce qui ne l'est pas.

    On inspecte les marqueurs plutôt que de soumettre un formulaire
    incomplet : les champs requis portent un ``default``, que voluptuous
    injecte quand la clé manque. Une validation ne lèverait donc pas, et
    le test passerait quel que soit le marqueur.
    """

    schema = await _schema_de_l_ecran(ENTITES_SANS_PAC)
    marqueurs = {cle.schema: type(cle) for cle in schema.schema}

    for champ in (
        "temperatureWater",
        "temperatureOutdoor",
        "leverSoleil",
        "filtration",
        "traitement",
        "surpresseur",
    ):
        assert marqueurs[champ] is vol.Required, champ

    for champ in ("traitement_2", "heatPump", "heatPumpPower"):
        assert marqueurs[champ] is vol.Optional, champ


async def test_vider_un_champ_optionnel_l_efface():
    """Un champ vidé disparaît des options.

    Un champ laissé vide est absent des données soumises ; ``update`` ne
    supprimant rien, la valeur précédente survivrait sans retrait
    explicite — et le champ serait impossible à effacer une fois rempli.
    """

    handler = _handler({**ENTITES_SANS_PAC, "heatPump": "switch.pac"})

    await handler.async_step_user(dict(ENTITES_SANS_PAC))

    assert "heatPump" not in handler.options


async def test_un_champ_optionnel_renseigne_est_conserve():
    """À l'inverse, une valeur soumise est bien enregistrée."""

    handler = _handler(ENTITES_SANS_PAC)

    await handler.async_step_user(
        {**ENTITES_SANS_PAC, "heatPump": "climate.pac"}
    )

    assert handler.options["heatPump"] == "climate.pac"


async def test_les_autres_options_sont_preservees():
    """Soumettre l'écran des entités ne touche pas aux réglages des menus."""

    handler = _handler({**ENTITES_SANS_PAC, "sondeLocalTechnique": True})

    await handler.async_step_user(dict(ENTITES_SANS_PAC))

    assert handler.options["sondeLocalTechnique"] is True
# ---------------------------------------------------------------------------
# Plancher de la plage d'hivernage
#
# « Temps de filtration minimum » figurait dans le menu Filtration, où son
# libellé annonçait un plancher saisonnier. La saison n'en a jamais appliqué
# aucun : le réglage était déclaré dans le bloc hivernage du YAML d'origine
# et n'a jamais eu qu'un seul consommateur, la durée calculée en hivernage.
# Il siège donc désormais dans le menu Hivernage, sous un nom qui le dit.
# ---------------------------------------------------------------------------

LIBELLES = (
    "custom_components/pool_management/strings.json",
    "custom_components/pool_management/translations/fr.json",
    "custom_components/pool_management/translations/en.json",
)


def _libelles(chemin: str) -> dict:
    """Retourne les libellés de champs d'un fichier de traduction."""

    with io.open(chemin, encoding="utf-8") as fichier:
        contenu = json.load(fichier)

    return contenu["options"]["step"]


async def _schema(etape: str, options: dict) -> vol.Schema:
    """Retourne le schéma du formulaire d'un menu."""

    handler = _handler(options)
    resultat = await getattr(handler, f"async_step_{etape}")()
    return resultat["data_schema"]


def _defauts(schema: vol.Schema) -> dict:
    """Retourne les valeurs par défaut portées par les marqueurs du schéma."""

    return {
        cle.schema: cle.default()
        for cle in schema.schema
        if getattr(cle, "default", None) is not None
    }


async def test_le_plancher_est_propose_dans_le_menu_hivernage():
    """Le menu Hivernage expose le plancher de la plage."""

    schema = await _schema("hivernage", {})

    assert "tempsDeFiltrationMinimumHivernage" in _defauts(schema)


async def test_le_plancher_ne_figure_plus_dans_le_menu_filtration():
    """Le menu Filtration ne propose plus de plancher.

    La saison n'en applique aucun : le laisser là entretenait l'idée d'un
    réglage saisonnier sans effet sur la saison.
    """

    schema = await _schema("filtration", {})

    assert "tempsDeFiltrationMinimum" not in _defauts(schema)


async def test_le_formulaire_propose_la_valeur_deja_enregistree():
    """Une installation en place ouvre le menu sur son plancher actuel.

    Le champ est pré-rempli avec la valeur héritée de l'ancien nom, pour que
    l'utilisateur voie le plancher qui s'applique vraiment chez lui et ne le
    change pas sans le savoir en validant l'écran.
    """

    schema = await _schema("hivernage", {"tempsDeFiltrationMinimum": 6})

    assert _defauts(schema)["tempsDeFiltrationMinimumHivernage"] == 6


async def test_valider_le_menu_retire_l_ancienne_cle():
    """Le réglage migre une fois pour toutes, sans doublon.

    Deux clés portant le même sens finiraient par diverger : seule la
    nouvelle est conservée dès que l'écran est validé.
    """

    handler = _handler({"tempsDeFiltrationMinimum": 6})

    await handler.async_step_hivernage({"tempsDeFiltrationMinimumHivernage": 6})

    assert handler.options["tempsDeFiltrationMinimumHivernage"] == 6
    assert "tempsDeFiltrationMinimum" not in handler.options


def test_les_trois_fichiers_de_libelles_portent_le_nouveau_champ():
    """Un champ sans libellé dans les trois fichiers affiche sa clé brute."""

    for chemin in LIBELLES:
        etapes = _libelles(chemin)

        assert (
            "tempsDeFiltrationMinimumHivernage" in etapes["hivernage"]["data"]
        ), chemin
        assert (
            "tempsDeFiltrationMinimum" not in etapes["filtration"]["data"]
        ), chemin
