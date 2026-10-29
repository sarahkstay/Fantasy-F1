"""
Schema definitions and ID normalisation for Fantasy F1 2026.

Different data sources use different names for the same drivers and
circuits. This module provides canonical mappings so that data from
Kaggle, TracingInsights, FastF1, and OpenF1 can be joined reliably.

The canonical key for drivers is the 3-letter abbreviation (e.g., "VER").
The canonical key for circuits is a snake_case ID (e.g., "albert_park").

Usage:
    from src.data.schema import normalise_driver, normalise_circuit
    normalise_driver("Max Verstappen")  # -> "VER"
    normalise_driver("verstappen")      # -> "VER"
    normalise_circuit("Melbourne")      # -> "albert_park"
"""

from __future__ import annotations


# ============================================================
# Status Classification (Kaggle / API status -> Finished / DNF / DSQ)
# ============================================================
# Used by scoring.py to apply DNF/DSQ penalties. Keys are normalised
# (uppercase, stripped). Add entries when new sources use different codes.

STATUS_CLASSIFICATION: dict[str, str] = {
    # Finished (classified)
    "1": "Finished",
    "FINISHED": "Finished",
    "+1 LAP": "Finished",
    "+2 LAPS": "Finished",
    "+3 LAPS": "Finished",
    "+4 LAPS": "Finished",
    "+5 LAPS": "Finished",
    "+6 LAPS": "Finished",
    "+7 LAPS": "Finished",
    "+8 LAPS": "Finished",
    "+9 LAPS": "Finished",
    "+10 LAPS": "Finished",
    "+11 LAPS": "Finished",
    "+12 LAPS": "Finished",
    "+13 LAPS": "Finished",
    "+14 LAPS": "Finished",
    "+15 LAPS": "Finished",
    "+16 LAPS": "Finished",
    "+17 LAPS": "Finished",
    "+18 LAPS": "Finished",
    "+19 LAPS": "Finished",
    "+20 LAPS": "Finished",
    "+21 LAPS": "Finished",
    "+22 LAPS": "Finished",
    "+23 LAPS": "Finished",
    "+24 LAPS": "Finished",
    "+25 LAPS": "Finished",
    "+26 LAPS": "Finished",
    "+27 LAPS": "Finished",
    "+28 LAPS": "Finished",
    "+29 LAPS": "Finished",
    "+30 LAPS": "Finished",
    "+42 LAPS": "Finished",
    "NOT CLASSIFIED": "DNF",
    "WITHDREW": "DNF",
    "RETIRED": "DNF",
    "DISQUALIFIED": "DSQ",
    "EXCLUDED": "DSQ",
    # DNF reasons (Kaggle / common)
    "ACCIDENT": "DNF",
    "ACCIDENTAL": "DNF",
    "COLLISION": "DNF",
    "ENGINE": "DNF",
    "GEARBOX": "DNF",
    "SPUN OFF": "DNF",
    "POWER UNIT": "DNF",
    "POWER LOSS": "DNF",
    "BRAKES": "DNF",
    "WHEEL": "DNF",
    "TRANSMISSION": "DNF",
    "HYDRAULICS": "DNF",
    "ELECTRICAL": "DNF",
    "FUEL PRESSURE": "DNF",
    "PUNCTURE": "DNF",
    "OIL LEAK": "DNF",
    "OIL PRESSURE": "DNF",
    "WATER PRESSURE": "DNF",
    "WATER LEAK": "DNF",
    "INJURY": "DNF",
    "ILLNESS": "DNF",
    "DID NOT QUALIFY": "DNF",
    "DID NOT PREQUALIFY": "DNF",
    "DRIVER OFF": "DNF",
    "DRIVETRAIN": "DNF",
    "SUSPENSION": "DNF",
    "CLUTCH": "DNF",
    "STEERING": "DNF",
    "COOLING": "DNF",
    "OVERHEATING": "DNF",
    "FUEL SYSTEM": "DNF",
    "FUEL PUMP": "DNF",
    "EXHAUST": "DNF",
    "BATTERY": "DNF",
    "ELECTRONICS": "DNF",
    "THROTTLE": "DNF",
    "LAP": "Finished",  # "+N Lap" variants
}


# ============================================================
# Driver Normalisation
# ============================================================

