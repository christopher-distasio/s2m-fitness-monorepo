from backend.services.query_match_rank import branded_product_head, wrong_product_head


def test_product_word_the_user_did_not_say_is_flagged():
    assert wrong_product_head("califia farms almond milk", "ALMOND MILK CREAMER", "CALIFIA FARMS")
    assert wrong_product_head("cascadian farm granola", "CHEWY GRANOLA BARS", "CASCADIAN FARM")
    assert wrong_product_head("rice krispies treats", "TREAT DECORATING KIT", "RICE KRISPIES TREATS")


def test_describing_extras_are_not_flagged():
    assert not wrong_product_head(
        "califia farms almond milk", "Califia Farms Unsweetened Almond Milk", "Califia Farms")
    assert not wrong_product_head("rice krispies treats", "RICE CRISPY TREAT", "SELMA'S")
    assert not wrong_product_head("kind bar", "KIND, FRUIT & NUT BAR", "KIND")


def test_head_skips_brand_segment_and_sizes():
    assert branded_product_head("HEINZ, TEXAS STYLE BBQ SAUCE", "HEINZ") == "sauce"
    assert branded_product_head("Kellogg's Pop-Tarts Strawberry 22oz", "Kellogg's Pop-Tarts") == "strawberry"
    assert branded_product_head("NUTTER BUTTER COOKIES 1X1.75 OZ", "NUTTER BUTTER") == "cookies"


def test_generic_rows_are_never_flagged():
    assert not wrong_product_head("granola", "Cereals, granola, homemade", "")
