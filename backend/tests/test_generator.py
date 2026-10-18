import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from config import LLM_MODEL, VLM_MODEL
from services import generator

POINTS = [SimpleNamespace(payload={"page_number": 1, "type": "text", "text": "Entropy measures uncertainty."})]


class FakeModels:
    def __init__(self, fail_times: int, code: int = 503):
        self.calls, self.fail_times, self.code = [], fail_times, code

    async def generate_content(self, model, contents, config):
        self.calls.append(model)
        if len(self.calls) <= self.fail_times:
            cls = errors.ServerError if self.code >= 500 else errors.ClientError
            raise cls(self.code, {"error": {"code": self.code, "message": "busy", "status": "UNAVAILABLE"}})
        return SimpleNamespace(text="It measures uncertainty [p.1].")


@pytest.fixture
def fake(monkeypatch):
    def use(models):
        monkeypatch.setattr(generator, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=models)))
        monkeypatch.setattr(generator, "RETRY_DELAYS", (0, 0))
        return models
    return use


def test_busy_model_is_retried_then_falls_back_to_the_lighter_model(fake):
    models = fake(FakeModels(fail_times=2))
    assert asyncio.run(generator.generate_answer("what is entropy", POINTS)) == "It measures uncertainty [p.1]."
    assert models.calls == [LLM_MODEL, LLM_MODEL, VLM_MODEL]


def test_rate_limit_counts_as_busy(fake):
    models = fake(FakeModels(fail_times=1, code=429))
    assert asyncio.run(generator.generate_answer("what is entropy", POINTS))
    assert len(models.calls) == 2


def test_gives_up_with_model_busy_after_three_tries(fake):
    models = fake(FakeModels(fail_times=99))
    with pytest.raises(generator.ModelBusy):
        asyncio.run(generator.generate_answer("what is entropy", POINTS))
    assert len(models.calls) == 3


def test_a_bad_request_is_not_retried(fake):
    models = fake(FakeModels(fail_times=99, code=400))
    with pytest.raises(errors.ClientError):
        asyncio.run(generator.generate_answer("what is entropy", POINTS))
    assert len(models.calls) == 1