# Maps various name forms to the canonical 3-letter code.
# Add entries here when a new source uses a different spelling.
DRIVER_NAME_TO_CODE: dict[str, str] = {
    # Max Verstappen
    "max verstappen": "VER",
    "verstappen": "VER",
    "ver": "VER",
    "max_verstappen": "VER",
    # George Russell
    "george russell": "RUS",
    "russell": "RUS",
    "rus": "RUS",
    "george_russell": "RUS",
    # Lando Norris
    "lando norris": "NOR",
    "norris": "NOR",
    "nor": "NOR",
    "lando_norris": "NOR",
    # Oscar Piastri
    "oscar piastri": "PIA",
    "piastri": "PIA",
    "pia": "PIA",
    "oscar_piastri": "PIA",
    # Kimi Antonelli
    "kimi antonelli": "ANT",
    "andrea kimi antonelli": "ANT",
    "antonelli": "ANT",
    "ant": "ANT",
    "kimi_antonelli": "ANT",
    # Charles Leclerc
    "charles leclerc": "LEC",
    "leclerc": "LEC",
    "lec": "LEC",
    "charles_leclerc": "LEC",
    # Lewis Hamilton
    "lewis hamilton": "HAM",
    "hamilton": "HAM",
    "ham": "HAM",
    "lewis_hamilton": "HAM",
    # Isack Hadjar
    "isack hadjar": "HAD",
    "hadjar": "HAD",
    "had": "HAD",
    "isack_hadjar": "HAD",
    # Pierre Gasly
    "pierre gasly": "GAS",
    "gasly": "GAS",
    "gas": "GAS",
    "pierre_gasly": "GAS",
    # Carlos Sainz
    "carlos sainz": "SAI",
    "sainz": "SAI",
    "sai": "SAI",
    "carlos_sainz": "SAI",
    "carlos sainz jr": "SAI",
    "carlos sainz jr.": "SAI",
    # Alexander Albon
    "alexander albon": "ALB",
    "alex albon": "ALB",
    "albon": "ALB",
    "alb": "ALB",
    "alexander_albon": "ALB",
    # Fernando Alonso
    "fernando alonso": "ALO",
    "alonso": "ALO",
    "alo": "ALO",
    "fernando_alonso": "ALO",
    # Lance Stroll
    "lance stroll": "STR",
    "stroll": "STR",
    "str": "STR",
    "lance_stroll": "STR",
    # Oliver Bearman
    "oliver bearman": "BEA",
    "bearman": "BEA",
    "bea": "BEA",
    "oliver_bearman": "BEA",
    # Esteban Ocon
    "esteban ocon": "OCO",
    "ocon": "OCO",
    "oco": "OCO",
    "esteban_ocon": "OCO",
    # Nico Hulkenberg
    "nico hulkenberg": "HUL",
    "nico hülkenberg": "HUL",
    "hulkenberg": "HUL",
    "hülkenberg": "HUL",
    "hul": "HUL",
    "nico_hulkenberg": "HUL",
    # Liam Lawson
    "liam lawson": "LAW",
    "lawson": "LAW",
    "law": "LAW",
    "liam_lawson": "LAW",
    # Gabriel Bortoleto
    "gabriel bortoleto": "BOR",
    "bortoleto": "BOR",
    "bor": "BOR",
    "gabriel_bortoleto": "BOR",
    # Arvid Lindblad
    "arvid lindblad": "LIN",
    "lindblad": "LIN",
    "lin": "LIN",
    "arvid_lindblad": "LIN",
    # Franco Colapinto
    "franco colapinto": "COL",
    "colapinto": "COL",
    "col": "COL",
    "franco_colapinto": "COL",
    # Sergio Perez
    "sergio perez": "PER",
    "sergio pérez": "PER",
    "perez": "PER",
    "pérez": "PER",
    "per": "PER",
    "sergio_perez": "PER",
    # Valtteri Bottas
    "valtteri bottas": "BOT",
    "bottas": "BOT",
    "bot": "BOT",
    "valtteri_bottas": "BOT",

    # --- Historical drivers (appear in training data but not 2026 grid) ---
    "daniel ricciardo": "RIC",
    "ricciardo": "RIC",
    "ric": "RIC",
    "yuki tsunoda": "TSU",
    "tsunoda": "TSU",
    "tsu": "TSU",
    "kevin magnussen": "MAG",
    "magnussen": "MAG",
    "mag": "MAG",
    "guanyu zhou": "ZHO",
    "zhou guanyu": "ZHO",
    "zhou": "ZHO",
    "zho": "ZHO",
    "logan sargeant": "SAR",
    "sargeant": "SAR",
    "sar": "SAR",
    "nyck de vries": "DEV",
    "de vries": "DEV",
    "dev": "DEV",
    "nicholas latifi": "LAT",
    "latifi": "LAT",
    "lat": "LAT",
    "sebastian vettel": "VET",
    "vettel": "VET",
    "vet": "VET",
    "mick schumacher": "MSC",
    "schumacher": "MSC",
    "msc": "MSC",
    "pierre gasly": "GAS",
    "jack doohan": "DOO",
    "doohan": "DOO",
    "doo": "DOO",
}

