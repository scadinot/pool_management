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
# Choix de l'heure de reference de la plage d'hivernage
#
# Ce reglage valait 1 (lever du soleil) ou 2 (heure fixe), saisis dans un
# champ numerique nu : rien a l'ecran ne disait ce que valaient 1 et 2. Il
# s'affiche desormais en liste deroulante.
#
# Le piege, et la raison pour laquelle ces tests couvrent le trajet complet
# du formulaire jusqu'au controleur : un selecteur HA renvoie une CHAINE,
# alors que hivernage.py compare ``self.choixHeureFiltrationHivernage == 1``.
# "1" == 1 vaut False en Python, donc une liste deroulante posee sans
# conversion basculerait silencieusement tout le monde sur l'heure fixe.
# ---------------------------------------------------------------------------


async def _schema_hivernage(options: dict) -> vol.Schema:
    """Retourne le schema du formulaire d'hivernage."""

    resultat = await _handler(options).async_step_hivernage()
    return resultat["data_schema"]


def _champ(schema: vol.Schema, nom: str):
    """Retourne le couple (marqueur, validateur) du champ nomme."""

    for cle in schema.schema:
        if cle.schema == nom:
            return cle, schema.schema[cle]

    raise AssertionError(f"champ {nom} absent du schema")


@pytest.mark.bugs
async def test_le_choix_de_l_heure_hivernage_est_une_liste():
    """Le reglage s'affiche en liste deroulante, pas en champ numerique.

    Un entier nu n'indiquait nulle part que 1 valait « lever du soleil » et
    2 « heure fixe » : le reglage etait indevinable sans lire le README.
    """

    schema = await _schema_hivernage({})
    _, validateur = _champ(schema, "choixHeureFiltrationHivernage")

    assert getattr(validateur, "selector_type", None) == "select", (
        "le champ doit etre un selecteur de type select, pas %r" % (validateur,)
    )
    assert list(validateur.config["options"]) == ["1", "2"]
    assert validateur.config["mode"] == "dropdown"
    assert (
        validateur.config["translation_key"] == "choix_heure_filtration_hivernage"
    ), "les libelles doivent venir des traductions, pas du code"


async def test_le_choix_de_l_heure_hivernage_propose_la_valeur_en_cours():
    """La valeur enregistree preselectionne la bonne entree de la liste.

    Les options d'un selecteur sont des chaines : un entier 2 ne
    correspondrait a aucune entree et la liste s'ouvrirait vide.
    """

    schema = await _schema_hivernage({"choixHeureFiltrationHivernage": 2})
    cle, _ = _champ(schema, "choixHeureFiltrationHivernage")

    assert cle.default() == "2"


@pytest.mark.bugs
async def test_choisir_le_lever_du_soleil_stocke_un_entier():
    """Le choix du lever du soleil doit etre stocke en entier.

    C'est le cas critique : hivernage.py compare la valeur a l'entier 1.
    Une chaine "1" rendue telle quelle par le selecteur ne correspondrait
    pas, et la plage se calerait sur l'heure fixe alors que l'utilisateur a
    choisi le lever du soleil.
    """

    handler = _handler({})

    await handler.async_step_hivernage(
        {
            "choixHeureFiltrationHivernage": "1",
            "distributionDatePivotHivernage": "4",
        }
    )

    valeur = handler.options["choixHeureFiltrationHivernage"]

    assert valeur == 1
    assert isinstance(valeur, int) and not isinstance(valeur, bool), (
        "la valeur doit etre un entier, obtenu %r" % (valeur,)
    )


async def test_choisir_l_heure_fixe_stocke_un_entier():
    """Le choix de l'heure fixe est stocke en entier lui aussi."""

    handler = _handler({})

    await handler.async_step_hivernage(
        {
            "choixHeureFiltrationHivernage": "2",
            "distributionDatePivotHivernage": "4",
        }
    )

    valeur = handler.options["choixHeureFiltrationHivernage"]

    assert valeur == 2
    assert isinstance(valeur, int)


