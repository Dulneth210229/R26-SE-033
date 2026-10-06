"""
Tests for app/agents/uiux_agent/revision_patcher.py -- the deterministic
"small ops plan -> apply to ui_metadata_json" patcher, mirroring
test_requirement_revision_patcher.py's own style. No LLM, no HTTP, pure Python.
"""

import copy

from app.agents.uiux_agent.revision_patcher import apply_uiux_revision_operations

METADATA = {
    "pages": [
        {
            "page_id": "item-listing-page",
            "name": "Item Listing Page",
            "route": "/items",
            "components": [
                {
                    "name": "ItemListingTable",
                    "reused_from_design_system": False,
                    "content_elements": ["item name", "item price"],
                    "covers_ui_expectations": ["UI-001"],
                },
                {
                    "name": "Pagination",
                    "reused_from_design_system": False,
                    "content_elements": ["page number", "total pages"],
                },
            ],
        },
        {
            "page_id": "item-details-page",
            "name": "Item Details Page",
            "route": "/items/:id",
            "components": [
                {
                    "name": "ItemDetailsPanel",
                    "reused_from_design_system": False,
                    "content_elements": ["item name", "item description"],
                },
            ],
        },
    ],
    "color_theme": "indigo",
}


def test_add_component_to_existing_page():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [
            {
                "action": "add",
                "page_id": "item-listing-page",
                "component_name": "EmptyStateBanner",
                "content_elements": ["no items found message"],
            }
        ],
    )

    listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
    names = [c["name"] for c in listing_page["components"]]
    assert "EmptyStateBanner" in names
    assert applied
    assert unmatched == []
    # Original components untouched.
    assert len(listing_page["components"]) == 3


def test_add_without_matching_page_is_unmatched():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [
            {
                "action": "add",
                "page_id": "nonexistent-page",
                "component_name": "Whatever",
                "content_elements": ["something"],
            }
        ],
    )

    assert applied == []
    assert unmatched
    # Original metadata unchanged.
    assert len(patched["pages"]) == 2


def test_add_duplicate_component_name_is_unmatched():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [
            {
                "action": "add",
                "page_id": "item-listing-page",
                "component_name": "Pagination",
                "content_elements": ["x"],
            }
        ],
    )

    assert applied == []
    assert unmatched
    listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
    assert len(listing_page["components"]) == 2


def test_remove_component_by_name_only():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [{"action": "remove", "component_name": "Pagination"}],
    )

    listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
    names = [c["name"] for c in listing_page["components"]]
    assert "Pagination" not in names
    assert applied
    assert unmatched == []


def test_remove_nonexistent_component_is_unmatched():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [{"action": "remove", "component_name": "DoesNotExist"}],
    )

    assert applied == []
    assert unmatched


def test_modify_component_content_elements():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [
            {
                "action": "modify",
                "component_name": "ItemListingTable",
                "content_elements": ["item name", "item price", "item stock"],
            }
        ],
    )

    listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
    table = next(c for c in listing_page["components"] if c["name"] == "ItemListingTable")
    assert table["content_elements"] == ["item name", "item price", "item stock"]
    assert applied
    assert unmatched == []


def test_modify_with_no_fields_to_change_is_unmatched():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [{"action": "modify", "component_name": "ItemListingTable"}],
    )

    assert applied == []
    assert unmatched


def test_modify_scoped_by_page_id_disambiguates_same_name_on_different_pages():
    metadata = copy.deepcopy(METADATA)
    metadata["pages"][1]["components"].append(
        {"name": "Pagination", "content_elements": ["x"], "reused_from_design_system": False}
    )

    patched, applied, unmatched = apply_uiux_revision_operations(
        metadata,
        [
            {
                "action": "modify",
                "page_id": "item-details-page",
                "component_name": "Pagination",
                "content_elements": ["details page pagination"],
            }
        ],
    )

    listing_pagination = next(
        c for c in patched["pages"][0]["components"] if c["name"] == "Pagination"
    )
    details_pagination = next(
        c for c in patched["pages"][1]["components"] if c["name"] == "Pagination"
    )
    assert listing_pagination["content_elements"] == ["page number", "total pages"]
    assert details_pagination["content_elements"] == ["details page pagination"]
    assert applied
    assert unmatched == []


