"""Pool controller integration for Home Assistant."""

import logging
from datetime import datetime
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .activation import ActivationMixin
from .buttons import ButtonMixin
from .filtration import FiltrationMixin
from .hivernage import HivernageMixin
from .lavage import LavageMixin
from .saison import SaisonMixin
from .scheduler import SchedulerMixin
from .sensors import SensorMixin
from .service import ServiceMixin
from .surpresseur import SurpresseurMixin
from .traitement import TraitementMixin
from .utils import FiltrationUtilsMixin

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
STORAGE_KEY = "pool_management_data"
STORAGE_KEY_PREFIX = "pool_management_data"

VALID_DISTRIBUTIONS = (1, 2, 3, 4, 5)

#: Bornes des réglages numériques : (minimum, maximum, défaut).
#:
#: Ces huit réglages se saisissaient dans un champ libre, où rien
#: n'empêchait une durée négative ou un seuil hors-gel de 400 °C. Les
#: maxima sont volontairement larges : il s'agit d'écarter l'absurde, pas
#: de dicter une installation. Celui de la pause pivot vient du calcul
#: lui-même, qui ramène déjà pause plus filtration à 24 h.
#:
#: La table est lue par le contrôleur comme par les formulaires : un écran
#: ne peut plus annoncer un défaut que le contrôleur n'applique pas.
BORNES_NOMBRES = {
    "pausePivot": (0, 1440, 0),
    "sondeLocalTechniquePause": (0, 240, 0),
    "surpresseurDuree": (0, 120, 5),
    "lavageDuree": (0, 60, 2),
    "rincageDuree": (0, 60, 2),
    "tempsDeFiltrationMinimumHivernage": (0, 24, 3),
    "temperatureSecurite": (-20, 10, -2),
    "temperatureHysteresis": (0.0, 5.0, 0.5),
}

#: Valeurs acceptées par « Heure de référence de la plage » en hivernage :
#: 1 = lever du soleil, 2 = heure fixe (``datePivotHivernage``).
VALID_CHOIX_HEURE_HIVERNAGE = (1, 2)

#: Actionneurs commandés par le contrôleur, dans l'ordre où il est sûr de les
#: couper : traitements d'abord, surpresseur ensuite, filtration en dernier.
#: L'eau doit circuler tant qu'un équipement tourne.
RELAIS = ("traitement", "traitement_2", "surpresseur", "filtration")


def _validate_choice(value: Any, name: str, default: int, allowed: tuple) -> int:
    """Return value as an int when it belongs to allowed, else the default.

    Les listes déroulantes de Home Assistant rendent des chaînes. La
    conversion en entier est donc ce qui permet aux comparaisons du code
    de voir la valeur choisie : ``"1" == 1`` vaut ``False`` en Python, et
    un réglage comparé à un entier serait sinon toujours jugé différent.

    Logs a warning and returns the default on an out-of-range value.
    Handles None and non-int values.
    """

    try:
        v = int(value)
        if v in allowed:
            return v
    except (TypeError, ValueError):
        pass

    _LOGGER.warning(
        "%s invalide (%s), utilisation de la valeur par défaut %s",
        name,
        value,
        default,
    )
    return default


def _validate_distribution(value: Any, name: str, default: int) -> int:
    """Validate that a distribution config value is in the allowed range.

    Returns the value as int if valid (1..5), otherwise logs a warning
    and returns the provided default. Handles None and non-int values.
    """

    return _validate_choice(value, name, default, VALID_DISTRIBUTIONS)


def _validate_choix_heure_hivernage(value: Any) -> int:
    """Validate the hivernage reference-time choice: 1 sunrise, 2 fixed.

    Le repli est le lever du soleil, choix recommandé pour le hors-gel.
    La version précédente comparait la valeur à 1 sans la valider, si
    bien que tout ce qui n'était pas exactement cet entier — 0, 7, une
    chaîne rendue par une liste déroulante — basculait silencieusement
    sur l'heure fixe.
    """

    return _validate_choice(
        value,
        "choixHeureFiltrationHivernage",
        1,
        VALID_CHOIX_HEURE_HIVERNAGE,
    )


#: Formats acceptés pour un horaire pivot. ``%H:%M`` est celui qu'attend
#: ``pivotTimestamp`` ; ``%H:%M:%S`` est celui que rendrait un sélecteur
#: d'heure de Home Assistant, accepté pour qu'un changement de champ un
#: jour ne casse pas le calcul.
FORMATS_HEURE = ("%H:%M", "%H:%M:%S")