def _controleur(config: dict):
    """Construit un controleur reel sur une configuration minimale."""

    from unittest.mock import MagicMock

    from custom_components.pool_management.controller import PoolController

    return PoolController(MagicMock(), config)


@pytest.mark.bugs
def test_le_controleur_accepte_une_valeur_stockee_en_chaine():
    """Une valeur deja stockee en chaine doit redevenir un entier.

    Une entree configuree par une version intermediaire, ou editee a la
    main dans .storage, peut porter "1" : sans conversion, la comparaison
    a 1 echouerait et le lever du soleil serait ignore.
    """

    controleur = _controleur({"choixHeureFiltrationHivernage": "1"})

    assert controleur.choixHeureFiltrationHivernage == 1


def test_le_controleur_replie_une_valeur_invalide_sur_le_lever_du_soleil():
    """Une valeur hors 1-2 revient au lever du soleil, pas a l'heure fixe.

    La comparaison ``== 1`` faisait basculer sur l'heure fixe tout ce qui
    n'etait pas exactement 1, y compris 0, 7 ou None, sans rien signaler.
    Le lever du soleil est le choix recommande pour le hors-gel : c'est le
    repli sur.
    """

    for valeur in (0, 7, None, "", "abc"):
        controleur = _controleur({"choixHeureFiltrationHivernage": valeur})

        assert controleur.choixHeureFiltrationHivernage == 1, (
            "valeur %r" % (valeur,)
        )


def test_les_libelles_du_choix_existent_en_francais_et_en_anglais():
    """Les trois fichiers de libelles portent la liste et son aide.

    Ajouter la section selector a strings.json en oubliant fr.json ou
    en.json laisserait la liste afficher ses valeurs brutes, 1 et 2, ce qui
    annulerait tout le benefice du changement.
    """

    import json
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent / "custom_components" / "pool_management"

    fichiers = [
        racine / "strings.json",
        racine / "translations" / "fr.json",
        racine / "translations" / "en.json",
    ]

    for fichier in fichiers:
        contenu = json.loads(fichier.read_text(encoding="utf-8"))

        options = contenu["selector"]["choix_heure_filtration_hivernage"]["options"]

        assert set(options) == {"1", "2"}, fichier.name
        assert all(libelle.strip() for libelle in options.values()), fichier.name

        aide = contenu["options"]["step"]["hivernage"]["data_description"]

        assert aide["choixHeureFiltrationHivernage"].strip(), fichier.name
@pytest.mark.bugs
async def test_la_saisie_traverse_la_validation_du_schema():
    """Le trajet reel : Home Assistant valide par le schema, puis appelle l'etape.

    Les tests ci-dessus appellent l'etape directement et sautent donc la
    validation du schema, qui est precisement le maillon ou le defaut des
    champs optionnels s'etait produit. On rejoue ici la sequence complete.
    """

    handler = _handler({})
    resultat = await handler.async_step_hivernage()
    schema = resultat["data_schema"]

    # Ce que soumet le frontend quand l'utilisateur choisit « lever du soleil »
    valide = schema(
        {
            "choixHeureFiltrationHivernage": "1",
            "distributionDatePivotHivernage": "4",
        }
    )

    await handler.async_step_hivernage(valide)

    assert handler.options["choixHeureFiltrationHivernage"] == 1
    assert isinstance(handler.options["choixHeureFiltrationHivernage"], int)


async def test_le_schema_refuse_une_valeur_hors_liste():
    """Une valeur absente de la liste est rejetee avant d'atteindre l'etape.

    C'est l'interet d'un selecteur sur un champ entier libre : l'interface
    ne peut plus produire une valeur que le code devrait deviner.
    """

    schema = await _schema_hivernage({})

    with pytest.raises(vol.Invalid):
        schema(
            {
                "choixHeureFiltrationHivernage": "9",
                "distributionDatePivotHivernage": "4",
            }
        )
