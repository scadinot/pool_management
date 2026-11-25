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

from custom_components.pool_management.controller import BORNES_NOMBRES
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
@pytest.mark.bugs
async def test_une_valeur_invalide_deja_enregistree_n_empeche_pas_le_formulaire():
    """Une valeur hors liste deja enregistree ne doit pas bloquer l'ecran.

    L'ancien champ numerique etait libre : une entree peut donc porter 0,
    7, ou tout autre entier saisi a la main. Rendu tel quel en defaut du
    formulaire, ce nombre ne correspond a aucune entree de la liste, qui
    s'ouvre alors sans choix valide. Et si le champ est omis a la
    soumission, ``vol.Optional`` injecte ce defaut puis le selecteur le
    rejette -- avant que la validation de l'etape ait pu le corriger, donc
    sans que l'utilisateur puisse enregistrer quoi que ce soit.

    Le controleur, lui, repliait bien sur 1, mais dans son seul etat
    interne : la valeur enregistree restait invalide.
    """

    schema = await _schema_hivernage({"choixHeureFiltrationHivernage": 7})
    cle, _ = _champ(schema, "choixHeureFiltrationHivernage")

    assert cle.default() == "1", (
        "le defaut propose doit etre une entree de la liste, obtenu %r"
        % (cle.default(),)
    )

    # Champ omis a la soumission : vol.Optional injecte le defaut, que le
    # selecteur doit accepter sous peine de bloquer l'enregistrement.
    valide = schema({"distributionDatePivotHivernage": "4"})

    assert valide["choixHeureFiltrationHivernage"] == "1"


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


# ---------------------------------------------------------------------------
# Horaires pivot : du texte libre consommé par ``strptime``
#
# « Horaire pivot » et « Horaire pivot hivernage » sont des champs texte sans
# validation. Leur valeur finit dans ``pivotTimestamp``, qui appelle
# ``datetime.strptime(pivot, "%H:%M")`` : « 13h00 », « 25:00 » ou un champ
# vidé lèvent une exception. Rien ne l'attrape — ni le flow, ni le cron qui
# calcule la plage chaque minute. La saisie était donc acceptée, puis plus
# aucune plage n'était calculée et le journal prenait une erreur par minute.
# ---------------------------------------------------------------------------

HORAIRES_INVALIDES = ("13h00", "25:00", "12:60", "", "   ", "1:00 PM", None, 13)


async def test_un_horaire_pivot_invalide_est_remplace_a_la_soumission():
    """Le menu Filtration remplace un horaire illisible par 13:00.

    L'écran ne signale rien : la valeur est corrigée en silence, et
    seul le journal garde la trace de la saisie refusée.
    """

    for valeur in HORAIRES_INVALIDES:
        handler = _handler({})

        await handler.async_step_filtration({"datePivot": valeur})

        assert handler.options["datePivot"] == "13:00", f"valeur {valeur!r}"


async def test_un_horaire_pivot_hivernage_invalide_est_remplace():
    """Le menu Hivernage procède de même et garde 06:00.

    L'horaire fixe d'hivernage ne sert que si « Heure fixe » est choisi,
    mais il est enregistré dans tous les cas : une saisie fautive dort
    jusqu'au jour où l'utilisateur quitte le lever du soleil.
    """

    for valeur in HORAIRES_INVALIDES:
        handler = _handler({})

        await handler.async_step_hivernage({"datePivotHivernage": valeur})

        assert (
            handler.options["datePivotHivernage"] == "06:00"
        ), f"valeur {valeur!r}"


async def test_un_horaire_valide_est_conserve_et_normalise():
    """Les écritures acceptables sont ramenées au format attendu.

    ``strptime`` lit « 9:05 » mais refuse « 13:00:00 », que rendrait un
    selecteur d'heure de Home Assistant : la normalisation permet de
    changer de champ un jour sans casser le calcul.
    """

    attendu = {
        "08:30": "08:30",
        "9:05": "09:05",
        "13:00:00": "13:00",
        " 07:15 ": "07:15",
        "00:00": "00:00",
        "23:59": "23:59",
    }

    for saisi, normalise in attendu.items():
        handler = _handler({})

        await handler.async_step_filtration({"datePivot": saisi})

        assert handler.options["datePivot"] == normalise, f"saisi {saisi!r}"


async def test_une_saisie_illisible_ne_perd_pas_l_horaire_en_place():
    """Le repli est l'horaire déjà enregistré, pas le défaut du paquet.

    Un utilisateur réglé sur 14:30 qui tape « 15h00 » garderait sinon une
    plage centrée sur 13:00, qu'il n'a peut-être jamais choisie.
    """

    handler = _handler({"datePivot": "14:30"})

    await handler.async_step_filtration({"datePivot": "15h00"})

    assert handler.options["datePivot"] == "14:30"


