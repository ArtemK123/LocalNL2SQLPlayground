"""BIRD minidev logical db_id list (= PostgreSQL schema names on full BIRD load)."""

MINIDEV_DB_IDS: tuple[str, ...] = (
    "california_schools",
    "card_games",
    "codebase_community",
    "debit_card_specializing",
    "european_football_2",
    "financial",
    "formula_1",
    "student_club",
    "superhero",
    "thrombosis_prediction",
    "toxicology",
)


def minidev_schemas_csv() -> str:
    return ",".join(MINIDEV_DB_IDS)
