import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from services import generator

LLM_MODEL, VLM_MODEL = "main-model", "light-model"  # distinct names, whatever config.py defaults to
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
        monkeypatch.setattr(generator, "LLM_MODEL", LLM_MODEL)
        monkeypatch.setattr(generator, "VLM_MODEL", VLM_MODEL)
        return models
    return use


def test_busy_model_falls_back_to_the_lighter_model(fake):
    models = fake(FakeModels(fail_times=2))
    assert asyncio.run(generator.generate_answer("what is entropy", POINTS)) == "It measures uncertainty [p.1]."
    assert models.calls == [LLM_MODEL, VLM_MODEL, VLM_MODEL]


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


class HangingMain:
    """The main model never answers (seen live: gemini-flash-latest hung for 40 s+); the light one does."""
    def __init__(self):
        self.calls = []

    async def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        if model == LLM_MODEL:
            await asyncio.sleep(3600)
        return SimpleNamespace(text="Answer from the light model [p.1].")


def test_a_hanging_model_times_out_and_the_light_model_answers(fake, monkeypatch):
    models = fake(HangingMain())
    monkeypatch.setattr(generator, "TIMEOUT", 0.05)
    assert asyncio.run(generator.generate_answer("what is entropy", POINTS)) == "Answer from the light model [p.1]."
    assert models.calls == [LLM_MODEL, VLM_MODEL]


def test_a_hanging_caption_gives_up_instead_of_freezing_the_upload(monkeypatch):
    from services import vlm

    class Hang:
        async def generate_content(self, model, contents, config=None):
            await asyncio.sleep(3600)

    monkeypatch.setattr(vlm, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=Hang())))
    monkeypatch.setattr(vlm, "TIMEOUT", 0.05)
    monkeypatch.setattr(vlm, "RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(vlm, "_sem", None)
    assert asyncio.run(vlm.caption("AAAA", "figure")) is None
