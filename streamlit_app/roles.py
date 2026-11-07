"""Role definitions for the factory analytics assistant (img-as-text concept, steps 1-2)."""

ROLES = {
    "director": {
        "id": "director",
        "label": "Tehtaan johtaja",
        "icon": "🏭",
        "description": "Kokonaiskuva tehtaan toiminnasta: tuotanto tavoitteeseen verrattuna, "
                       "aikataulunmukaisuus, turvallisuus ja kustannukset.",
        "briefing_focus": "Tehdastason tunnusluvut ja poikkeamat",
    },
    "shift_supervisor": {
        "id": "shift_supervisor",
        "label": "Vuoropäällikkö",
        "icon": "👷",
        "description": "Oman vuoron tilanne: linjojen OEE, hylkäykset, seisokit ja "
                       "käytettävyys vuorotasolla.",
        "briefing_focus": "Vuoron tunnusluvut, linjapoikkeamat ja datan tuoreus",
    },
    "worker": {
        "id": "worker",
        "label": "Tuotantotyöntekijä",
        "icon": "🔧",
        "description": "Oman linjan päivätavoite, valmistunut määrä, hylkäykset ja "
                       "turvallisuus — yksinkertaisesti.",
        "briefing_focus": "Oman linjan päiväkuva",
    },
}

STEWARD = {
    "id": "steward",
    "label": "Data steward",
    "icon": "🛡️",
    "description": "BI-omaisuuden hallinta: hallinnollinen auditointi, uudelleenkäyttö ja "
                   "elinkaarenpäätökset (Build Less, Build Better).",
}

ALL_ROLES = {**ROLES, "steward": STEWARD}


def get_role(role_id):
    return ALL_ROLES.get(role_id)
