from __future__ import annotations

from types import SimpleNamespace

import pytest

from dingdongditch.contract.observation import PageObservationOptions
from dingdongditch.page_observer import (
    ObservationUnstableError,
    PageObserver,
    _ObservationMutated,
)


class FakePage:
    def __init__(self, quiescence):
        self.quiescence = list(quiescence)
        self.wait_calls = []

    def evaluate(self, script, arguments):
        self.wait_calls.append(arguments)
        return self.quiescence.pop(0)


class FakeBackend:
    def __init__(self, quiescence=()):
        self.is_started = True
        self.page = FakePage(quiescence)


def observation():
    return SimpleNamespace(diagnostics={})


def test_static_page_uses_one_unchanged_capture(monkeypatch):
    observer = PageObserver(FakeBackend())
    result = observation()
    calls = []
    monkeypatch.setattr(
        observer,
        "_capture_once",
        lambda options: calls.append(options) or result,
    )
    returned = observer.observe_page(PageObservationOptions())
    assert returned is result
    assert len(calls) == 1
    assert observer.backend.page.wait_calls == []
    assert result.diagnostics["transaction"]["attempts"] == 1
    assert result.diagnostics["transaction"]["discarded_attempts"] == []


def test_one_transient_mutation_restarts_from_beginning(monkeypatch):
    observer = PageObserver(
        FakeBackend([{"stable": True, "mutations": 1, "mutation_epoch": 2}])
    )
    result = observation()
    attempts = iter([_ObservationMutated("before-1", "after-1"), result])

    def capture(options):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(observer, "_capture_once", capture)
    returned = observer.observe_page(PageObservationOptions())
    assert returned is result
    transaction = result.diagnostics["transaction"]
    assert transaction["attempts"] == 2
    assert len(transaction["discarded_attempts"]) == 1
    assert transaction["discarded_attempts"][0]["quiescence"]["stable"] is True


def test_multiple_transient_mutations_eventually_succeed(monkeypatch):
    observer = PageObserver(FakeBackend([
        {"stable": True, "mutations": 2, "mutation_epoch": 3},
        {"stable": True, "mutations": 1, "mutation_epoch": 4},
    ]))
    result = observation()
    attempts = iter([
        _ObservationMutated("before-1", "after-1"),
        _ObservationMutated("before-2", "after-2"),
        result,
    ])

    def capture(options):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(observer, "_capture_once", capture)
    returned = observer.observe_page(PageObservationOptions())
    assert returned is result
    assert result.diagnostics["transaction"]["attempts"] == 3
    assert len(result.diagnostics["transaction"]["discarded_attempts"]) == 2


def test_continuous_dom_churn_fails_without_publishing(monkeypatch):
    observer = PageObserver(FakeBackend([
        {"stable": False, "mutations": 500, "mutation_epoch": 501}
    ]))
    monkeypatch.setattr(
        observer,
        "_capture_once",
        lambda options: (_ for _ in ()).throw(
            _ObservationMutated("before", "after")
        ),
    )
    with pytest.raises(ObservationUnstableError) as caught:
        observer.observe_page(PageObservationOptions(observation_budget_ms=100))
    assert caught.value.evidence["reason"] == "dom_never_reached_quiescence"
    assert caught.value.evidence["attempts"] == 1
    assert observer._observations == {}
