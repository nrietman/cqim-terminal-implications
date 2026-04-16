"""
CQIM v14.1 — Advanced Logical-Equivalence Quotient Layer
=========================================================

Pre-recursion canonicalization that detects and collapses logically
equivalent graph structures before the engine runs.

Pipeline:  G → quotient(G) → run_atlas → σ* → lift(σ*, map)

Equivalence classes handled:
  Pass 1: Self-loops (source == target)
  Pass 2: Duplicate paths (same source, target, type → merge)
  Pass 3: Alias nodes (identical coupling profile + evidence → merge)
  Pass 4: Redundant intermediaries (pure supporting relay nodes → bypass)
  Pass 5: Polarity-preserving nonlocal refactorization (split nodes → merge)
  Pass 6: Mixed support/defeat multi-step decomposition (mixed relay → net coupling)
  Pass 7: Necessity-preserving rewrites (redundant supporting beside necessary → remove)
  Pass 8: Distributed alias structures (cliques/chains of fractional nodes → merge)

The quotient layer is a pure pre-processor. The engine (run_atlas,
compute_theta_global, energy gate) is untouched. All v13 guarantees
(monotone descent, gate, convergence) still hold.

Author: Nathan Robert Rietmann, Rietmann Intelligence LLC
"""

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class QuotientMap:
    """Records the mapping from original graph to quotient graph."""
    condition_map: Dict[str, str] = field(default_factory=dict)
    equivalence_classes: Dict[str, Set[str]] = field(default_factory=dict)
    removed_intermediaries: Dict[str, dict] = field(default_factory=dict)
    operations: List[str] = field(default_factory=list)

    @property
    def n_merges(self):
        return sum(1 for s in self.equivalence_classes.values() if len(s) > 1)

    @property
    def n_removals(self):
        return len(self.removed_intermediaries)


# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _coupling_signature(cid, couplings, conditions):
    """
    Compute a canonical signature for a condition based on its coupling
    profile and intrinsic properties. Two conditions with the same
    signature are logically equivalent (aliases).
    """
    cond = conditions[cid]
    incoming = []
    outgoing = []
    for c in couplings:
        if c.target == cid:
            incoming.append((c.source, c.type, round(c.strength, 6)))
        if c.source == cid:
            outgoing.append((c.target, c.type, round(c.strength, 6)))
    incoming.sort()
    outgoing.sort()
    sig = (
        tuple(incoming),
        tuple(outgoing),
        round(cond.evidence, 6),
        round(cond.evidence_weight, 6),
        cond.polarity,
        round(cond.weight, 6),
    )
    return sig


def _is_pure_relay(cid, couplings, conditions):
    """
    Check if a condition is a pure relay: exactly one incoming supporting
    coupling, exactly one outgoing supporting coupling, no evidence, and
    no other couplings.
    """
    cond = conditions[cid]
    if cond.evidence_weight > 0:
        return False

    incoming = [c for c in couplings if c.target == cid]
    outgoing = [c for c in couplings if c.source == cid]

    if len(incoming) != 1 or len(outgoing) != 1:
        return False

    inc = incoming[0]
    out = outgoing[0]

    if inc.type != "supporting" or out.type != "supporting":
        return False

    if inc.source == out.target:
        return False

    return True


def _is_mixed_relay(cid, couplings, conditions):
    """
    Check if a condition is a mixed-type relay: exactly one incoming and
    one outgoing coupling, no evidence, where the types are mixed
    (one supporting, one defeating). The net effect is a single defeating
    coupling.
    """
    cond = conditions[cid]
    if cond.evidence_weight > 0:
        return False

    incoming = [c for c in couplings if c.target == cid]
    outgoing = [c for c in couplings if c.source == cid]

    if len(incoming) != 1 or len(outgoing) != 1:
        return False

    inc = incoming[0]
    out = outgoing[0]

    types = {inc.type, out.type}
    if types != {"supporting", "defeating"}:
        return False

    if inc.source == out.target:
        return False

    return True


def _get_external_targets(cid, couplings, exclude_cids):
    """Get the set of (target, type, strength) for outgoing couplings
    from cid that don't go to any node in exclude_cids."""
    result = set()
    for c in couplings:
        if c.source == cid and c.target not in exclude_cids:
            result.add((c.target, c.type, round(c.strength, 6)))
    return result