def _validate_heure(value: Any, name: str, default: str) -> str:
    """Return the value as a HH:MM string, or the default when unreadable.

    « Horaire pivot » et « Horaire pivot hivernage » sont des champs texte
    libres dont la valeur finit dans ``datetime.strptime`` : « 13h00 »,
    « 25:00 » ou un champ vidé y levaient une exception. Rien ne
    l'attrapait, et le cron qui calcule la plage repasse chaque minute ;
    la saisie était acceptée, puis plus aucune plage n'était calculée et
    le journal prenait une erreur par minute.

    La valeur rendue est toujours normalisée au format ``HH:MM``, seul
    format que lit ``pivotTimestamp``.
    """

    if isinstance(value, str):
        for format_heure in FORMATS_HEURE:
            try:
                return datetime.strptime(
                    value.strip(), format_heure
                ).strftime("%H:%M")
            except ValueError:
                continue

    _LOGGER.warning(
        "%s invalide (%s), utilisation de la valeur par défaut %s",
        name,
        value,
        default,
    )
    return default


def _validate_nombre(
    value: Any, name: str, default: Any, minimum: Any, maximum: Any
) -> Any:
    """Return the value as a bounded number of the default's own type.

    Une valeur illisible retombe sur le défaut ; une valeur hors bornes
    est ramenée à la borne la plus proche plutôt qu'au défaut, pour que
    l'intention de l'utilisateur soit préservée autant que possible : un
    surpresseur réglé à 500 minutes devient 120, non 5.

    Le type du défaut décide du type rendu. Le sélecteur « number » de
    Home Assistant rend toujours un flottant, même avec un pas de 1 :
    sans cette reprise, valider un écran remplacerait ``2`` par ``2.0``
    dans les options, et ``frontend.py``, qui lit ces durées sans passer
    par le contrôleur, afficherait « 2.0 ».
    """

    try:
        nombre = float(value)
        if isinstance(default, int):
            nombre = round(nombre)
    except (TypeError, ValueError, OverflowError):
        _LOGGER.warning(
            "%s illisible (%s), utilisation de la valeur par défaut %s",
            name,
            value,
            default,
        )
        return default

    borne = min(max(nombre, minimum), maximum)

    if borne != nombre:
        _LOGGER.warning(
            "%s hors bornes (%s), ramené à %s",
            name,
            nombre,
            borne,
        )

    return borne


def _lire_nombre(config: dict, cle: str) -> Any:
    """Lit un réglage numérique borné dans la configuration."""

    minimum, maximum, defaut = BORNES_NOMBRES[cle]

    return _validate_nombre(config.get(cle, defaut), cle, defaut, minimum, maximum)


def _normaliser_nombres(user_input: dict, cles: tuple) -> None:
    """Remet les nombres soumis par un formulaire dans leur type et leurs bornes.

    Le sélecteur refuse déjà les valeurs hors bornes à l'écran ; ce qu'il
    ne fait pas, c'est rendre un entier.
    """

    for cle in cles:
        if cle in user_input:
            minimum, maximum, defaut = BORNES_NOMBRES[cle]
            user_input[cle] = _validate_nombre(
                user_input[cle], cle, defaut, minimum, maximum
            )