async def test_le_formulaire_ne_propose_jamais_un_horaire_illisible():
    """Une entrée qui porte déjà un horaire fautif s'ouvre sur le défaut.

    ``vol.Optional`` injecte son défaut quand le champ est omis : un défaut
    invalide se réenregistrerait tel quel, écran après écran.
    """

    formulaire = await _schema("filtration", {"datePivot": "25:00"})
    assert _defauts(formulaire)["datePivot"] == "13:00"

    formulaire = await _schema("hivernage", {"datePivotHivernage": "nuit"})
    assert _defauts(formulaire)["datePivotHivernage"] == "06:00"


def test_le_controleur_assainit_un_horaire_deja_enregistre():
    """Une entrée enregistrée avant cette version ne doit pas casser le cron.

    La validation du formulaire ne protège que les saisies à venir ; une
    valeur fautive déjà dans ``.storage`` n'est corrigée que par cette
    lecture défensive.
    """

    controleur = _controleur({"datePivot": "13h00", "datePivotHivernage": ""})

    assert controleur.datePivot == "13:00"
    assert controleur.datePivotHivernage == "06:00"


def test_le_calcul_de_la_plage_ne_leve_plus_sur_un_horaire_invalide():
    """C'est le cron, chaque minute, qui payait l'absence de validation."""

    from custom_components.pool_management.utils import pivotTimestamp

    for valeur in HORAIRES_INVALIDES:
        controleur = _controleur(
            {"datePivot": valeur, "datePivotHivernage": valeur}
        )

        assert isinstance(
            pivotTimestamp(controleur.datePivot, False), float
        ), f"valeur {valeur!r}"
        assert isinstance(
            pivotTimestamp(controleur.datePivotHivernage, False), float
        ), f"valeur {valeur!r}"


# ---------------------------------------------------------------------------
# « Méthode de calcul » : des libellés codés en dur, donc jamais traduits
# ---------------------------------------------------------------------------


async def test_la_methode_de_calcul_tire_ses_libelles_des_traductions():
    """La liste doit porter une ``translation_key``, pas ses propres libellés.

    Les deux choix étaient écrits en français dans le code : une interface
    en anglais affichait « Courbe de température ».
    """

    _, selecteur = _champ(await _schema("filtration", {}), "methodeCalcul")

    config = selecteur.config

    assert config.get("translation_key") == "methode_calcul"
    assert config["options"] == ["1", "2"]


def test_les_trois_fichiers_portent_les_libelles_de_la_methode_de_calcul():
    """Sans les trois fichiers, la liste afficherait ses valeurs brutes."""

    for chemin in LIBELLES:
        with open(chemin, encoding="utf-8") as fichier:
            contenu = json.load(fichier)

        options = contenu["selector"]["methode_calcul"]["options"]

        assert set(options) == {"1", "2"}, chemin
        assert all(libelle.strip() for libelle in options.values()), chemin


# ---------------------------------------------------------------------------
# Champs numériques : des entiers nus, donc sans bornes
#
# Huit réglages se saisissaient dans un champ libre : rien n'empêchait une
# durée négative, un plancher de 99 h ou un seuil hors-gel de 400 °C. Les
# coefficients d'ajustement, eux, passaient déjà par un sélecteur borné.
#
# Borner un champ déjà en service demande une précaution : ``vol.Optional``
# réinjecte son défaut dès que le champ est omis à la soumission, et un
# défaut hors bornes serait alors refusé par le sélecteur — l'écran
# deviendrait impossible à valider, comme l'avait montré la liste
# déroulante de l'hivernage. La valeur enregistrée est donc ramenée dans
# ses bornes avant d'être proposée.
# ---------------------------------------------------------------------------

#: Les champs numériques bornés, par menu qui les expose.
MENUS_NOMBRES = {
    "filtration": ("pausePivot",),
    "hivernage": (
        "tempsDeFiltrationMinimumHivernage",
        "temperatureSecurite",
        "temperatureHysteresis",
    ),
    "avance": (
        "sondeLocalTechniquePause",
        "surpresseurDuree",
        "lavageDuree",
        "rincageDuree",
    ),
}


async def test_les_champs_numeriques_portent_leurs_bornes():
    """Chaque champ doit exposer un sélecteur borné, non un entier nu."""

    for etape, cles in MENUS_NOMBRES.items():
        schema = await _schema(etape, {})

        for cle in cles:
            _, validateur = _champ(schema, cle)

            config = getattr(validateur, "config", None)

            assert config is not None, f"{cle} : champ non borné"

            minimum, maximum, _defaut = BORNES_NOMBRES[cle]

            assert config["min"] == minimum, cle
            assert config["max"] == maximum, cle