def _get_external_sources(cid, couplings, exclude_cids):
    """Get the set of (source, type, strength) for incoming couplings
    to cid that don't come from any node in exclude_cids."""
    result = set()
    for c in couplings:
        if c.target == cid and c.source not in exclude_cids:
            result.add((c.source, c.type, round(c.strength, 6)))
    return result


def _dedup_couplings(couplings):
    """Remove self-loops and merge duplicate paths (max strength)."""
    couplings = [c for c in couplings if c.source != c.target]
    path_groups = defaultdict(list)
    for c in couplings:
        key = (c.source, c.target, c.type)
        path_groups[key].append(c)
    merged = []
    for key, group in path_groups.items():
        if len(group) == 1:
            merged.append(group[0])
        else:
            rep = copy.deepcopy(group[0])
            rep.strength = max(c.strength for c in group)
            merged.append(rep)
    return merged


# ══════════════════════════════════════════════════════════════
# MAIN QUOTIENT FUNCTION
# ══════════════════════════════════════════════════════════════

def quotient(state):
    """
    Apply the full quotient layer to a State object.

    Returns:
        (quotient_state, quotient_map)
    """
    from cqim_v14_engine import State, Condition, Coupling, Synergy

    qmap = QuotientMap()
    conditions = copy.deepcopy(state.conditions)
    couplings = [copy.deepcopy(c) for c in state.couplings]
    synergies = [copy.deepcopy(s) for s in state.synergies]
    unknowns = list(state.unknowns)

    # Initialize identity mapping
    for cid in conditions:
        qmap.condition_map[cid] = cid
        qmap.equivalence_classes[cid] = {cid}

    # ── Pass 1: Remove self-loops ──
    n_before = len(couplings)
    couplings = [c for c in couplings if c.source != c.target]
    n_removed = n_before - len(couplings)
    if n_removed > 0:
        qmap.operations.append(f"Removed {n_removed} self-loop(s)")

    # ── Pass 2: Merge duplicate paths ──
    path_groups = defaultdict(list)
    for c in couplings:
        key = (c.source, c.target, c.type)
        path_groups[key].append(c)

    merged_couplings = []
    n_dup_merged = 0
    for key, group in path_groups.items():
        if len(group) == 1:
            merged_couplings.append(group[0])
        else:
            rep = copy.deepcopy(group[0])
            rep.strength = max(c.strength for c in group)
            merged_couplings.append(rep)
            n_dup_merged += len(group) - 1
    couplings = merged_couplings
    if n_dup_merged > 0:
        qmap.operations.append(f"Merged {n_dup_merged} duplicate path(s)")

    # ── Pass 3: Detect and merge alias nodes ──
    sig_to_cids = defaultdict(list)
    for cid in conditions:
        sig = _coupling_signature(cid, couplings, conditions)
        sig_to_cids[sig].append(cid)

    n_alias_merged = 0
    alias_groups = [group for group in sig_to_cids.values() if len(group) > 1]
    for group in alias_groups:
        group.sort()
        rep = group[0]
        for alias in group[1:]:
            qmap.condition_map[alias] = rep
            qmap.equivalence_classes[rep].add(alias)
            if alias in qmap.equivalence_classes:
                qmap.equivalence_classes[rep].update(qmap.equivalence_classes[alias])
                del qmap.equivalence_classes[alias]

            for c in couplings:
                if c.source == alias:
                    c.source = rep
                if c.target == alias:
                    c.target = rep

            for s in synergies:
                if s.condition_a == alias:
                    s.condition_a = rep
                if s.condition_b == alias:
                    s.condition_b = rep
                if s.target == alias:
                    s.target = rep

            del conditions[alias]
            n_alias_merged += 1

    if n_alias_merged > 0:
        qmap.operations.append(f"Merged {n_alias_merged} alias node(s)")
        couplings = _dedup_couplings(couplings)

    # ── Pass 4: Collapse redundant intermediaries (pure supporting relays) ──
    n_relay_removed = 0
    changed = True
    while changed:
        changed = False
        relay_cid = None
        for cid in list(conditions.keys()):
            if _is_pure_relay(cid, couplings, conditions):
                relay_cid = cid
                break
        if relay_cid is None:
            break

        inc = [c for c in couplings if c.target == relay_cid][0]
        out = [c for c in couplings if c.source == relay_cid][0]

        bypass = Coupling(
            source=inc.source,
            target=out.target,
            strength=inc.strength * out.strength,
            type="supporting",
            authority=f"bypass({relay_cid})",
        )

        qmap.removed_intermediaries[relay_cid] = {
            "source": inc.source,
            "target": out.target,
            "inc_strength": inc.strength,
            "out_strength": out.strength,
            "bypass_strength": bypass.strength,
        }
        qmap.condition_map[relay_cid] = f"__removed__{relay_cid}"

        couplings = [c for c in couplings if c.source != relay_cid and c.target != relay_cid]
        couplings.append(bypass)

        del conditions[relay_cid]
        n_relay_removed += 1
        changed = True

    if n_relay_removed > 0:
        qmap.operations.append(f"Collapsed {n_relay_removed} redundant intermediary/ies")
        couplings = _dedup_couplings(couplings)

    # ══════════════════════════════════════════════════════════
    # v14.1 ADVANCED PASSES
    # ══════════════════════════════════════════════════════════

    # ── Pass 5: Polarity-preserving nonlocal refactorization ──
    # Detect pairs (A, B) connected by a supporting coupling where:
    #   - Same polarity, same evidence, same evidence_weight, same weight
    #   - Their external coupling profiles (excluding A↔B link) are identical
    n_nonlocal_merged = 0
    changed = True
    while changed:
        changed = False
        merge_pair = None

        for c in couplings:
            if c.type != "supporting":
                continue
            a, b = c.source, c.target
            if a not in conditions or b not in conditions:
                continue

            cond_a = conditions[a]
            cond_b = conditions[b]

            if cond_a.polarity != cond_b.polarity:
                continue
            if (round(cond_a.evidence, 6) != round(cond_b.evidence, 6) or
                round(cond_a.evidence_weight, 6) != round(cond_b.evidence_weight, 6)):
                continue
            if round(cond_a.weight, 6) != round(cond_b.weight, 6):
                continue

            pair = {a, b}
            ext_targets_a = _get_external_targets(a, couplings, pair)
            ext_targets_b = _get_external_targets(b, couplings, pair)
            ext_sources_a = _get_external_sources(a, couplings, pair)
            ext_sources_b = _get_external_sources(b, couplings, pair)

            if ext_targets_a == ext_targets_b and ext_sources_a == ext_sources_b:
                merge_pair = (a, b)
                break

        if merge_pair is None:
            break

        a, b = merge_pair
        qmap.condition_map[b] = a
        qmap.equivalence_classes[a].add(b)
        if b in qmap.equivalence_classes:
            qmap.equivalence_classes[a].update(qmap.equivalence_classes[b])
            del qmap.equivalence_classes[b]

        for c_ref in couplings:
            if c_ref.source == b:
                c_ref.source = a
            if c_ref.target == b:
                c_ref.target = a

        for s in synergies:
            if s.condition_a == b:
                s.condition_a = a
            if s.condition_b == b:
                s.condition_b = a
            if s.target == b:
                s.target = a

        del conditions[b]
        # Dedup and remove self-loops after each merge to prevent cascading false matches
        couplings = [c for c in couplings if c.source != c.target]
        couplings = _dedup_couplings(couplings)
        n_nonlocal_merged += 1
        changed = True

    if n_nonlocal_merged > 0:
        qmap.operations.append(
            f"Merged {n_nonlocal_merged} polarity-preserving nonlocal refactorization(s)")

    # ── Pass 6: Mixed support/defeat multi-step decomposition ──
    # Collapse relays where one leg is supporting and one is defeating.
    # Net effect: defeating coupling with product strength.
    n_mixed_removed = 0
    changed = True
    while changed:
        changed = False
        relay_cid = None
        for cid in list(conditions.keys()):
            if _is_mixed_relay(cid, couplings, conditions):
                relay_cid = cid
                break
        if relay_cid is None:
            break

        inc = [c for c in couplings if c.target == relay_cid][0]
        out = [c for c in couplings if c.source == relay_cid][0]

        bypass = Coupling(
            source=inc.source,
            target=out.target,
            strength=inc.strength * out.strength,
            type="defeating",
            authority=f"mixed_bypass({relay_cid})",
        )

        qmap.removed_intermediaries[relay_cid] = {
            "source": inc.source,
            "target": out.target,
            "inc_strength": inc.strength,
            "inc_type": inc.type,
            "out_strength": out.strength,
            "out_type": out.type,
            "bypass_strength": bypass.strength,
            "bypass_type": "defeating",
        }
        qmap.condition_map[relay_cid] = f"__removed__{relay_cid}"

        couplings = [c for c in couplings if c.source != relay_cid and c.target != relay_cid]
        couplings.append(bypass)

        del conditions[relay_cid]
        n_mixed_removed += 1
        changed = True

    if n_mixed_removed > 0:
        qmap.operations.append(
            f"Collapsed {n_mixed_removed} mixed support/defeat decomposition(s)")
        couplings = _dedup_couplings(couplings)

    # ── Pass 7: Necessity-preserving rewrites ──
    # 7a: Remove supporting couplings that duplicate a necessary coupling
    n_necessity_cleaned = 0
    necessary_pairs = set()
    for c in couplings:
        if c.type == "necessary":
            necessary_pairs.add((c.source, c.target))

    if necessary_pairs:
        cleaned = []
        for c in couplings:
            if c.type == "supporting" and (c.source, c.target) in necessary_pairs:
                n_necessity_cleaned += 1
                continue
            cleaned.append(c)
        couplings = cleaned

    # 7b: Collapse necessity relays
    n_necessity_relay = 0
    changed = True
    while changed:
        changed = False
        relay_cid = None
        for cid in list(conditions.keys()):
            cond = conditions[cid]
            if cond.evidence_weight > 0:
                continue

            incoming = [c for c in couplings if c.target == cid]
            outgoing = [c for c in couplings if c.source == cid]

            if len(incoming) != 1 or len(outgoing) != 1:
                continue

            inc = incoming[0]
            out = outgoing[0]

            types = {inc.type, out.type}
            if "necessary" not in types:
                continue
            if not types.issubset({"necessary", "supporting"}):
                continue

            if inc.source == out.target:
                continue

            relay_cid = cid
            break

        if relay_cid is None:
            break

        inc = [c for c in couplings if c.target == relay_cid][0]
        out = [c for c in couplings if c.source == relay_cid][0]

        bypass = Coupling(
            source=inc.source,
            target=out.target,
            strength=inc.strength * out.strength,
            type="necessary",
            authority=f"necessity_bypass({relay_cid})",
        )

        qmap.removed_intermediaries[relay_cid] = {
            "source": inc.source,
            "target": out.target,
            "inc_strength": inc.strength,
            "inc_type": inc.type,
            "out_strength": out.strength,
            "out_type": out.type,
            "bypass_strength": bypass.strength,
            "bypass_type": "necessary",
        }
        qmap.condition_map[relay_cid] = f"__removed__{relay_cid}"

        couplings = [c for c in couplings if c.source != relay_cid and c.target != relay_cid]
        couplings.append(bypass)

        del conditions[relay_cid]
        n_necessity_relay += 1
        changed = True

    total_necessity = n_necessity_cleaned + n_necessity_relay
    if total_necessity > 0:
        parts = []
        if n_necessity_cleaned > 0:
            parts.append(f"removed {n_necessity_cleaned} redundant supporting-beside-necessary")
        if n_necessity_relay > 0:
            parts.append(f"collapsed {n_necessity_relay} necessity relay(s)")
        qmap.operations.append(f"Necessity-preserving: {'; '.join(parts)}")
        couplings = _dedup_couplings(couplings)

    # ── Pass 8: Distributed alias structures ──
    # Detect groups of nodes connected by supporting couplings (clique/chain)
    # with same polarity, same weight, identical external profiles,
    # and distributed evidence.
    n_distributed_merged = 0
    changed = True
    while changed:
        changed = False

        # Build supporting adjacency
        supp_adj = defaultdict(set)
        for c in couplings:
            if c.type == "supporting" and c.source in conditions and c.target in conditions:
                supp_adj[c.source].add(c.target)
                supp_adj[c.target].add(c.source)

        # Find connected components in the supporting subgraph
        visited = set()
        components = []
        for cid in conditions:
            if cid in visited:
                continue
            component = set()
            queue = [cid]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                component.add(node)
                for neighbor in supp_adj.get(node, set()):
                    if neighbor not in visited and neighbor in conditions:
                        queue.append(neighbor)
            if len(component) > 1:
                components.append(component)

        merge_group = None
        for comp in components:
            comp_list = sorted(comp)

            # All must have same polarity
            polarities = {conditions[cid].polarity for cid in comp_list}
            if len(polarities) > 1:
                continue

            # All must have same weight
            weights = {round(conditions[cid].weight, 4) for cid in comp_list}
            if len(weights) > 1:
                continue

            # External coupling profiles (excluding intra-group) must match
            ext_profiles_out = []
            ext_profiles_in = []
            for cid in comp_list:
                ext_profiles_out.append(
                    frozenset(_get_external_targets(cid, couplings, comp)))
                ext_profiles_in.append(
                    frozenset(_get_external_sources(cid, couplings, comp)))

            if len(set(ext_profiles_out)) > 1 or len(set(ext_profiles_in)) > 1:
                continue

            # Evidence should be distributed: check they're approximately equal
            ev_weights = [conditions[cid].evidence_weight for cid in comp_list]
            if any(e > 0 for e in ev_weights):
                mean_ew = sum(ev_weights) / len(ev_weights)
                if mean_ew > 0 and any(
                    abs(ew - mean_ew) / mean_ew > 0.5
                    for ew in ev_weights if ew > 0
                ):
                    continue

            merge_group = comp_list
            break

        if merge_group is None:
            break

        rep = merge_group[0]
        for alias in merge_group[1:]:
            qmap.condition_map[alias] = rep
            qmap.equivalence_classes[rep].add(alias)
            if alias in qmap.equivalence_classes:
                qmap.equivalence_classes[rep].update(qmap.equivalence_classes[alias])
                del qmap.equivalence_classes[alias]

            for c_ref in couplings:
                if c_ref.source == alias:
                    c_ref.source = rep
                if c_ref.target == alias:
                    c_ref.target = rep

            for s in synergies:
                if s.condition_a == alias:
                    s.condition_a = rep
                if s.condition_b == alias:
                    s.condition_b = rep
                if s.target == alias:
                    s.target = rep

            # Sum evidence from distributed nodes
            conditions[rep].evidence += conditions[alias].evidence
            conditions[rep].evidence_weight = max(
                conditions[rep].evidence_weight,
                conditions[alias].evidence_weight
            )

            del conditions[alias]
            n_distributed_merged += 1

        changed = True

    if n_distributed_merged > 0:
        qmap.operations.append(
            f"Merged {n_distributed_merged} distributed alias node(s)")
        couplings = _dedup_couplings(couplings)

    # ══════════════════════════════════════════════════════════
    # BUILD QUOTIENT STATE
    # ══════════════════════════════════════════════════════════

    q_state = State(
        conditions=conditions,
        couplings=couplings,
        synergies=synergies,
        unknowns=unknowns,
    )

    return q_state, qmap


