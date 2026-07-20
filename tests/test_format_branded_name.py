from backend.services.nutrition_service import format_branded_name


def test_skips_prepend_when_name_already_contains_brand():
    assert (
        format_branded_name("GREAT VALUE POTATO CHIPS", "GREAT VALUE")
        == "GREAT VALUE POTATO CHIPS"
    )


def test_case_insensitive():
    assert (
        format_branded_name("Great Value Potato Chips", "GREAT VALUE")
        == "Great Value Potato Chips"
    )


def test_prepends_when_brand_absent():
    assert (
        format_branded_name("POTATO CHIPS", "GREAT VALUE")
        == "GREAT VALUE POTATO CHIPS"
    )


def test_empty_brand_returns_name():
    assert format_branded_name("Banana", "") == "Banana"
    assert format_branded_name("Banana", None) == "Banana"


def test_skips_owner_double_when_name_starts_with_owner():
    assert (
        format_branded_name(
            "Wal-Mart Stores, Inc. GREAT VALUE, POTATO CHIPS",
            "Wal-Mart Stores, Inc.",
        )
        == "Wal-Mart Stores, Inc. GREAT VALUE, POTATO CHIPS"
    )
