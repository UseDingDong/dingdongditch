"""Playwright-adjacent target resolution: primary locator + host constraints.

Keeps Playwright APIs out of the public contract. Does not invent constraints,
rank candidates, or fall back to first-match.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame
from playwright.sync_api import Locator as PlaywrightLocator
from playwright.sync_api import Page

from dingdongditch.contract.operation import Locator, LocatorStrategy
from dingdongditch.contract.target import (
    AttributeOperator,
    CardinalityPolicy,
    ConstraintType,
    NameMatchMode,
    ResolutionStage,
    TargetConstraint,
    TargetResolutionTrace,
    compile_name_regex,
)


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


ResolutionRoot = Page | Frame


# Accessible-name approximation used only for exclude/summary (not for inventing targets).
_ACCESSIBLE_NAME_JS = """(e) => {
  const labelled = e.getAttribute("aria-label");
  if (labelled) return labelled.trim();
  const labelledBy = e.getAttribute("aria-labelledby");
  if (labelledBy) {
    const parts = labelledBy.split(/\\s+/).map(id => {
      const node = document.getElementById(id);
      return node ? (node.textContent || "").trim() : "";
    }).filter(Boolean);
    if (parts.length) return parts.join(" ");
  }
  const title = e.getAttribute("title");
  if (title) return title.trim();
  return (e.textContent || "").replace(/\\s+/g, " ").trim();
}"""


@dataclass
class ResolvedTarget:
    ok: bool
    playwright_locator: PlaywrightLocator | None
    match_count: int
    error: str | None
    failure_kind: str | None
    trace: TargetResolutionTrace


@dataclass
class ResolvedFrame:
    """Result of resolving a declared iframe element in the main document."""

    ok: bool
    frame: Frame | None
    match_count: int
    error: str | None
    failure_kind: str | None
    trace: TargetResolutionTrace


def identity_locator(locator: Locator) -> Locator:
    """Return only the stable, non-interaction-state portion of a target.

    Visibility and enabledness are intentionally deferred until after target
    preparation.  All other host-declared constraints remain identity inputs.
    """
    return replace(
        locator,
        constraints=tuple(
            constraint
            for constraint in locator.constraints
            if constraint.type not in (ConstraintType.VISIBLE, ConstraintType.ENABLED)
        ),
    )


def resolve_target_identity(
    root: ResolutionRoot,
    locator: Locator,
    *,
    cardinality: CardinalityPolicy = CardinalityPolicy.EXACTLY_ONE,
    backend_identity: str = "playwright-sync",
) -> ResolvedTarget:
    """Resolve stable identity without consulting temporary interaction state."""
    result = resolve_target(
        root,
        identity_locator(locator),
        cardinality=cardinality,
        backend_identity=backend_identity,
    )
    for stage in result.trace.stages:
        stage.stage = f"identity_{stage.stage}"
    result.trace.dispatch_permitted = False
    return result


def _primary_playwright_locator(
    root: ResolutionRoot | PlaywrightLocator, locator: Locator
) -> PlaywrightLocator:
    if locator.strategy == LocatorStrategy.TEST_ID:
        return root.get_by_test_id(locator.value)
    if locator.strategy == LocatorStrategy.CSS:
        return root.locator(locator.value)
    if locator.strategy == LocatorStrategy.EXACT_TEXT:
        return root.get_by_text(locator.value, exact=True)
    if locator.strategy == LocatorStrategy.ROLE_NAME:
        assert locator.role is not None and locator.name is not None
        mode = locator.resolved_name_match()
        assert mode is not None
        if mode == NameMatchMode.EXACT:
            return root.get_by_role(locator.role, name=locator.name, exact=True)
        if mode == NameMatchMode.CONTAINS:
            return root.get_by_role(locator.role, name=locator.name, exact=False)
        if mode == NameMatchMode.REGEX:
            return root.get_by_role(locator.role, name=compile_name_regex(locator.name))
        raise ValueError(f"unsupported name_match: {mode}")
    raise ValueError(f"unsupported locator strategy: {locator.strategy}")


def _candidate_summary(handle: PlaywrightLocator) -> dict[str, Any]:
    try:
        return handle.evaluate(
            """e => ({
              tag: e.tagName.toLowerCase(),
              role: e.getAttribute("role"),
              id: e.id || null,
              testId: e.getAttribute("data-testid"),
              ariaLabel: e.getAttribute("aria-label"),
              nameGuess: (e.getAttribute("aria-label")
                || e.getAttribute("title")
                || (e.textContent || "").replace(/\\s+/g, " ").trim()
                || "").slice(0, 120),
              dataPurpose: e.getAttribute("data-purpose"),
            })"""
        )
    except PlaywrightError:
        return {"error": "summary_unavailable"}


def _is_descendant(candidate: PlaywrightLocator, container: PlaywrightLocator) -> bool:
    try:
        container_handle = container.element_handle(timeout=1000)
        if container_handle is None:
            return False
        return bool(
            candidate.evaluate(
                "(e, c) => !!c && c.contains(e)",
                container_handle,
            )
        )
    except PlaywrightError:
        return False


def _accessible_name(candidate: PlaywrightLocator) -> str:
    try:
        return str(candidate.evaluate(_ACCESSIBLE_NAME_JS) or "")
    except PlaywrightError:
        return ""


def _attribute_value(candidate: PlaywrightLocator, name: str) -> str | None:
    try:
        return candidate.get_attribute(name)
    except PlaywrightError:
        return None


def _apply_attribute_constraint(
    candidates: list[int],
    primary: PlaywrightLocator,
    constraint: TargetConstraint,
) -> list[int]:
    assert constraint.attribute_name is not None
    assert constraint.attribute_operator is not None
    remaining: list[int] = []
    for idx in candidates:
        el = primary.nth(idx)
        actual = _attribute_value(el, constraint.attribute_name)
        op = constraint.attribute_operator
        if op == AttributeOperator.EXISTS:
            if actual is not None:
                remaining.append(idx)
        elif op == AttributeOperator.EQUALS:
            if actual == constraint.attribute_value:
                remaining.append(idx)
        elif op == AttributeOperator.NOT_EQUALS:
            if actual != constraint.attribute_value:
                remaining.append(idx)
    return remaining


def _apply_exclude_constraint(
    candidates: list[int],
    primary: PlaywrightLocator,
    root: ResolutionRoot,
    constraint: TargetConstraint,
) -> list[int]:
    remaining: list[int] = []
    exclude_css_loc = (
        root.locator(constraint.exclude_css) if constraint.exclude_css else None
    )
    for idx in candidates:
        el = primary.nth(idx)
        excluded = False
        name = _accessible_name(el)
        for exact in constraint.exclude_names_exact:
            if name == exact:
                excluded = True
                break
        if not excluded:
            for fragment in constraint.exclude_names_contains:
                if fragment in name:
                    excluded = True
                    break
        if (
            not excluded
            and constraint.exclude_attribute_name is not None
            and constraint.exclude_attribute_value is not None
        ):
            if (
                _attribute_value(el, constraint.exclude_attribute_name)
                == constraint.exclude_attribute_value
            ):
                excluded = True
        if not excluded and exclude_css_loc is not None:
            try:
                n = exclude_css_loc.count()
                for j in range(n):
                    other = exclude_css_loc.nth(j)
                    same = el.evaluate(
                        "(e, o) => e === o",
                        other.element_handle(),
                    )
                    if same:
                        excluded = True
                        break
            except PlaywrightError:
                excluded = False
        if not excluded:
            remaining.append(idx)
    return remaining


def _resolve_container(
    root: ResolutionRoot,
    container: Locator,
    *,
    backend_identity: str,
) -> tuple[PlaywrightLocator | None, TargetResolutionTrace | None, str | None, str | None]:
    """Resolve a WITHIN container with its own constraints; must be exactly one."""
    result = resolve_target(
        root,
        container,
        cardinality=CardinalityPolicy.EXACTLY_ONE,
        backend_identity=backend_identity,
        for_container=True,
    )
    if not result.ok or result.playwright_locator is None:
        return None, result.trace, result.error, result.failure_kind
    return result.playwright_locator, result.trace, None, None


def resolve_frame(
    page: Page,
    frame_locator: Locator,
    *,
    backend_identity: str = "playwright-sync",
) -> ResolvedFrame:
    """Resolve one unique iframe/frame element in the main document and return its Frame.

    Does not search nested frames, does not fall back to the main document, and
    does not mutate any global "current frame" state.
    """
    element = resolve_target(
        page,
        frame_locator,
        cardinality=CardinalityPolicy.EXACTLY_ONE,
        backend_identity=backend_identity,
    )
    # Remap element failure kinds to frame-specific kinds for receipts.
    if not element.ok or element.playwright_locator is None:
        kind = element.failure_kind or "missing_frame"
        if kind in (
            "zero_after_primary",
            "zero_after_constraints",
            "missing_container",
        ):
            kind = "missing_frame"
        elif kind in (
            "multiple_after_primary",
            "multiple_after_constraints",
            "ambiguous_container",
        ):
            kind = "ambiguous_frame"
        reason = element.error or "iframe target could not be uniquely resolved"
        if kind == "missing_frame":
            reason = "missing iframe"
        elif kind == "ambiguous_frame":
            reason = "ambiguous iframe"
        trace = element.trace
        trace.frame_locator = frame_locator.describe()
        trace.failure_kind = kind
        trace.failure_reason = reason
        # Retarget stage names for auditability without inventing a second resolver.
        for stage in trace.stages:
            if stage.stage == "primary":
                stage.stage = "frame_primary"
            elif stage.stage == "cardinality":
                stage.stage = "frame_cardinality"
            elif stage.stage == "constraint":
                stage.stage = "frame_constraint"
        return ResolvedFrame(
            ok=False,
            frame=None,
            match_count=element.match_count,
            error=reason,
            failure_kind=kind,
            trace=trace,
        )

    loc = element.playwright_locator
    trace = element.trace
    trace.frame_locator = frame_locator.describe()
    for stage in trace.stages:
        if stage.stage == "primary":
            stage.stage = "frame_primary"
        elif stage.stage == "cardinality":
            stage.stage = "frame_cardinality"
        elif stage.stage == "constraint":
            stage.stage = "frame_constraint"

    try:
        tag = str(
            loc.evaluate("(e) => (e.tagName || '').toLowerCase()") or ""
        )
    except PlaywrightError as exc:
        reason = f"iframe element observation failed: {exc}"
        trace.failure_kind = "detached_frame"
        trace.failure_reason = reason
        trace.dispatch_permitted = False
        trace.cardinality_passed = False
        return ResolvedFrame(
            ok=False,
            frame=None,
            match_count=1,
            error=reason,
            failure_kind="detached_frame",
            trace=trace,
        )

    if tag not in ("iframe", "frame"):
        reason = f"frame target resolved to non-frame element: {tag or 'unknown'}"
        trace.failure_kind = "not_a_frame"
        trace.failure_reason = reason
        trace.dispatch_permitted = False
        trace.cardinality_passed = False
        return ResolvedFrame(
            ok=False,
            frame=None,
            match_count=1,
            error=reason,
            failure_kind="not_a_frame",
            trace=trace,
        )

    try:
        handle = loc.element_handle(timeout=1000)
        if handle is None:
            reason = "iframe detached before content frame resolution"
            trace.failure_kind = "detached_frame"
            trace.failure_reason = reason
            trace.dispatch_permitted = False
            trace.cardinality_passed = False
            return ResolvedFrame(
                ok=False,
                frame=None,
                match_count=1,
                error=reason,
                failure_kind="detached_frame",
                trace=trace,
            )
        frame = handle.content_frame()
        if frame is None:
            reason = "iframe content frame unavailable (detached or not a browsing context)"
            trace.failure_kind = "detached_frame"
            trace.failure_reason = reason
            trace.dispatch_permitted = False
            trace.cardinality_passed = False
            return ResolvedFrame(
                ok=False,
                frame=None,
                match_count=1,
                error=reason,
                failure_kind="detached_frame",
                trace=trace,
            )
    except PlaywrightError as exc:
        reason = f"iframe detached during resolution: {exc}"
        trace.failure_kind = "detached_frame"
        trace.failure_reason = reason
        trace.dispatch_permitted = False
        trace.cardinality_passed = False
        return ResolvedFrame(
            ok=False,
            frame=None,
            match_count=1,
            error=reason,
            failure_kind="detached_frame",
            trace=trace,
        )

    trace.stages.append(
        ResolutionStage(
            stage="frame_attached",
            candidates_before=1,
            candidates_after=1,
            timestamp_ms=_monotonic_ms(),
            notes="content frame obtained; page remains owned browsing context",
        )
    )
    return ResolvedFrame(
        ok=True,
        frame=frame,
        match_count=1,
        error=None,
        failure_kind=None,
        trace=trace,
    )


def merge_frame_trace(
    frame_trace: TargetResolutionTrace,
    target_trace: TargetResolutionTrace,
) -> TargetResolutionTrace:
    """Combine frame resolution stages with in-frame target stages."""
    merged = TargetResolutionTrace(
        primary_locator=target_trace.primary_locator,
        stages=list(frame_trace.stages) + list(target_trace.stages),
        final_candidate_count=target_trace.final_candidate_count,
        cardinality_policy=target_trace.cardinality_policy,
        cardinality_passed=target_trace.cardinality_passed,
        dispatch_permitted=target_trace.dispatch_permitted,
        failure_reason=target_trace.failure_reason or frame_trace.failure_reason,
        failure_kind=target_trace.failure_kind or frame_trace.failure_kind,
        backend_identity=target_trace.backend_identity,
        candidate_summaries=list(target_trace.candidate_summaries),
        frame_locator=frame_trace.frame_locator,
    )
    return merged


def resolve_target(
    root: ResolutionRoot,
    locator: Locator,
    *,
    cardinality: CardinalityPolicy = CardinalityPolicy.EXACTLY_ONE,
    backend_identity: str = "playwright-sync",
    for_container: bool = False,
) -> ResolvedTarget:
    """Resolve primary + constraints; permit dispatch only when cardinality holds."""
    trace = TargetResolutionTrace(
        primary_locator=locator.describe(),
        cardinality_policy=cardinality.value,
        backend_identity=backend_identity,
    )
    now = _monotonic_ms()
    primary = _primary_playwright_locator(root, locator)
    primary_count = primary.count()
    candidates = list(range(primary_count))
    trace.stages.append(
        ResolutionStage(
            stage="primary",
            candidates_before=0,
            candidates_after=primary_count,
            timestamp_ms=now,
            notes="primary locator match set",
        )
    )

    if primary_count == 0 and not locator.constraints:
        trace.final_candidate_count = 0
        kind = "zero_after_primary"
        reason = "zero candidates after primary locator"
        trace.failure_kind = kind
        trace.failure_reason = reason
        return ResolvedTarget(
            ok=False,
            playwright_locator=None,
            match_count=0,
            error=reason,
            failure_kind=kind,
            trace=trace,
        )

    for constraint in locator.constraints:
        before = len(candidates)
        stage_notes = ""
        if constraint.type == ConstraintType.WITHIN:
            assert constraint.within is not None
            container_loc, container_trace, cerr, ckind = _resolve_container(
                root, constraint.within, backend_identity=backend_identity
            )
            if container_loc is None:
                # Merge nested stages for auditability.
                for stage in container_trace.stages if container_trace else []:
                    trace.stages.append(stage)
                kind = ckind or "ambiguous_container"
                if kind == "zero_after_primary" or kind == "zero_after_constraints":
                    kind = "missing_container"
                reason = cerr or "within container could not be uniquely resolved"
                if "ambiguous" in (cerr or "") or (
                    container_trace and container_trace.final_candidate_count > 1
                ):
                    kind = "ambiguous_container"
                    reason = "ambiguous within container"
                trace.final_candidate_count = len(candidates)
                trace.failure_kind = kind
                trace.failure_reason = reason
                trace.stages.append(
                    ResolutionStage(
                        stage="constraint",
                        constraint=constraint.describe(),
                        candidates_before=before,
                        candidates_after=before,
                        timestamp_ms=_monotonic_ms(),
                        notes=reason,
                    )
                )
                return ResolvedTarget(
                    ok=False,
                    playwright_locator=None,
                    match_count=before,
                    error=reason,
                    failure_kind=kind,
                    trace=trace,
                )
            candidates = [
                idx
                for idx in candidates
                if _is_descendant(primary.nth(idx), container_loc)
            ]
            stage_notes = "within unique container"
        elif constraint.type == ConstraintType.ATTRIBUTE:
            candidates = _apply_attribute_constraint(candidates, primary, constraint)
            stage_notes = "attribute filter"
        elif constraint.type == ConstraintType.VISIBLE:
            assert constraint.visible is not None
            want = constraint.visible
            candidates = [
                idx
                for idx in candidates
                if primary.nth(idx).is_visible() == want
            ]
            stage_notes = f"visible={want}"
        elif constraint.type == ConstraintType.ENABLED:
            assert constraint.enabled is not None
            want = constraint.enabled
            candidates = [
                idx
                for idx in candidates
                if primary.nth(idx).is_enabled() == want
            ]
            stage_notes = f"enabled={want}"
        elif constraint.type == ConstraintType.EXCLUDE:
            candidates = _apply_exclude_constraint(candidates, primary, root, constraint)
            stage_notes = "exclude filter"
        else:
            reason = f"unsupported constraint type: {constraint.type}"
            trace.failure_kind = "invalid_constraint"
            trace.failure_reason = reason
            return ResolvedTarget(
                ok=False,
                playwright_locator=None,
                match_count=len(candidates),
                error=reason,
                failure_kind="invalid_constraint",
                trace=trace,
            )

        trace.stages.append(
            ResolutionStage(
                stage="constraint",
                constraint=constraint.describe(),
                candidates_before=before,
                candidates_after=len(candidates),
                timestamp_ms=_monotonic_ms(),
                notes=stage_notes,
            )
        )

    final_count = len(candidates)
    trace.final_candidate_count = final_count

    # Safe summaries when uniqueness fails (no large DOM dumps).
    if final_count != 1:
        for idx in candidates[:8]:
            trace.candidate_summaries.append(_candidate_summary(primary.nth(idx)))

    if cardinality != CardinalityPolicy.EXACTLY_ONE:
        reason = f"unsupported cardinality policy: {cardinality.value}"
        trace.failure_kind = "invalid_constraint"
        trace.failure_reason = reason
        return ResolvedTarget(
            ok=False,
            playwright_locator=None,
            match_count=final_count,
            error=reason,
            failure_kind="invalid_constraint",
            trace=trace,
        )

    if final_count == 0:
        kind = (
            "zero_after_constraints"
            if locator.constraints
            else "zero_after_primary"
        )
        reason = (
            "zero candidates after constraints"
            if locator.constraints
            else "zero candidates after primary locator"
        )
        trace.failure_kind = kind
        trace.failure_reason = reason
        trace.stages.append(
            ResolutionStage(
                stage="cardinality",
                candidates_before=final_count,
                candidates_after=final_count,
                timestamp_ms=_monotonic_ms(),
                notes=reason,
            )
        )
        return ResolvedTarget(
            ok=False,
            playwright_locator=None,
            match_count=0,
            error=reason,
            failure_kind=kind,
            trace=trace,
        )

    if final_count > 1:
        kind = (
            "multiple_after_constraints"
            if locator.constraints
            else "multiple_after_primary"
        )
        reason = (
            f"multiple candidates after constraints: {final_count}"
            if locator.constraints
            else f"ambiguous target: {final_count} matches"
        )
        trace.failure_kind = kind
        trace.failure_reason = reason
        trace.stages.append(
            ResolutionStage(
                stage="cardinality",
                candidates_before=final_count,
                candidates_after=final_count,
                timestamp_ms=_monotonic_ms(),
                notes=reason,
            )
        )
        return ResolvedTarget(
            ok=False,
            playwright_locator=None,
            match_count=final_count,
            error=reason,
            failure_kind=kind,
            trace=trace,
        )

    # Exactly one — build a locator that addresses only that element.
    chosen_index = candidates[0]
    # Prefer chaining when unconstrained and primary already unique.
    if not locator.constraints and primary_count == 1:
        resolved = primary
    else:
        resolved = primary.nth(chosen_index)

    trace.cardinality_passed = True
    trace.dispatch_permitted = True
    trace.stages.append(
        ResolutionStage(
            stage="cardinality",
            candidates_before=1,
            candidates_after=1,
            timestamp_ms=_monotonic_ms(),
            notes="exactly_one passed; dispatch permitted"
            + (" (container)" if for_container else ""),
        )
    )
    return ResolvedTarget(
        ok=True,
        playwright_locator=resolved,
        match_count=1,
        error=None,
        failure_kind=None,
        trace=trace,
    )