# Driver number to code mapping (for OpenF1 which uses car numbers)
DRIVER_NUMBER_TO_CODE: dict[int, str] = {
    1: "VER",
    63: "RUS",
    4: "NOR",
    81: "PIA",
    12: "ANT",  # Antonelli's number TBC — update when confirmed
    16: "LEC",
    44: "HAM",
    35: "HAD",  # Hadjar's number TBC
    10: "GAS",
    55: "SAI",
    23: "ALB",
    14: "ALO",
    18: "STR",
    87: "BEA",  # Bearman's number TBC
    31: "OCO",
    27: "HUL",
    30: "LAW",  # Lawson's number TBC
    5: "BOR",   # Bortoleto's number TBC
    40: "LIN",  # Lindblad's number TBC
    43: "COL",  # Colapinto's number
    11: "PER",
    77: "BOT",
}


def normalise_driver(name: str) -> str:
    """Convert any driver name variant to the canonical 3-letter code.

    Args:
        name: Driver name in any format (full name, surname, abbreviation,
              underscore-separated, etc.)

    Returns:
        Canonical 3-letter code (e.g., "VER").

    Raises:
        KeyError: If the name isn't recognised. Add it to the mapping above.
    """
    key = name.strip().lower()
    if key in DRIVER_NAME_TO_CODE:
        return DRIVER_NAME_TO_CODE[key]
    # Try just the last word (surname)
    surname = key.split()[-1] if " " in key else key
    if surname in DRIVER_NAME_TO_CODE:
        return DRIVER_NAME_TO_CODE[surname]
    raise KeyError(
        f"Unknown driver name: '{name}'. "
        f"Add a mapping in src/data/schema.py DRIVER_NAME_TO_CODE."
    )


def normalise_driver_number(number: int) -> str:
    """Convert a car number to the canonical driver code."""
    if number in DRIVER_NUMBER_TO_CODE:
        return DRIVER_NUMBER_TO_CODE[number]
    raise KeyError(
        f"Unknown driver number: {number}. "
        f"Add a mapping in src/data/schema.py DRIVER_NUMBER_TO_CODE."
    )


# ============================================================
# Circuit Normalisation
# ============================================================

