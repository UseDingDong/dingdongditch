from __future__ import annotations

from dingdongditch.contract.operation import FreshnessPolicy
from dingdongditch.evidence.models import EvidenceSignal, FreshnessEvaluation


def evaluate_freshness(
    *,
    policy: FreshnessPolicy,
    action_started_at_ms: int | None,
    verification_completed_at_ms: int | None,
    signals: list[EvidenceSignal],
    signal_ids_used_for_verification: set[str],
) -> FreshnessEvaluation:
    """Post-action evidence must not predate action start;

    evidence older than max_age_ms relative to verification time is stale.
    """
    stale: list[str] = []
    notes: list[str] = []

    if action_started_at_ms is None:
        notes.append("action_started_at_ms missing; cannot fully evaluate freshness")
        return FreshnessEvaluation(
            policy_max_age_ms=policy.max_age_ms,
            action_started_at_ms=action_started_at_ms,
            verification_completed_at_ms=verification_completed_at_ms,
            stale_signal_ids=stale,
            notes="; ".join(notes),
        )

    by_id = {s.signal_id: s for s in signals}
    for signal_id in signal_ids_used_for_verification:
        signal = by_id.get(signal_id)
        if signal is None:
            continue
        if signal.collected_at_ms < action_started_at_ms:
            stale.append(signal_id)
            notes.append(
                f"{signal_id} collected before action start "
                f"({signal.collected_at_ms} < {action_started_at_ms})"
            )
        if verification_completed_at_ms is not None:
            age = verification_completed_at_ms - signal.collected_at_ms
            if age > policy.max_age_ms:
                if signal_id not in stale:
                    stale.append(signal_id)
                notes.append(
                    f"{signal_id} age {age}ms exceeds max_age_ms {policy.max_age_ms}"
                )

    if not notes:
        notes.append("all verification signals satisfied freshness policy")

    return FreshnessEvaluation(
        policy_max_age_ms=policy.max_age_ms,
        action_started_at_ms=action_started_at_ms,
        verification_completed_at_ms=verification_completed_at_ms,
        stale_signal_ids=stale,
        notes="; ".join(notes),
    )


def is_signal_fresh_for_verification(
    signal: EvidenceSignal,
    *,
    action_started_at_ms: int,
    verification_completed_at_ms: int,
    policy: FreshnessPolicy,
) -> bool:
    if signal.collected_at_ms < action_started_at_ms:
        return False
    age = verification_completed_at_ms - signal.collected_at_ms
    return age <= policy.max_age_ms