def test_malformed_operation_is_skipped_not_raised():
    patched, applied, unmatched = apply_uiux_revision_operations(METADATA, ["not-a-dict", 42, None])

    assert applied == []
    assert len(unmatched) == 3
    assert patched["pages"] == METADATA["pages"]


def test_unsupported_action_is_unmatched():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [{"action": "replace_everything", "component_name": "ItemListingTable"}],
    )

    assert applied == []
    assert unmatched


def test_original_metadata_never_mutated():
    original = copy.deepcopy(METADATA)
    apply_uiux_revision_operations(
        METADATA,
        [{"action": "remove", "component_name": "Pagination"}],
    )
    assert METADATA == original


def test_multiple_operations_across_different_pages_in_one_call():
    patched, applied, unmatched = apply_uiux_revision_operations(
        METADATA,
        [
            {"action": "remove", "component_name": "Pagination"},
            {
                "action": "modify",
                "component_name": "ItemDetailsPanel",
                "content_elements": ["item name", "item description", "item price"],
            },
            {
                "action": "add",
                "page_id": "item-listing-page",
                "component_name": "SortDropdown",
                "content_elements": ["sort order"],
            },
        ],
    )

    assert len(applied) == 3
    assert unmatched == []

    listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
    listing_names = [c["name"] for c in listing_page["components"]]
    assert "Pagination" not in listing_names
    assert "SortDropdown" in listing_names

    details_page = next(p for p in patched["pages"] if p["page_id"] == "item-details-page")
    details_panel = next(c for c in details_page["components"] if c["name"] == "ItemDetailsPanel")
    assert details_panel["content_elements"] == ["item name", "item description", "item price"]


def test_add_marks_component_as_revision_touched_transiently():
    patched, _applied, _unmatched = apply_uiux_revision_operations(
        METADATA,
        [
            {
                "action": "add",
                "page_id": "item-listing-page",
                "component_name": "NewOne",
                "content_elements": ["x"],
            }
        ],
    )
    listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
    new_component = next(c for c in listing_page["components"] if c["name"] == "NewOne")
    assert new_component["_revision_touched"] is True


def test_modify_marks_component_as_revision_touched_transiently():
    patched, _applied, _unmatched = apply_uiux_revision_operations(
        METADATA,
        [
            {
                "action": "modify",
                "component_name": "ItemListingTable",
                "content_elements": ["item name"],
            }
        ],
    )
    listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
    table = next(c for c in listing_page["components"] if c["name"] == "ItemListingTable")
    assert table["_revision_touched"] is True


def test_remove_does_not_mark_any_component_as_touched():
    patched, _applied, _unmatched = apply_uiux_revision_operations(
        METADATA,
        [{"action": "remove", "component_name": "Pagination"}],
    )
    for page in patched["pages"]:
        for component in page["components"]:
            assert "_revision_touched" not in component