class PoolController(
    ActivationMixin,
    ButtonMixin,
    FiltrationMixin,
    HivernageMixin,
    LavageMixin,
    SaisonMixin,
    SchedulerMixin,
    SensorMixin,
    ServiceMixin,
    SurpresseurMixin,
    TraitementMixin,
    FiltrationUtilsMixin,
):
    """Pool controller for managing pool automation logic."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        entry: Optional[ConfigEntry] = None,
    ) -> None:
        """Initialize the pool controller."""

        # Initialisation de la classe mère
        # On appelle le constructeur de la classe mère pour initialiser les mixins
        super().__init__()

        # configuration.yaml
        self.hass = hass
        self.entry = entry
        # Store distinct par instance afin de cohabiter en multi-instance ;
        # une instance unique conserve la clé historique pour la rétro-compat.
        storage_key = (
            f"{STORAGE_KEY_PREFIX}_{entry.entry_id}" if entry is not None else STORAGE_KEY
        )
        self.store = Store(hass, STORAGE_VERSION, storage_key)
        self.data = {}
        self.initialized = False
        # Handle de désabonnement du listener d'extinction, conservé pour
        # pouvoir le détacher au déchargement (voir detach_stop_listener).
        self._stop_listener = None

        # Configuration capteurs
        self.temperatureWater = config.get("temperatureWater")
        self.temperatureOutdoor = config.get("temperatureOutdoor")
        self.leverSoleil = config.get("leverSoleil")

        # Entités
        self.filtration = config.get("filtration")
        self.traitement = config.get("traitement")
        self.traitement_2 = config.get("traitement_2")
        self.surpresseur = config.get("surpresseur")

        # réglages personnalisés
        self.surpresseurDuree = _lire_nombre(config, "surpresseurDuree")

        self.disableMarcheForcee = config.get("disableMarcheForcee", False)
        self.methodeCalcul = int(config.get("methodeCalcul", 1))
        self.datePivot = _validate_heure(
            config.get("datePivot", "13:00"), "datePivot", "13:00"
        )
        self.pausePivot = _lire_nombre(config, "pausePivot")
        self.distributionDatePivot = _validate_distribution(
            config.get("distributionDatePivot", 1), "distributionDatePivot", 1
        )
        self.coefficientAjustement = config.get("coefficientAjustement", 1.0)
        self.coefficientAjustementHivernage = config.get(
            "coefficientAjustementHivernage", 1.0
        )

        self.sondeLocalTechnique = config.get("sondeLocalTechnique", False)
        self.sondeLocalTechniquePause = _lire_nombre(
            config, "sondeLocalTechniquePause"
        )
        self.traitementHivernage = config.get("traitementHivernage", False)
        # Plancher de la plage d'hivernage. Le réglage s'est longtemps appelé
        # « tempsDeFiltrationMinimum » et siégeait dans le menu Filtration,
        # où son libellé annonçait un plancher saisonnier ; la saison n'en a
        # jamais appliqué aucun, et ce réglage n'a jamais eu qu'un seul
        # consommateur, la durée calculée en hivernage. L'ancienne clé est
        # reprise telle quelle : une installation qui avait porté son
        # plancher à 6 h garde un plancher de 6 h, le changement de nom ne
        # ramène personne à 3 h sans le dire.
        minimum, maximum, defaut = BORNES_NOMBRES[
            "tempsDeFiltrationMinimumHivernage"
        ]
        self.tempsDeFiltrationMinimumHivernage = _validate_nombre(
            config.get(
                "tempsDeFiltrationMinimumHivernage",
                config.get("tempsDeFiltrationMinimum", defaut),
            ),
            "tempsDeFiltrationMinimumHivernage",
            defaut,
            minimum,
            maximum,
        )
        self.distributionDatePivotHivernage = _validate_distribution(
            config.get("distributionDatePivotHivernage", 4),
            "distributionDatePivotHivernage",
            4,
        )
        self.choixHeureFiltrationHivernage = _validate_choix_heure_hivernage(
            config.get("choixHeureFiltrationHivernage", 1)
        )
        self.datePivotHivernage = _validate_heure(
            config.get("datePivotHivernage", "06:00"),
            "datePivotHivernage",
            "06:00",
        )
        self.temperatureSecurite = _lire_nombre(config, "temperatureSecurite")
        self.temperatureHysteresis = _lire_nombre(
            config, "temperatureHysteresis"
        )
        self.filtration5mn3h = config.get("filtration5mn3h", False)

        self.lavageDuree = _lire_nombre(config, "lavageDuree")
        self.rincageDuree = _lire_nombre(config, "rincageDuree")

    async def async_initialize(self) -> None:
        """Initialise PoolController by loading data from store."""

        raw_data = await self.store.async_load()

        if raw_data:
            self.data = raw_data
            _LOGGER.info("Loaded data from store: %s", self.data)
        else:
            _LOGGER.info("No data found in store")

        self.initialized = True

        self._stop_listener = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self.async_save_data
        )

    def detach_stop_listener(self) -> None:
        """Détacher l'abonnement à l'extinction de Home Assistant.

        À appeler au déchargement de l'entrée. Sans cela, un contrôleur
        remplacé par un rechargement reste abonné et sauvegarde son état
        figé à l'extinction, sur la même clé de Store que son successeur :
        le dernier qui écrit gagne, et un état périmé peut revenir.
        """

        if self._stop_listener is not None:
            self._stop_listener()
            self._stop_listener = None

    async def stop_replaced_relays(self, config: dict) -> None:
        """Couper les actionneurs que la nouvelle configuration retire.

        À appeler avant un rechargement, tant que ce contrôleur connaît
        encore les identifiants en place. Le contrôleur reconstruit ne
        connaîtra que les nouveaux : un relais actif qu'on lui retire
        resterait allumé sans personne pour l'éteindre, et une pompe
        doseuse orpheline doserait indéfiniment.

        Les actionneurs conservés ne sont pas touchés : le nouveau
        contrôleur en reprend la main sans coupure.
        """

        for nom in RELAIS:
            ancien = getattr(self, nom, None)

            if not ancien or ancien == config.get(nom):
                continue

            etat = self.hass.states.get(ancien)

            if etat is None or etat.state == "off":
                continue

            _LOGGER.warning(
                "%s (%s) retiré de la configuration alors qu'il était actif : "
                "arrêt avant rechargement",
                nom,
                ancien,
            )

            await self._safe_service_call(
                domain=ancien.split(".")[0],
                service="turn_off",
                service_data={"entity_id": ancien},
                entity_name=nom,
            )

    async def async_save_data(self, event: Optional[Any] = None) -> None:
        """Save the current data to the store."""

        if self.initialized:
            await self.store.async_save(self.data)
            if event is not None:
                _LOGGER.info("Saved data to store: %s", self.data)

    def set_data(self, key: str, value: Any) -> None:
        """Set data in the store and trigger save if changed."""

        oldValue = self.data.get(key)
        self.data[key] = value

        if oldValue != value:
            self.hass.async_create_task(self.async_save_data())

    def get_data(self, key: str, default: Optional[Any] = None) -> Any:
        """Get data from the store, returning default if not found."""

        return self.data.get(key, default)