# ══════════════════════════════════════════════════════════════
# LIFT AND REPORT
# ══════════════════════════════════════════════════════════════

def lift(result, qmap, original_ids):
    """
    Lift a quotient-space result back to the original condition space.
    """
    q_sigma = result["sigma"]

    orig_sigma = {}
    for orig_cid in original_ids:
        rep = qmap.condition_map.get(orig_cid, orig_cid)

        if rep.startswith("__removed__"):
            info = qmap.removed_intermediaries.get(orig_cid, {})
            src = info.get("source")
            tgt = info.get("target")
            src_val = q_sigma.get(src, 0.5)
            tgt_val = q_sigma.get(tgt, 0.5)
            orig_sigma[orig_cid] = (src_val + tgt_val) / 2.0
        elif rep in q_sigma:
            orig_sigma[orig_cid] = q_sigma[rep]
        else:
            orig_sigma[orig_cid] = 0.5

    lifted = dict(result)
    lifted["sigma"] = orig_sigma
    lifted["quotient_sigma"] = q_sigma
    return lifted


def quotient_report(qmap):
    """Generate a human-readable report of quotient operations."""
    lines = []
    lines.append("QUOTIENT LAYER REPORT")
    lines.append("=" * 50)

    if not qmap.operations:
        lines.append("No equivalences detected. Graph is already canonical.")
        return "\n".join(lines)

    for op in qmap.operations:
        lines.append(f"  * {op}")

    lines.append("")
    if qmap.n_merges > 0:
        lines.append(f"Equivalence classes ({qmap.n_merges} non-trivial):")
        for rep, members in qmap.equivalence_classes.items():
            if len(members) > 1:
                lines.append(f"  [{rep}] <- {sorted(members)}")

    if qmap.n_removals > 0:
        lines.append(f"\nRemoved intermediaries ({qmap.n_removals}):")
        for cid, info in qmap.removed_intermediaries.items():
            bypass_type = info.get("bypass_type", "supporting")
            lines.append(
                f"  {info['source']} -> [{cid}] -> {info['target']}  "
                f"bypassed as {info['source']} -> {info['target']} "
                f"(type={bypass_type}, s={info['bypass_strength']:.4f})"
            )

    return "\n".join(lines)