# Maps various circuit name forms to the canonical snake_case ID
# used in config.yaml's circuits section.
CIRCUIT_NAME_TO_ID: dict[str, str] = {
    # Albert Park (Australia)
    "albert park": "albert_park",
    "melbourne": "albert_park",
    "australia": "albert_park",
    "australian grand prix": "albert_park",
    # Shanghai (China)
    "shanghai": "shanghai",
    "china": "shanghai",
    "chinese grand prix": "shanghai",
    "shanghai international circuit": "shanghai",
    # Suzuka (Japan)
    "suzuka": "suzuka",
    "japan": "suzuka",
    "japanese grand prix": "suzuka",
    "suzuka international racing course": "suzuka",
    # Bahrain
    "bahrain": "bahrain",
    "sakhir": "bahrain",
    "bahrain international circuit": "bahrain",
    "bahrain grand prix": "bahrain",
    # Jeddah (Saudi Arabia)
    "jeddah": "jeddah",
    "saudi arabia": "jeddah",
    "jeddah corniche circuit": "jeddah",
    "saudi arabian grand prix": "jeddah",
    # Miami
    "miami": "miami",
    "miami international autodrome": "miami",
    "miami grand prix": "miami",
    # Montreal (Canada)
    "montreal": "montreal",
    "canada": "montreal",
    "circuit gilles villeneuve": "montreal",
    "canadian grand prix": "montreal",
    # Monaco
    "monaco": "monaco",
    "monte carlo": "monaco",
    "circuit de monaco": "monaco",
    "monaco grand prix": "monaco",
    # Barcelona (Spain / Catalunya)
    "barcelona": "barcelona",
    "circuit de barcelona-catalunya": "barcelona",
    "catalunya": "barcelona",
    "spanish grand prix": "barcelona",
    # Red Bull Ring (Austria)
    "red bull ring": "red_bull_ring",
    "spielberg": "red_bull_ring",
    "austria": "red_bull_ring",
    "austrian grand prix": "red_bull_ring",
    # Silverstone (Great Britain)
    "silverstone": "silverstone",
    "great britain": "silverstone",
    "british grand prix": "silverstone",
    # Spa (Belgium)
    "spa": "spa",
    "spa-francorchamps": "spa",
    "belgium": "spa",
    "belgian grand prix": "spa",
    "circuit de spa-francorchamps": "spa",
    # Hungaroring (Hungary)
    "hungaroring": "hungaroring",
    "budapest": "hungaroring",
    "hungary": "hungaroring",
    "hungarian grand prix": "hungaroring",
    # Zandvoort (Netherlands)
    "zandvoort": "zandvoort",
    "netherlands": "zandvoort",
    "dutch grand prix": "zandvoort",
    "circuit zandvoort": "zandvoort",
    # Monza (Italy)
    "monza": "monza",
    "italy": "monza",
    "autodromo nazionale monza": "monza",
    "italian grand prix": "monza",
    # Valencia (Spain R16)
    "valencia": "valencia",
    "valencia street circuit": "valencia",
    # Baku (Azerbaijan)
    "baku": "baku",
    "azerbaijan": "baku",
    "baku city circuit": "baku",
    "azerbaijan grand prix": "baku",
    # Marina Bay (Singapore)
    "marina bay": "marina_bay",
    "singapore": "marina_bay",
    "marina bay street circuit": "marina_bay",
    "singapore grand prix": "marina_bay",
    # COTA (United States)
    "cota": "cota",
    "austin": "cota",
    "circuit of the americas": "cota",
    "united states": "cota",
    "united states grand prix": "cota",
    "us grand prix": "cota",
    # Mexico City
    "mexico city": "mexico_city",
    "mexico": "mexico_city",
    "autodromo hermanos rodriguez": "mexico_city",
    "mexican grand prix": "mexico_city",
    # Interlagos (Brazil)
    "interlagos": "interlagos",
    "sao paulo": "interlagos",
    "são paulo": "interlagos",
    "brazil": "interlagos",
    "autodromo jose carlos pace": "interlagos",
    "brazilian grand prix": "interlagos",
    # Las Vegas
    "las vegas": "las_vegas",
    "las vegas strip circuit": "las_vegas",
    "las vegas grand prix": "las_vegas",
    # Losail (Qatar)
    "losail": "losail",
    "lusail": "losail",
    "qatar": "losail",
    "losail international circuit": "losail",
    "qatar grand prix": "losail",
    # Yas Marina (Abu Dhabi)
    "yas marina": "yas_marina",
    "abu dhabi": "yas_marina",
    "yas marina circuit": "yas_marina",
    "abu dhabi grand prix": "yas_marina",
    # Madrid (new for 2026)
    "madrid": "madrid",
    "madring": "madrid",
    "spain": "barcelona",  # backup — usually Barcelona, but 2026 has Madrid replacing
    "spanish grand prix": "madrid",
}

# Round number to circuit ID mapping for 2026 season
ROUND_TO_CIRCUIT_2026: dict[int, str] = {
    1: "albert_park",
    2: "shanghai",
    3: "suzuka",
    4: "bahrain",
    5: "jeddah",
    6: "miami",
    7: "montreal",
    8: "monaco",
    9: "barcelona",
    10: "red_bull_ring",
    11: "silverstone",
    12: "spa",
    13: "hungaroring",
    14: "zandvoort",
    15: "monza",
    16: "madrid",
    17: "baku",
    18: "marina_bay",
    19: "cota",
    20: "mexico_city",
    21: "interlagos",
    22: "las_vegas",
    23: "losail",
    24: "yas_marina",
}


def normalise_circuit(name: str) -> str:
    """Convert any circuit name variant to the canonical snake_case ID.

    Args:
        name: Circuit name in any format.

    Returns:
        Canonical circuit ID (e.g., "albert_park").

    Raises:
        KeyError: If the name isn't recognised.
    """
    key = name.strip().lower()
    if key in CIRCUIT_NAME_TO_ID:
        return CIRCUIT_NAME_TO_ID[key]
    # Try partial matching (useful for compound names)
    for known_name, circuit_id in CIRCUIT_NAME_TO_ID.items():
        if key in known_name or known_name in key:
            return circuit_id
    raise KeyError(
        f"Unknown circuit name: '{name}'. "
        f"Add a mapping in src/data/schema.py CIRCUIT_NAME_TO_ID."
    )


