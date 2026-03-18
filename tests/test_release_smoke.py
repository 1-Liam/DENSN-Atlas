from __future__ import annotations

from densn.constraints import ConstraintEngine
from densn.graph import PersistentGraph
from densn.memory import OntologyRegistry
from densn.proof_contract import CORE_API_VERSION
from densn.proposal_review import ArtifactStructuralProposalReviewer
from densn.records import MetaSymbol
from densn.system import DENSNSystem
from densn.tsl import TSLEngine


def test_default_system_uses_frozen_core_contract() -> None:
    system = DENSNSystem(PersistentGraph())

    contract = system.core_contract()

    assert contract["core_mode"] == "core_frozen"
    assert contract["core_api_version"] == CORE_API_VERSION
    assert contract["expected_core_api_version"] == CORE_API_VERSION


def test_pathway_b_triggers_on_persistent_high_tension() -> None:
    tsl = TSLEngine(ConstraintEngine())

    assert tsl.should_trigger_pathway_b(
        {
            "psi": 8.0,
            "plateaued": True,
            "top_hotspot_persistence": 6.0,
            "hotspot_recurrence": 3,
            "proposal_support": 0.0,
        }
    )

    assert not tsl.should_trigger_pathway_b(
        {
            "psi": 2.0,
            "plateaued": True,
            "top_hotspot_persistence": 0.0,
            "hotspot_recurrence": 0,
            "proposal_support": 0.0,
        }
    )


def test_registry_finds_role_remap_candidates_via_canonical_roles() -> None:
    registry = OntologyRegistry()
    meta_symbol = MetaSymbol(
        id="meta_test",
        structural_name="META_TEST",
        interface_kind="exact",
        parent_cluster_symbol_ids=["s_open", "s_close"],
        markov_blanket_symbol_ids=["s_write"],
        admission_status="accepted",
    )
    registry.record_candidate(meta_symbol)
    registry.admit(meta_symbol.id, "accepted:test")
    registry.mark_reuse_signature(
        meta_symbol.id,
        parent_roles=["grant", "revoke"],
        blanket_roles=["charge"],
        retired_constraint_signatures=[{"kind": "xor", "roles": ["grant", "revoke"]}],
        canonical_parent_roles=["open", "close"],
        canonical_blanket_roles=["write"],
        canonical_retired_constraint_signatures=[{"kind": "xor", "roles": ["open", "close"]}],
    )

    matches = registry.find_reusable_candidates(
        available_roles=["begin", "end", "mutate"],
        constraint_signatures=[{"kind": "xor", "roles": ["begin", "end"]}],
        available_canonical_roles=["open", "close", "write"],
        canonical_constraint_signatures=[{"kind": "xor", "roles": ["open", "close"]}],
    )

    assert len(matches) == 1
    assert matches[0]["reuse_match"]["mapping_class"] == "role_remap"
    assert matches[0]["reuse_match"]["role_field"] == "canonical_role"


def test_real_world_strict_reviewer_policy_is_loaded() -> None:
    reviewer = ArtifactStructuralProposalReviewer(policy="real_world_strict")

    assert reviewer.policy.name == "real_world_strict"
    assert reviewer.policy.reject_shadowed_atoms is True
    assert reviewer.policy.abstain_all_semantic_labels is True
    assert reviewer.policy.abstain_parent_only_tests is True
