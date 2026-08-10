"""Guard against the sugar nutrient-ID bug (1063 vs 2000).

1063 ("Sugars, Total") has almost no branded coverage; 2000 ("Total Sugars")
is the correct modern ID. FNDDS uses legacy nbr 269 (= modern 2000).

Reads processor source text so we never execute the full CSV pipelines.
"""

from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"


def _nutrient_ids_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index("NUTRIENT_IDS = {")
    end = text.index("\n}", start)
    return text[start:end]


def test_process_branded_sugar_uses_modern_id_2000_not_1063():
    block = _nutrient_ids_block(_SCRIPTS / "process_branded.py")
    assert '"2000": "sugar"' in block
    assert '"1063": "sugar"' not in block


def test_process_sr_legacy_sugar_uses_modern_id_2000_not_1063():
    block = _nutrient_ids_block(_SCRIPTS / "process_sr_legacy.py")
    assert '"2000": "sugar"' in block
    assert '"1063": "sugar"' not in block


def test_process_fndds_sugar_uses_legacy_nbr_269_not_1063():
    """FNDDS food_nutrient.csv uses legacy nbrs; 269 == modern Total Sugars 2000."""
    block = _nutrient_ids_block(_SCRIPTS / "process_fndds.py")
    assert '"269": "sugar"' in block
    assert '"1063": "sugar"' not in block
