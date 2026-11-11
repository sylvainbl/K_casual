import csv
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "owkin_take_home_data.csv"

with DATA_FILE.open(encoding="utf-8", newline="") as file:
    EXPRESSIONS: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(file):
        EXPRESSIONS.setdefault(row["cancer_indication"], {})[row["gene"]] = float(
            row["median_value"]
        )


def get_targets(cancer_name: str) -> list[str]:
    """Return the genes associated with this cancer in the dataset."""
    return list(EXPRESSIONS.get(cancer_name, {}))


def get_expressions(cancer_name: str, genes: list[str]) -> dict[str, float]:
    """Return the recorded expression medians for these genes in this cancer."""
    values = EXPRESSIONS.get(cancer_name, {})
    return {gene: values[gene] for gene in genes if gene in values}
