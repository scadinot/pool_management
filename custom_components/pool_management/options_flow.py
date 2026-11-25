"""Options flow for Pool Management integration."""

from typing import Any, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import FlowResult
from homeassistant.helpers.selector import selector

from .controller import (
    BORNES_NOMBRES,
    _normaliser_nombres,
    _validate_choix_heure_hivernage,
    _validate_distribution,
    _validate_heure,
    _validate_nombre,
)


def _selecteur_nombre(cle: str) -> Any:
    """Construit le sélecteur borné d'un réglage numérique.

    Le libellé de chacun de ces champs porte déjà son unité : aucune
    ``unit_of_measurement`` n'est posée, elle ferait doublon.
    """

    minimum, maximum, defaut = BORNES_NOMBRES[cle]

    return selector(
        {
            "number": {
                "min": minimum,
                "max": maximum,
                "step": 1 if isinstance(defaut, int) else 0.1,
                "mode": "box",
            }
        }
    )


class PoolManagementOptionsFlowHandler(config_entries.OptionsFlow):
    """Gestion des options de Pool Management avec menu de navigation."""

    #: Entités facultatives de l'écran « user » : second relais de
    #: traitement, pompe à chaleur et son capteur de puissance. Elles
    #: reçoivent un ``suggested_value`` plutôt qu'un ``default`` (voir
    #: ``async_step_user``) et peuvent être effacées.
    CHAMPS_OPTIONNELS = ("traitement_2", "heatPump", "heatPumpPower")

    def __init__(self) -> None:
        """Initialize the options flow."""

        self.options: dict[str, Any] = {}

    async def async_step_init(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Étape initiale de configuration des options."""

        if not self.options:
            self.options = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            return await getattr(self, f"async_step_{user_input['menu']}")()

        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "user",
                "filtration",
                "hivernage",
                "avance",
                "confirm",
            ],
        )

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the user step of the options flow."""

        if user_input is not None:
            # Un champ optionnel laissé vide est absent des données
            # soumises. ``update`` ne supprimant rien, il faut le retirer
            # explicitement : sans cela une entité choisie une fois ne
            # pourrait plus jamais être effacée.
            for champ in self.CHAMPS_OPTIONNELS:
                if champ not in user_input:
                    self.options.pop(champ, None)

            self.options.update(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "temperatureWater", default=self.options.get("temperatureWater")
                    ): selector({"entity": {"domain": ["sensor", "input_number"]}}),
                    vol.Required(
                        "temperatureOutdoor",
                        default=self.options.get("temperatureOutdoor"),
                    ): selector({"entity": {"domain": ["sensor", "input_number"]}}),
                    vol.Required(
                        "leverSoleil", default=self.options.get("leverSoleil")
                    ): selector({"entity": {"domain": ["sensor", "input_number"]}}),
                    vol.Required(
                        "filtration", default=self.options.get("filtration")
                    ): selector({"entity": {"domain": ["switch", "input_boolean"]}}),
                    vol.Required(
                        "traitement", default=self.options.get("traitement")
                    ): selector({"entity": {"domain": ["switch", "input_boolean"]}}),
                    # Champs optionnels : ``suggested_value`` et non
                    # ``default``. Avec un ``default``, voluptuous injecte la
                    # clé absente puis la valide, et le sélecteur d'entité
                    # refuse ``None`` — le champ optionnel devient alors
                    # impossible à laisser vide.
                    vol.Optional(
                        "traitement_2",
                        description={
                            "suggested_value": self.options.get("traitement_2")
                        },
                    ): selector({"entity": {"domain": ["switch", "input_boolean"]}}),
                    vol.Required(
                        "surpresseur", default=self.options.get("surpresseur")
                    ): selector({"entity": {"domain": ["switch", "input_boolean"]}}),
                    vol.Optional(
                        "heatPump",
                        description={"suggested_value": self.options.get("heatPump")},
                    ): selector(
                        {"entity": {"domain": ["switch", "input_boolean", "climate"]}}
                    ),
                    vol.Optional(
                        "heatPumpPower",
                        description={
                            "suggested_value": self.options.get("heatPumpPower")
                        },
                    ): selector({"entity": {"domain": "sensor", "device_class": "power"}}),
                }
            ),
            last_step=False,
        )

    def _nombre(self, cle: str) -> Any:
        """Retourne le réglage numérique enregistré, ramené dans ses bornes.

        Un défaut hors bornes serait refusé par le sélecteur dès que le
        champ est omis à la soumission, puisque ``vol.Optional`` le
        réinjecte : l'écran deviendrait impossible à enregistrer.
        """

        minimum, maximum, defaut = BORNES_NOMBRES[cle]

        return _validate_nombre(
            self.options.get(cle, defaut), cle, defaut, minimum, maximum
        )

    def _plancher_hivernage(self) -> int:
        """Retourne le plancher d'hivernage enregistré, ramené dans ses bornes.

        Le réglage s'est longtemps appelé « tempsDeFiltrationMinimum » :
        l'ancienne clé sert encore de défaut, pour que l'écran s'ouvre sur
        le plancher qui s'applique réellement.
        """

        cle = "tempsDeFiltrationMinimumHivernage"
        minimum, maximum, defaut = BORNES_NOMBRES[cle]
        valeur = self.options.get(
            cle, self.options.get("tempsDeFiltrationMinimum", defaut)
        )

        return _validate_nombre(valeur, cle, defaut, minimum, maximum)

    def _horaire(self, cle: str, defaut: str) -> str:
        """Retourne l'horaire enregistré, assaini, ou le défaut.

        Sert de valeur proposée par le formulaire et de repli en cas de
        saisie illisible : un utilisateur réglé sur 14:30 qui tape
        « 15h00 » garde 14:30, plutôt que d'être ramené au défaut du
        paquet, qu'il n'a peut-être jamais utilisé.
        """

        return _validate_heure(self.options.get(cle, defaut), cle, defaut)

    async def async_step_filtration(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the filtration step of the options flow."""

        if user_input is not None:
            user_input["distributionDatePivot"] = _validate_distribution(
                user_input.get("distributionDatePivot"), "distributionDatePivot", 1
            )

            # Champ texte libre consommé par ``strptime`` : un horaire
            # illisible s'enregistrait sans bruit, puis faisait échouer
            # le calcul de la plage à chaque minute du cron. Le repli
            # est l'horaire déjà en place, non le défaut du paquet.
            user_input["datePivot"] = _validate_heure(
                user_input.get("datePivot"),
                "datePivot",
                self._horaire("datePivot", "13:00"),
            )

            _normaliser_nombres(user_input, ("pausePivot",))

            self.options.update(user_input)
            return await self.async_step_init()

        schema = {
            vol.Optional(
                "methodeCalcul", default=str(self.options.get("methodeCalcul", 1))
            ): selector(
                {
                    "select": {
                        "mode": "dropdown",
                        # Les libellés étaient écrits en français dans
                        # le code : une interface en anglais affichait
                        # « Courbe de température ». Ils viennent
                        # désormais des traductions.
                        "translation_key": "methode_calcul",
                        "options": ["1", "2"],
                    }
                }
            ),
            vol.Optional(
                "coefficientAjustement",
                default=self.options.get("coefficientAjustement", 1.0),
            ): selector(
                {
                    "number": {
                        "min": 0.3,
                        "max": 1.7,
                        "step": 0.1,
                        "mode": "slider",
                        "unit_of_measurement": "x",
                    }
                }
            ),
            # Le défaut est assaini avant d'être proposé : une entrée
            # configurée par une version antérieure peut porter un
            # horaire illisible, et ``vol.Optional`` réinjecte son
            # défaut dès que le champ est omis à la soumission.
            vol.Optional(
                "datePivot", default=self._horaire("datePivot", "13:00")
            ): str,
            vol.Optional(
                "pausePivot", default=self._nombre("pausePivot")
            ): _selecteur_nombre("pausePivot"),
            vol.Optional(
                "distributionDatePivot",
                default=str(self.options.get("distributionDatePivot", 1)),
            ): selector(
                {
                    "select": {
                        "mode": "dropdown",
                        "options": [
                            {"value": "1", "label": "(1/2 <> 1/2)"},
                            {"value": "2", "label": "(1/3 <> 2/3)"},
                            {"value": "3", "label": "(2/3 <> 1/3)"},
                            {"value": "4", "label": "(1/1 <>)"},
                            {"value": "5", "label": "(<> 1/1)"},
                        ],
                    }
                }
            ),
        }

        return self.async_show_form(
            step_id="filtration", data_schema=vol.Schema(schema), last_step=False
        )

    async def async_step_hivernage(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the hivernage step of the options flow."""

        if user_input is not None:
            user_input["distributionDatePivotHivernage"] = _validate_distribution(
                user_input.get("distributionDatePivotHivernage"),
                "distributionDatePivotHivernage",
                4,
            )

            # La liste déroulante rend une chaîne, et ``hivernage.py``
            # compare ce réglage à l'entier 1 : sans conversion ici, le
            # choix du lever du soleil serait lu comme une heure fixe.
            user_input["choixHeureFiltrationHivernage"] = (
                _validate_choix_heure_hivernage(
                    user_input.get("choixHeureFiltrationHivernage")
                )
            )

            # Même champ texte libre que l'horaire pivot de saison.
            # Il n'est lu que si « Heure fixe » est choisi, mais il
            # est enregistré dans tous les cas : une saisie fautive
            # dormirait jusqu'au jour où ce choix est fait.
            user_input["datePivotHivernage"] = _validate_heure(
                user_input.get("datePivotHivernage"),
                "datePivotHivernage",
                self._horaire("datePivotHivernage", "06:00"),
            )

            _normaliser_nombres(
                user_input,
                (
                    "tempsDeFiltrationMinimumHivernage",
                    "temperatureSecurite",
                    "temperatureHysteresis",
                ),
            )

            self.options.update(user_input)

            # Le plancher a changé de nom : deux clés portant le même sens
            # finiraient par diverger. L'ancienne est retirée des options dès
            # que l'écran est validé, sa valeur ayant servi de défaut au
            # nouveau champ. Celle que porterait ``entry.data`` survit, mais
            # les options primant sur elle dans la fusion, elle ne décide
            # plus de rien.
            self.options.pop("tempsDeFiltrationMinimum", None)

            return await self.async_step_init()

        return self.async_show_form(
            step_id="hivernage",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "traitementHivernage",
                        default=self.options.get("traitementHivernage", False),
                    ): bool,
                    vol.Optional(
                        "coefficientAjustementHivernage",
                        default=self.options.get("coefficientAjustementHivernage", 1.0),
                    ): selector(
                        {
                            "number": {
                                "min": 0.3,
                                "max": 1.7,
                                "step": 0.1,
                                "mode": "slider",
                                "unit_of_measurement": "x",
                            }
                        }
                    ),
                    # Plancher de la plage d'hivernage. Le défaut reprend la
                    # valeur enregistrée sous l'ancien nom, pour que l'écran
                    # s'ouvre sur le plancher qui s'applique réellement : le
                    # valider ne doit pas changer le réglage à l'insu de
                    # l'utilisateur.
                    vol.Optional(
                        "tempsDeFiltrationMinimumHivernage",
                        default=self._plancher_hivernage(),
                    ): _selecteur_nombre("tempsDeFiltrationMinimumHivernage"),
                    vol.Optional(
                        "distributionDatePivotHivernage",
                        default=str(
                            self.options.get("distributionDatePivotHivernage", 4)
                        ),
                    ): selector(
                        {
                            "select": {
                                "mode": "dropdown",
                                "options": [
                                    {"value": "1", "label": "(1/2 <> 1/2)"},
                                    {"value": "2", "label": "(1/3 <> 2/3)"},
                                    {"value": "3", "label": "(2/3 <> 1/3)"},
                                    {"value": "4", "label": "(1/1 <>)"},
                                    {"value": "5", "label": "(<> 1/1)"},
                                ],
                            }
                        }
                    ),
                    # Liste déroulante et non champ numérique : rien, dans
                    # un entier nu, ne disait que 1 valait « lever du
                    # soleil » et 2 « heure fixe ». Les libellés viennent
                    # des traductions via ``translation_key``.
                    #
                    # Le défaut est validé avant d'être converti en chaîne.
                    # L'ancien champ numérique était libre, donc une entrée
                    # peut porter 0 ou 7 : rendu tel quel, ce nombre ne
                    # correspondrait à aucune entrée de la liste, qui
                    # s'ouvrirait sans choix valide. Et le champ omis à la
                    # soumission, ``vol.Optional`` injecterait ce défaut
                    # puis le sélecteur le rejetterait — avant que la
                    # validation de l'étape ait pu le corriger, bloquant
                    # tout enregistrement.
                    vol.Optional(
                        "choixHeureFiltrationHivernage",
                        default=str(
                            _validate_choix_heure_hivernage(
                                self.options.get("choixHeureFiltrationHivernage", 1)
                            )
                        ),
                    ): selector(
                        {
                            "select": {
                                "mode": "dropdown",
                                "translation_key": "choix_heure_filtration_hivernage",
                                "options": ["1", "2"],
                            }
                        }
                    ),
                    # Défaut assaini, comme l'horaire pivot de saison.
                    vol.Optional(
                        "datePivotHivernage",
                        default=self._horaire(
                            "datePivotHivernage", "06:00"
                        ),
                    ): str,
                    vol.Optional(
                        "temperatureSecurite",
                        default=self._nombre("temperatureSecurite"),
                    ): _selecteur_nombre("temperatureSecurite"),
                    vol.Optional(
                        "temperatureHysteresis",
                        default=self._nombre("temperatureHysteresis"),
                    ): _selecteur_nombre("temperatureHysteresis"),
                    vol.Optional(
                        "filtration5mn3h",
                        default=self.options.get("filtration5mn3h", False),
                    ): bool,
                }
            ),
            last_step=False,
        )

    async def async_step_avance(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the avance step of the options flow."""

        if user_input is not None:
            _normaliser_nombres(
                user_input,
                (
                    "sondeLocalTechniquePause",
                    "surpresseurDuree",
                    "lavageDuree",
                    "rincageDuree",
                ),
            )

            self.options.update(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="avance",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "disableMarcheForcee",
                        default=self.options.get("disableMarcheForcee", False),
                    ): bool,
                    vol.Optional(
                        "sondeLocalTechnique",
                        default=self.options.get("sondeLocalTechnique", False),
                    ): bool,
                    vol.Optional(
                        "sondeLocalTechniquePause",
                        default=self._nombre("sondeLocalTechniquePause"),
                    ): _selecteur_nombre("sondeLocalTechniquePause"),
                    vol.Optional(
                        "surpresseurDuree",
                        default=self._nombre("surpresseurDuree"),
                    ): _selecteur_nombre("surpresseurDuree"),
                    vol.Optional(
                        "lavageDuree", default=self._nombre("lavageDuree")
                    ): _selecteur_nombre("lavageDuree"),
                    vol.Optional(
                        "rincageDuree", default=self._nombre("rincageDuree")
                    ): _selecteur_nombre("rincageDuree"),
                }
            ),
            last_step=False,
        )

    async def async_step_confirm(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the confirm step of the options flow."""

        return self.async_create_entry(title="Pool Management", data=self.options)