def circuit_for_round(year: int, round_number: int) -> str:
    """Get the circuit ID for a given season and round.

    Currently only 2026 calendar is hardcoded. For historical seasons,
    this information comes from the data sources (FastF1, Kaggle, etc.).
    """
    if year == 2026:
        if round_number in ROUND_TO_CIRCUIT_2026:
            return ROUND_TO_CIRCUIT_2026[round_number]
        raise ValueError(f"No circuit mapped for 2026 round {round_number}.")
    raise ValueError(
        f"Calendar for {year} not hardcoded. Use data source lookup instead."
    )


# ============================================================
# Constructor Normalisation
# ============================================================

CONSTRUCTOR_NAME_TO_ID: dict[str, str] = {
    "red bull racing": "red_bull",
    "red bull": "red_bull",
    "redbull": "red_bull",
    "mercedes": "mercedes",
    "mercedes-amg petronas": "mercedes",
    "mclaren": "mclaren",
    "mclaren f1 team": "mclaren",
    "ferrari": "ferrari",
    "scuderia ferrari": "ferrari",
    "alpine": "alpine",
    "alpine f1 team": "alpine",
    "bwt alpine f1 team": "alpine",
    "williams": "williams",
    "williams racing": "williams",
    "aston martin": "aston_martin",
    "aston martin aramco": "aston_martin",
    "haas": "haas",
    "haas f1 team": "haas",
    "haas f1": "haas",
    "audi": "audi",
    "kick sauber": "audi",
    "sauber": "audi",
    "stake f1 team": "audi",
    "alfa romeo": "audi",  # Historical: Alfa Romeo -> Sauber -> Audi
    "racing bulls": "racing_bulls",
    "rb": "racing_bulls",
    "visa cash app rb": "racing_bulls",
    "alphatauri": "racing_bulls",
    "scuderia alphatauri": "racing_bulls",
    "toro rosso": "racing_bulls",
    "cadillac": "cadillac",
    "cadillac f1": "cadillac",
    "andretti": "cadillac",  # Andretti-Cadillac
}


def normalise_constructor(name: str) -> str:
    """Convert any constructor name variant to the canonical ID."""
    key = name.strip().lower()
    if key in CONSTRUCTOR_NAME_TO_ID:
        return CONSTRUCTOR_NAME_TO_ID[key]
    for known_name, team_id in CONSTRUCTOR_NAME_TO_ID.items():
        if key in known_name or known_name in key:
            return team_id
    raise KeyError(
        f"Unknown constructor name: '{name}'. "
        f"Add a mapping in src/data/schema.py CONSTRUCTOR_NAME_TO_ID."
    )


# ============================================================
# Unified DataFrame Column Names
# ============================================================
# All data loaders output DataFrames with these exact column names.
# This prevents subtle bugs from inconsistent naming across sources.

UNIFIED_COLUMNS = {
    # Identifiers
    "year": "int",           # Season year
    "round": "int",          # Round number in season
    "circuit_id": "str",     # Canonical circuit ID (e.g., "albert_park")
    "session_type": "str",   # "qualifying", "sprint", "race"
    "driver_code": "str",    # 3-letter driver code (e.g., "VER")
    "constructor_id": "str", # Canonical constructor ID (e.g., "red_bull")

    # Results
    "grid_position": "int",       # Starting grid position
    "finish_position": "int",     # Finishing position (0 if DNF)
    "status": "str",              # "Finished", "DNF", "DSQ", etc.
    "points_official": "float",   # Official F1 championship points
    "finish_time_ms": "float",    # Finish time in milliseconds (null if DNF)
    "fastest_lap_rank": "int",    # Rank of driver's fastest lap (1 = fastest)

    # Qualifying specifics
    "q1_time_ms": "float",  # Q1 lap time in milliseconds
    "q2_time_ms": "float",  # Q2 lap time (null if eliminated in Q1)
    "q3_time_ms": "float",  # Q3 lap time (null if eliminated in Q2)

    # Race/sprint specifics
    "positions_gained": "int",     # grid - finish (positive = gained)
    "overtakes": "int",            # Number of overtakes made
    "is_fastest_lap": "bool",      # True if this driver set fastest lap
    "is_dotd": "bool",             # True if Driver of the Day (race only)

    # Pitstop data (constructor-level, but stored per driver for convenience)
    "fastest_pitstop_ms": "float", # Team's fastest pitstop in this race
    "avg_pitstop_ms": "float",     # Team's average pitstop time

    # Weather (per session)
    "air_temp_c": "float",
    "track_temp_c": "float",
    "humidity_pct": "float",
    "wind_speed_ms": "float",
    "rainfall": "bool",      # True if any rain during session
}
