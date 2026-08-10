"""A small planner loop over the stable, governed planner-facing API.

The trusted host creates ``planner`` from a host-issued ``GovernedAgentSession``:

    planner = PlannerAdapter.from_governed_session(agent)

An external planner may use the same calls as MCP tools instead:
``dingdong.get_capabilities``, ``dingdong.observe``, ``dingdong.execute``,
and ``dingdong.reobserve``.  It never needs a StatefulSessionRuntime object.
"""

from __future__ import annotations

from typing import Any, Callable

from dingdongditch import PlannerAdapter


def observe_execute_reobserve_continue(
    planner: PlannerAdapter,
    *,
    choose_operation: Callable[[dict[str, Any]], tuple[dict[str, Any], str]],
) -> dict[str, Any]:
    """One unfamiliar planner turn: observe -> choose -> execute -> receipt -> continue."""
    capabilities = planner.available_actions()
    if not capabilities.ok:
        return capabilities.to_dict()

    observed = planner.observe()
    if not observed.ok:
        return observed.to_dict()

    # The planner chooses a canonical Operation and an element_id from the
    # observation's interactive_elements. DingDongDitch does not choose either.
    operation, element_id = choose_operation(dict(observed.result["observation"]))
    executed = planner.execute(
        operation,
        observation_handle=observed.result["observation_handle"],
        element_id=element_id,
    )
    # A runtime can report a changed page either as a stale-observation
    # receipt or as a mutation-conflict error before dispatch.
    recovery = executed.recovery
    if not executed.ok and recovery is None:
        return executed.to_dict()

    receipt = executed.result["receipt"] if executed.ok else None
    if recovery is None:
        return {"receipt": receipt, "next": "continue planning from the receipt and a later observation"}

    # A dynamic page legitimately changed. Re-observe; choose a new element
    # from current evidence instead of assuming the old DOM id is still valid.
    rebound = planner.reobserve(
        previous_observation_handle=observed.result["observation_handle"],
        previous_element_id=element_id,
    )
    if not rebound.ok:
        return rebound.to_dict()
    return {
        "receipt": receipt,
        "recovery": recovery,
        "fresh_observation": rebound.result["observation"],
        "fresh_observation_handle": rebound.result["observation_handle"],
        "next": "choose a current element_id and execute the next canonical operation",
    }