def test_aucune_duree_ne_peut_etre_negative():
    """Le défaut que cette correction visait : des durées négatives.

    Les maxima restent larges — il s'agit d'écarter l'absurde, pas de
    dicter une installation.
    """

    durees = (
        "pausePivot",
        "sondeLocalTechniquePause",
        "surpresseurDuree",
        "lavageDuree",
        "rincageDuree",
        "tempsDeFiltrationMinimumHivernage",
    )

    for cle in durees:
        minimum, maximum, _defaut = BORNES_NOMBRES[cle]

        assert minimum == 0, cle
        assert maximum > 0, cle


async def test_une_saisie_hors_bornes_est_refusee_par_le_formulaire():
    """Contrairement aux horaires, le sélecteur refuse la valeur à l'écran.

    C'est tout l'intérêt de borner le champ plutôt que de corriger après
    coup : l'utilisateur voit son erreur au lieu de la découvrir au
    journal.
    """

    schema = await _schema("avance", {})

    with pytest.raises(vol.Invalid):
        schema({"surpresseurDuree": -5})

    with pytest.raises(vol.Invalid):
        schema({"lavageDuree": 10000})


async def test_une_valeur_deja_hors_bornes_laisse_l_ecran_validable():
    """Une installation en place ne doit pas se retrouver bloquée.

    ``vol.Optional`` réinjecte son défaut quand le champ est omis : un
    défaut hors bornes serait refusé par le sélecteur, et l'écran ne
    pourrait plus être enregistré du tout.
    """

    schema = await _schema("avance", {"surpresseurDuree": 500})

    assert _defauts(schema)["surpresseurDuree"] == BORNES_NOMBRES["surpresseurDuree"][1]

    schema({})


def test_le_controleur_ramene_les_nombres_dans_leurs_bornes():
    """Une valeur fautive déjà enregistrée est rattrapée à la relecture."""

    controleur = _controleur(
        {
            "surpresseurDuree": -5,
            "pausePivot": 10000,
            "temperatureHysteresis": "abc",
            "temperatureSecurite": -400,
        }
    )

    assert controleur.surpresseurDuree == 0
    assert controleur.pausePivot == BORNES_NOMBRES["pausePivot"][1]
    assert controleur.temperatureHysteresis == 0.5
    assert controleur.temperatureSecurite == BORNES_NOMBRES["temperatureSecurite"][0]


def test_le_plancher_herite_de_l_ancienne_cle_reste_borne():
    """La reprise de l'ancien nom passe par les mêmes bornes.

    Une valeur plausible est conservée telle quelle ; une valeur absurde
    héritée de l'ancien champ libre est ramenée au maximum.
    """

    controleur = _controleur({"tempsDeFiltrationMinimum": 6})

    assert controleur.tempsDeFiltrationMinimumHivernage == 6

    maximum = BORNES_NOMBRES["tempsDeFiltrationMinimumHivernage"][1]
    controleur = _controleur({"tempsDeFiltrationMinimum": 99})

    assert controleur.tempsDeFiltrationMinimumHivernage == maximum


async def test_le_formulaire_et_le_controleur_partagent_les_memes_defauts():
    """Un écran qui annoncerait un défaut non appliqué par le contrôleur mentirait.

    Les deux lisent désormais la même table de bornes : l'écart n'est plus
    possible par construction, et ce test le vérifie.
    """

    controleur = _controleur({})

    for etape, cles in MENUS_NOMBRES.items():
        defauts = _defauts(await _schema(etape, {}))

        for cle in cles:
            assert defauts[cle] == getattr(controleur, cle), cle


async def test_valider_un_ecran_ne_transforme_pas_les_entiers_en_flottants():
    """Le sélecteur « number » rend un flottant, même avec un pas de 1.

    Sans reprise à la soumission, ``2`` deviendrait ``2.0`` dans les
    options : ``frontend.py`` lit ces durées sans passer par le
    contrôleur et afficherait « 2.0 », et le type stocké changerait à
    chaque validation d'écran. L'hystérésis, elle, doit rester un
    flottant.
    """

    handler = _handler({})
    schema = await _schema("avance", {})

    await handler.async_step_avance(schema({"lavageDuree": 3, "rincageDuree": 2}))

    assert handler.options["lavageDuree"] == 3
    assert isinstance(handler.options["lavageDuree"], int), handler.options["lavageDuree"]
    assert isinstance(handler.options["rincageDuree"], int)
    assert isinstance(handler.options["surpresseurDuree"], int)

    handler = _handler({})
    schema = await _schema("hivernage", {})

    await handler.async_step_hivernage(schema({"temperatureHysteresis": 0.4}))

    assert handler.options["temperatureHysteresis"] == 0.4
    assert isinstance(handler.options["temperatureHysteresis"], float)
    assert isinstance(handler.options["temperatureSecurite"], int)
    assert isinstance(handler.options["tempsDeFiltrationMinimumHivernage"], int)