class TestAllowedPageIds:
    """
    Real, confirmed gap this locks in: target_page_ids was previously only a soft prompt hint --
    a real local model could (and, per the reported bug, did) apply operations to pages outside
    what the human selected. allowed_page_ids is the deterministic, hard enforcement: an
    operation resolving to a page outside the selected set is rejected into `unmatched`, never
    silently applied and never silently dropped.
    """

    def test_modify_on_selected_page_applies(self):
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [{"action": "modify", "component_name": "ItemListingTable", "content_elements": ["x"]}],
            allowed_page_ids={"item-listing-page"},
        )

        listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
        table = next(c for c in listing_page["components"] if c["name"] == "ItemListingTable")
        assert table["content_elements"] == ["x"]
        assert applied
        assert unmatched == []

    def test_modify_on_unselected_page_is_rejected_not_applied(self):
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [{"action": "modify", "component_name": "ItemDetailsPanel", "content_elements": ["changed"]}],
            allowed_page_ids={"item-listing-page"},
        )

        details_page = next(p for p in patched["pages"] if p["page_id"] == "item-details-page")
        panel = next(c for c in details_page["components"] if c["name"] == "ItemDetailsPanel")
        # Untouched -- the operation targeted a page outside the selected set.
        assert panel["content_elements"] == ["item name", "item description"]
        assert applied == []
        assert unmatched
        assert "item-details-page" in unmatched[0]
        assert "not one of the pages selected" in unmatched[0]

    def test_remove_on_unselected_page_is_rejected(self):
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [{"action": "remove", "component_name": "ItemDetailsPanel"}],
            allowed_page_ids={"item-listing-page"},
        )

        details_page = next(p for p in patched["pages"] if p["page_id"] == "item-details-page")
        names = [c["name"] for c in details_page["components"]]
        assert "ItemDetailsPanel" in names
        assert applied == []
        assert unmatched

    def test_add_to_unselected_page_is_rejected(self):
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [
                {
                    "action": "add",
                    "page_id": "item-details-page",
                    "component_name": "NewThing",
                    "content_elements": ["x"],
                }
            ],
            allowed_page_ids={"item-listing-page"},
        )

        details_page = next(p for p in patched["pages"] if p["page_id"] == "item-details-page")
        names = [c["name"] for c in details_page["components"]]
        assert "NewThing" not in names
        assert applied == []
        assert unmatched

    def test_mixed_operations_only_selected_page_ones_apply(self):
        """One operation on a selected page, one on an unselected page, in the same call --
        the selected one applies, the other is rejected, neither affects the other."""
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [
                {"action": "remove", "component_name": "Pagination"},  # on item-listing-page
                {
                    "action": "modify",
                    "component_name": "ItemDetailsPanel",  # on item-details-page
                    "content_elements": ["should not apply"],
                },
            ],
            allowed_page_ids={"item-listing-page"},
        )

        listing_page = next(p for p in patched["pages"] if p["page_id"] == "item-listing-page")
        assert "Pagination" not in [c["name"] for c in listing_page["components"]]

        details_page = next(p for p in patched["pages"] if p["page_id"] == "item-details-page")
        panel = next(c for c in details_page["components"] if c["name"] == "ItemDetailsPanel")
        assert panel["content_elements"] == ["item name", "item description"]

        assert len(applied) == 1
        assert len(unmatched) == 1

    def test_multiple_selected_pages_both_allowed(self):
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [
                {"action": "remove", "component_name": "Pagination"},
                {
                    "action": "modify",
                    "component_name": "ItemDetailsPanel",
                    "content_elements": ["updated"],
                },
            ],
            allowed_page_ids={"item-listing-page", "item-details-page"},
        )

        assert len(applied) == 2
        assert unmatched == []

    def test_none_allowed_page_ids_is_unconstrained(self):
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [{"action": "remove", "component_name": "ItemDetailsPanel"}],
            allowed_page_ids=None,
        )

        assert applied
        assert unmatched == []

    def test_empty_set_allowed_page_ids_is_unconstrained(self):
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [{"action": "remove", "component_name": "ItemDetailsPanel"}],
            allowed_page_ids=set(),
        )

        assert applied
        assert unmatched == []

    def test_page_id_matching_is_case_and_whitespace_insensitive(self):
        """Matches _normalize's own established behavior for every other match in this patcher."""
        patched, applied, unmatched = apply_uiux_revision_operations(
            METADATA,
            [{"action": "remove", "component_name": "Pagination"}],
            allowed_page_ids={"  Item-Listing-Page  "},
        )

        assert applied
        assert unmatched == []
