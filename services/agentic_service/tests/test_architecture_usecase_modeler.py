"""
Unit tests for ArchitectureUseCaseModeler (app/agents/architecture_agent/usecase_modeler.py).
No LLM involved -- these exercise the deterministic modeling logic directly.

Covers the two build() paths:
- LLM-specification path (specification["use_cases"] non-empty): the
  modeler must trust the LLM's names/categorization directly (no regex
  phrase-surgery) and merge near-duplicates via the three-pass
  _merge_near_duplicates (exact name, shared related_requirements, name
  stem similarity).
- Fallback path (specification empty): the last-resort deterministic
  builder must produce a clean main use case named from feature_name
  alone (no business-goal regex-mangling) and honest, non-garbled
  supporting use case names (via _build_fallback_supporting_use_case).

These fixtures are based on the real, confirmed-garbled examples recorded
in the approved rewrite plan (Task Comments, Login) to directly verify
those failure modes no longer occur.
"""

from app.agents.architecture_agent.usecase_modeler import ArchitectureUseCaseModeler


def _relationships_by_type(usecase_json: dict, relation_type: str) -> list[dict]:
    return [r for r in usecase_json["relationships"] if r["type"] == relation_type]


def _names(use_cases: list[dict]) -> list[str]:
    return [uc["name"] for uc in use_cases]


