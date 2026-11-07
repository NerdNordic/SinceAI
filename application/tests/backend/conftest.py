"""Isolate the classifier in existing workflow tests; routing tests override this stub."""

import pytest


@pytest.fixture(autouse=True)
def offline_classifier(monkeypatch):
    from backend import routing
    from backend.router import Classification

    monkeypatch.setattr(routing, "classify", lambda *args: (
        Classification(intent="analytics_request", action=None, needs_clarification=False, ambiguity_reason=None), 0.0))