class TestLlmSpecificationPath:
    def test_trusts_llm_names_and_categorization_directly(self):
        modeler = ArchitectureUseCaseModeler()

        srs_json = {
            "feature_name": "Task Comments",
            "user_roles": ["Team Member"],
            "functional_requirements": [
                {"id": "FR-001", "description": "Users can add a comment to a task."},
                {"id": "FR-002", "description": "Users can view comments on a task."},
                {"id": "FR-003", "description": "Users can delete their own comment."},
            ],
        }
        sds_json = {"design_views": {}}
        specification = {
            "system_boundary": "Task Comments",
            "diagram_title": "Task Comments Use Case Diagram",
            "actors": [{"name": "Team Member", "type": "primary"}],
            "use_cases": [
                {
                    "name": "Discuss Task",
                    "type": "main",
                    "description": "A team member discusses a task via comments.",
                    "related_requirements": ["FR-001", "FR-002"],
                },
                {
                    "name": "Add Comment",
                    "type": "included",
                    "description": "Add a comment to a task.",
                    "related_requirements": ["FR-001"],
                },
                {
                    "name": "View Comments",
                    "type": "included",
                    "description": "View comments on a task.",
                    "related_requirements": ["FR-002"],
                },
                {
                    "name": "Delete Own Comment",
                    "type": "extension",
                    "description": "Delete a comment the user authored.",
                    "related_requirements": ["FR-003"],
                },
            ],
        }

        analysis, usecase_json = modeler.build(
            srs_json=srs_json, sds_json=sds_json, usecase_specification_json=specification
        )

        names = _names(usecase_json["use_cases"])

        # The confirmed real garbled examples ("A Task The Can", "A Comment
        # The Authored") must never appear -- names are trusted as-is.
        assert "Discuss Task" in names
        assert "Add Comment" in names
        assert "View Comments" in names
        assert "Delete Own Comment" in names
        for name in names:
            assert "The Can" not in name
            assert "The Authored" not in name

        main = [uc for uc in usecase_json["use_cases"] if uc["category"] == "main"]
        assert len(main) == 1
        assert main[0]["name"] == "Discuss Task"

    def test_merges_exact_duplicate_names(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Search", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "use_cases": [
                {"name": "Search Tasks", "type": "main", "related_requirements": ["FR-001"]},
                {"name": "Filter Results", "type": "included", "related_requirements": ["FR-002"]},
                {"name": "filter results", "type": "included", "related_requirements": ["FR-003"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert len(included) == 1
        assert set(included[0]["related_requirements"]) == {"FR-002", "FR-003"}

    def test_merges_use_cases_sharing_identical_related_requirements(self):
        """
        Real confirmed near-duplicate: "Initiate Forgot Password Process" vs
        "Initiate Recovery Flow" citing the same FR -- no string-similarity
        metric would catch this (they share no meaningful stems), but citing
        the exact same requirement id set is a strong duplicate signal.
        """
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Login", "functional_requirements": [{"id": "FR-005", "description": "x"}]}
        specification = {
            "use_cases": [
                {"name": "Login", "type": "main", "related_requirements": ["FR-001"]},
                {
                    "name": "Initiate Forgot Password Process",
                    "type": "extension",
                    "related_requirements": ["FR-005"],
                },
                {
                    "name": "Initiate Recovery Flow",
                    "type": "extension",
                    "related_requirements": ["FR-005"],
                },
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        extensions = [uc for uc in usecase_json["use_cases"] if uc["category"] == "extension"]
        assert len(extensions) == 1
        assert extensions[0]["related_requirements"] == ["FR-005"]

    def test_merges_near_duplicate_names_by_stem_overlap(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Checkout", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "use_cases": [
                {"name": "Checkout", "type": "main", "related_requirements": ["FR-001"]},
                {"name": "Apply Discount Coupon", "type": "included", "related_requirements": ["FR-010"]},
                {"name": "Apply Discount Coupons", "type": "included", "related_requirements": ["FR-011"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert len(included) == 1
        assert set(included[0]["related_requirements"]) == {"FR-010", "FR-011"}

    def test_promotes_a_main_use_case_when_llm_produced_none(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Search", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "use_cases": [
                {"name": "Filter Results", "type": "included", "related_requirements": ["FR-001"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        main = [uc for uc in usecase_json["use_cases"] if uc["category"] == "main"]
        assert len(main) == 1
        assert main[0]["name"] == "Filter Results"

    def test_keeps_two_main_entries_with_disjoint_related_requirements_as_independent_siblings(self):
        # Real, confirmed bug this fixes: two main-typed entries for GENUINELY DIFFERENT
        # capabilities (disjoint related_requirements -- e.g. "Add Item"/"List Items", each citing
        # its own FR) used to always get folded into one main + one <<include>> child, inventing a
        # false "listing happens as part of adding" relationship. Disjoint related_requirements is
        # the real, confirmed signal these are two independent top-level goals, not one goal
        # double-marked -- both must survive as their own main use case.
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Item Management",
            "functional_requirements": [
                {"id": "FR-001", "description": "x"},
                {"id": "FR-002", "description": "y"},
            ],
        }
        specification = {
            "use_cases": [
                {"name": "Add Item", "type": "main", "related_requirements": ["FR-001"]},
                {"name": "List Items", "type": "main", "related_requirements": ["FR-002"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        main = [uc for uc in usecase_json["use_cases"] if uc["category"] == "main"]
        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert _names(main) == ["Add Item", "List Items"]
        assert included == []
        # No invented include/extend edge between the two independent main use cases.
        relationships = usecase_json["relationships"]
        main_ids = {uc["id"] for uc in main}
        assert not any(
            r["type"] in ("include", "extend") and r["from"] in main_ids and r["to"] in main_ids
            for r in relationships
        )

    def test_folds_extra_main_entries_with_overlapping_related_requirements_into_included(self):
        # The other half of the same fix: two main-typed entries that overlap (or one/both have
        # EMPTY related_requirements) are still the "LLM sloppily double-marked one thing as main"
        # case -- these still collapse to one main + one included child, exactly as before.
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Search", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "use_cases": [
                {"name": "Search Tasks", "type": "main", "related_requirements": ["FR-001"]},
                {"name": "Export Results", "type": "main", "related_requirements": ["FR-001"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        main = [uc for uc in usecase_json["use_cases"] if uc["category"] == "main"]
        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert len(main) == 1
        assert main[0]["name"] == "Search Tasks"
        assert "Export Results" in _names(included)


class TestParticipatingActorsAndGeneralization:
    def test_actor_is_associated_only_with_the_use_case_it_participates_in(self):
        # Real gap this fixes: previously EVERY actor was hardwired to the single main use case
        # only, even when it genuinely only participates in an extension use case's own logic.
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Process Return", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "actors": [{"name": "Customer", "type": "primary"}, {"name": "Admin", "type": "secondary"}],
            "use_cases": [
                {
                    "name": "Process Return", "type": "main", "related_requirements": ["FR-001"],
                    "participating_actors": ["Customer"],
                },
                {
                    "name": "Approve High Value Refund", "type": "extension", "related_requirements": ["FR-002"],
                    "participating_actors": ["Admin"],
                },
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        customer_id = next(a["id"] for a in usecase_json["actors"] if a["name"] == "Customer")
        admin_id = next(a["id"] for a in usecase_json["actors"] if a["name"] == "Admin")
        main_id = next(uc["id"] for uc in usecase_json["use_cases"] if uc["category"] == "main")
        extension_id = next(uc["id"] for uc in usecase_json["use_cases"] if uc["category"] == "extension")

        associations = {(r["from"], r["to"]) for r in _relationships_by_type(usecase_json, "association")}
        assert (customer_id, main_id) in associations
        assert (admin_id, extension_id) in associations
        # Admin never directly participates in the main use case's own logic.
        assert (admin_id, main_id) not in associations

    def test_main_use_case_with_no_explicit_participating_actors_still_gets_every_actor(self):
        # Backward-compatible default: an LLM (or the deterministic fallback) that omits
        # participating_actors on the main use case still produces a usable diagram.
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Search", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "actors": [{"name": "Customer", "type": "primary"}],
            "use_cases": [{"name": "Search", "type": "main", "related_requirements": ["FR-001"]}],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        associations = _relationships_by_type(usecase_json, "association")
        assert len(associations) == 1

    def test_use_case_generalization_relationship_is_built(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Make Payment", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "actors": [{"name": "Customer", "type": "primary"}],
            "use_cases": [
                {"name": "Make Payment", "type": "main", "related_requirements": ["FR-001"], "participating_actors": ["Customer"]},
                {
                    "name": "Pay By Card", "type": "included", "related_requirements": ["FR-002"],
                    "participating_actors": ["Customer"], "generalizes": "Make Payment",
                },
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        main_id = next(uc["id"] for uc in usecase_json["use_cases"] if uc["name"] == "Make Payment")
        child_id = next(uc["id"] for uc in usecase_json["use_cases"] if uc["name"] == "Pay By Card")

        generalizations = _relationships_by_type(usecase_json, "generalization")
        assert {"from": child_id, "to": main_id, "type": "generalization", "label": "", "related_requirements": []} in generalizations

    def test_actor_generalization_relationship_is_built(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Manage Account", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "actors": [
                {"name": "User", "type": "primary"},
                {"name": "Admin", "type": "secondary", "generalizes": "User"},
            ],
            "use_cases": [{"name": "Manage Account", "type": "main", "related_requirements": ["FR-001"]}],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        user_id = next(a["id"] for a in usecase_json["actors"] if a["name"] == "User")
        admin_id = next(a["id"] for a in usecase_json["actors"] if a["name"] == "Admin")

        generalizations = _relationships_by_type(usecase_json, "generalization")
        assert {"from": admin_id, "to": user_id, "type": "generalization", "label": "", "related_requirements": []} in generalizations

    def test_system_actor_stereotype_is_carried_through(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Send Notification", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "actors": [
                {"name": "Customer", "type": "primary", "stereotype": "human"},
                {"name": "Email Provider", "type": "secondary", "stereotype": "system"},
            ],
            "use_cases": [{"name": "Send Notification", "type": "main", "related_requirements": ["FR-001"]}],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        customer = next(a for a in usecase_json["actors"] if a["name"] == "Customer")
        email_provider = next(a for a in usecase_json["actors"] if a["name"] == "Email Provider")
        assert customer["stereotype"] == "human"
        assert email_provider["stereotype"] == "system"

    def test_external_systems_from_context_view_default_to_system_stereotype(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Checkout", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        sds_json = {"design_views": {"context_view": {"external_systems": ["Stripe"]}}}

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json=sds_json, usecase_specification_json={})

        stripe = next(a for a in usecase_json["actors"] if a["name"] == "Stripe")
        assert stripe["stereotype"] == "system"


class TestFallbackPath:
    def test_main_use_case_named_from_feature_name_only(self):
        """
        The fallback path must never regex-mangle a business_goal sentence
        into the main use case name -- feature_name is already a reasonable,
        conventional UML use case name (e.g. "Login").
        """
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Login",
            "business_goal": "Allow registered users to authenticate using their credentials.",
            "functional_requirements": [{"id": "FR-001", "description": "x"}],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json={})

        main = [uc for uc in usecase_json["use_cases"] if uc["category"] == "main"]
        assert len(main) == 1
        assert main[0]["name"] == "Login"

    def test_fallback_supporting_use_case_uses_matching_user_story_goal(self):
        """
        _build_fallback_supporting_use_case's naming logic is exercised via
        an explicit included_behaviours entry (a real, even if partial, LLM
        specification signal) -- NOT via mechanically converting every raw
        functional_requirements item, which was a real, confirmed bug (see
        _build_included_use_cases' own docstring: a genuine "Login and
        Signup" run produced spurious <<include>> relationships to garbled
        fragments like "Email Must Be In Valid" for validation rules that
        are not use cases at all).
        """
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Login",
            "user_stories": [
                {"id": "US-001", "role": "User", "goal": "Authenticate with my credentials", "benefit": "access my account"},
            ],
            "functional_requirements": [
                {"id": "FR-001", "description": "The system must validate the user credentials against stored records."},
            ],
        }
        specification = {
            "included_behaviours": [
                {"description": "The system must validate the user credentials against stored records.", "related_requirements": ["FR-001"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert len(included) == 1
        assert included[0]["name"] == "Authenticate With Credentials"

    def test_fallback_supporting_use_case_falls_back_to_gentle_truncation(self):
        """
        No matching user story -- a single gentle pass (strip boilerplate
        lead-in, keep ~5 words, title-case) via _clean_use_case_name, not
        multi-pass regex verb/topic extraction.
        """
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Login",
            "user_stories": [],
            "functional_requirements": [
                {"id": "FR-001", "description": "The system must validate the user credentials against stored records."},
            ],
        }
        specification = {
            "included_behaviours": [
                {"description": "The system must validate the user credentials against stored records.", "related_requirements": ["FR-001"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert len(included) == 1
        # No leftover article/pronoun fragment words in the fallback name.
        name_words = {w.lower() for w in included[0]["name"].split()}
        assert not name_words & {"the", "a", "an", "this", "that"}

    def test_fallback_preserves_full_fr_traceability(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Login",
            "functional_requirements": [
                {"id": "FR-001", "description": "The system must validate the user credentials."},
                {"id": "FR-002", "description": "The system must display an error for invalid credentials."},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json={})

        covered_ids: set[str] = set()
        for uc in usecase_json["use_cases"]:
            covered_ids.update(uc.get("related_requirements", []))
        assert {"FR-001", "FR-002"}.issubset(covered_ids)

    def test_fallback_relationships_are_correctly_wired(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Login",
            "functional_requirements": [
                {"id": "FR-001", "description": "The system must validate the user credentials."},
                {"id": "FR-002", "description": "The system must display an error for invalid credentials."},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json={})

        main_id = next(uc["id"] for uc in usecase_json["use_cases"] if uc["category"] == "main")

        for rel in _relationships_by_type(usecase_json, "include"):
            assert rel["from"] == main_id

        for rel in _relationships_by_type(usecase_json, "extend"):
            assert rel["to"] == main_id

        for rel in _relationships_by_type(usecase_json, "association"):
            assert rel["to"] == main_id

    def test_fallback_does_not_mechanically_turn_validation_rules_into_use_cases(self):
        """
        Regression test for a real, confirmed bug: a genuine "Login and
        Signup" run (every LLM generation rung failed, falling through to
        this deterministic last-resort path) produced 6 <<include>>
        relationships to garbled fragments like "Email Must Be In Valid"
        (from validation rule "Email must be in a valid format") and 6
        <<extend>> relationships to fragments like "Invalid Login
        Credentials Wrong Email" -- validation rules and raw requirement
        sentences are not real, distinct, user-observable use cases under
        any UML convention. With no explicit included_behaviours/
        extension_behaviours/exception_flows in the specification, the
        fallback must produce ONLY the main use case, with full FR/AC/VR
        traceability folded into its own related_requirements instead.
        """
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Login and Signup",
            "functional_requirements": [
                {"id": "FR-001", "description": "User can enter email and password into the login form"},
                {"id": "FR-003", "description": "System validates the input (both fields required, email format correct)"},
            ],
            "acceptance_criteria": [
                {"id": "AC-004", "description": "Given invalid login credentials, when the user submits the login form, then they see a generic error"},
            ],
            "validation_rules": [
                {"id": "VR-001", "description": "Email must be in a valid format."},
                {"id": "VR-002", "description": "Password must meet minimum strength requirements."},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json={})

        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        extension = [uc for uc in usecase_json["use_cases"] if uc["category"] == "extension"]
        assert included == []
        assert extension == []
        assert _relationships_by_type(usecase_json, "include") == []
        assert _relationships_by_type(usecase_json, "extend") == []

        main = [uc for uc in usecase_json["use_cases"] if uc["category"] == "main"][0]
        for req_id in ["FR-001", "FR-003", "AC-004", "VR-001", "VR-002"]:
            assert req_id in main["related_requirements"]


class TestActorNameCleanup:
    """
    _clean_actor_name -- the real, confirmed bug this closes: an LLM-authored actor name that
    reads as a full sentence ("An Image Hosting Solution To Store Uploaded Images.") passed
    through unchanged before this fix (only _title_case was ever applied to actor names).
    """

    def test_strips_trailing_sentence_punctuation_and_caps_at_four_words(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Add & List Items", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {
            "actors": [{"name": "An Image Hosting Solution To Store Uploaded Images.", "stereotype": "system"}],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        actor_names = _names(usecase_json["actors"])
        assert "An Image Hosting Solution To Store Uploaded Images." not in actor_names
        # Filler word "an" stripped, capped at 4 remaining words, no trailing period.
        assert actor_names == ["Image Hosting Solution To"]
        assert not actor_names[0].endswith(".")

    def test_leaves_a_clean_short_actor_name_unchanged(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {"feature_name": "Checkout", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        specification = {"actors": [{"name": "Payment Gateway", "stereotype": "system"}]}

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        assert [a["name"] for a in usecase_json["actors"]] == ["Payment Gateway"]

    def test_cleanup_applies_to_srs_user_roles_fallback_source_too(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Checkout",
            "functional_requirements": [{"id": "FR-001", "description": "x"}],
            "user_roles": ["The Customer Who Is Checking Out."],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json={})

        actor_names = [a["name"] for a in usecase_json["actors"]]
        assert "The Customer Who Is Checking Out." not in actor_names
        assert actor_names[0].split() and len(actor_names[0].split()) <= 4


class TestDistinctCapabilityMergeGuard:
    """
    _dedupe_by_shared_requirements' new verb-mismatch guard -- the real, confirmed mechanism that
    could silently fuse two genuinely different capabilities (e.g. "Add Item"/"List Items") into
    one entry if the SRS/LLM cited an identical related_requirements set for both.
    """

    def test_does_not_merge_different_capability_verbs_sharing_one_requirement_id(self):
        # Named "Manage Items" as the main use case (a decoy, distinct from the merge guard being
        # tested) so the two "included" entries below aren't auto-promoted to fill an empty main
        # slot -- isolating _dedupe_by_shared_requirements' own behavior specifically.
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Item Management",
            "functional_requirements": [{"id": "FR-001", "description": "Add and list items"}],
        }
        specification = {
            "use_cases": [
                {"name": "Manage Items", "type": "main", "related_requirements": ["FR-001"]},
                {"name": "Add Item", "type": "included", "related_requirements": ["FR-001"]},
                {"name": "List Items", "type": "included", "related_requirements": ["FR-001"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert sorted(_names(included)) == ["Add Item", "List Items"]

    def test_still_merges_same_capability_names_sharing_one_requirement_id(self):
        # The existing, still-required behavior this guard must not break: two entries starting
        # with the SAME (or no curated) verb, sharing one requirement id, are still merged. A
        # decoy main use case keeps the two "included" entries from being auto-promoted to fill an
        # empty main slot, isolating the merge behavior itself.
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Password Recovery",
            "functional_requirements": [{"id": "FR-001", "description": "Recover account access"}],
        }
        specification = {
            "use_cases": [
                {"name": "Recover Account Access", "type": "main", "related_requirements": ["FR-001"]},
                {"name": "Initiate Password Reset", "type": "included", "related_requirements": ["FR-001"]},
                {"name": "Initiate Recovery Flow", "type": "included", "related_requirements": ["FR-001"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        included = [uc for uc in usecase_json["use_cases"] if uc["category"] == "included"]
        assert len(included) == 1


class TestClosestMainUseCaseAssignment:
    """
    _closest_main_use_case -- with multiple independent main use cases (per the relaxed demotion
    logic above), an included/extension use case's include/extend edge must point at whichever
    main it actually shares related_requirements with, not always the first main.
    """

    def test_included_use_case_connects_to_the_main_it_shares_requirements_with(self):
        modeler = ArchitectureUseCaseModeler()
        srs_json = {
            "feature_name": "Item Management",
            "functional_requirements": [
                {"id": "FR-001", "description": "Add item"},
                {"id": "FR-002", "description": "List items"},
            ],
        }
        specification = {
            "use_cases": [
                {"name": "Add Item", "type": "main", "related_requirements": ["FR-001"]},
                {"name": "List Items", "type": "main", "related_requirements": ["FR-002"]},
                {"name": "Filter Item List", "type": "included", "related_requirements": ["FR-002"]},
            ],
        }

        _, usecase_json = modeler.build(srs_json=srs_json, sds_json={"design_views": {}}, usecase_specification_json=specification)

        by_name = {uc["name"]: uc for uc in usecase_json["use_cases"]}
        include_edges = _relationships_by_type(usecase_json, "include")
        assert len(include_edges) == 1
        assert include_edges[0]["from"] == by_name["List Items"]["id"]
        assert include_edges[0]["to"] == by_name["Filter Item List"]["id"]
