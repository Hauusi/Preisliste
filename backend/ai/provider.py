"""KI-Anbieter: Ollama (Standard), lokaler OpenAI-kompatibler Server (z. B. llama.cpp), Mock für Tests.

Grundregeln:
- Nur lokale Endpunkte (Docker-internes Netz oder localhost), keine Cloud.
- Die KI bekommt nur kleine Ausschnitte (Kopfzeile + 5 Zeilen, oder ein Artikel mit Kandidaten).
- Antworten müssen dem JSON-Schema entsprechen; sonst begrenzte Wiederholung, danach UNKLAR.
- Die KI rechnet nicht und erzeugt keinen Code.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from backend.ai.schemas import ColumnSuggestion, MatchJudgement, RuleSuggestion
from backend.config import Settings
from backend.excel.columns import FIELDS

T = TypeVar("T", bound=BaseModel)
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "ollama"}

SYSTEM = (
    "Du bist ein Hilfsprogramm für Preislisten. Antworte ausschließlich mit JSON nach dem vorgegebenen Schema. "
    "Rechne nichts aus, erfinde keine Werte, schreibe keinen Code. Wenn du unsicher bist, gib eine niedrige "
    "confidence an oder null."
)


class AIUnavailable(Exception):
    pass


class AIInvalidResponse(Exception):
    """Antwort nach allen Wiederholungen ungültig -> Status UNKLAR."""


@dataclass
class AIStatus:
    active: bool
    provider: str
    model: str | None
    message: str
    loaded_mb: int | None = None


def _check_local(url: str) -> None:
    host = urlsplit(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"KI-Endpunkt {host!r} ist nicht lokal. Erlaubt: {sorted(ALLOWED_HOSTS)}")


class AIProvider:
    name = "none"

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> AIStatus:
        return AIStatus(False, self.name, None, "KI ist deaktiviert")

    def _complete(self, system: str, prompt: str, schema: dict) -> str:  # pragma: no cover - abstrakt
        raise AIUnavailable("KI ist deaktiviert")

    def ask(self, prompt: str, model: type[T], extra_check: Callable[[T], None] | None = None) -> T:
        """Fragt die KI und validiert die Antwort. Wiederholt bei ungültiger Antwort begrenzt."""
        schema = model.model_json_schema()
        last_error = None
        for _attempt in range(1 + self.settings.ai_retries):
            raw = self._complete(SYSTEM, prompt, schema)
            try:
                parsed = model.model_validate_json(raw)
                if extra_check:
                    extra_check(parsed)
                return parsed
            except (ValidationError, ValueError) as exc:
                last_error = exc
        raise AIInvalidResponse(f"Ungültige KI-Antwort nach {1 + self.settings.ai_retries} Versuchen: {last_error}")

    # --- Aufgaben ---

    def suggest_columns(self, header: list[str], samples: list[list]) -> ColumnSuggestion:
        rows = [[_cell(v) for v in r[: len(header)]] for r in samples[:5]]
        prompt = (
            "Ordne die Spalten einer Preisliste den Feldern zu. Erlaubte Felder: "
            + ", ".join(f"{k} ({v})" for k, v in FIELDS.items())
            + ". Nicht zuordenbare Spalten: field null. Jedes Feld höchstens einmal.\n"
            + "Kopfzeile (Index: Text): " + json.dumps({i: h for i, h in enumerate(header)}, ensure_ascii=False)
            + "\nBeispielzeilen: " + json.dumps(rows, ensure_ascii=False)
        )

        def check(s: ColumnSuggestion):
            seen = set()
            for c in s.columns:
                if c.index >= len(header):
                    raise ValueError("Spaltenindex außerhalb der Tabelle")
                if c.field and c.field in seen:
                    raise ValueError(f"Feld {c.field} mehrfach")
                if c.field:
                    seen.add(c.field)

        return self.ask(prompt, ColumnSuggestion, check)

    def judge_match(self, new: dict, candidates: list[dict]) -> MatchJudgement:
        prompt = (
            "Entscheide, ob der neue Artikel einem der alten Artikel entspricht (gleiches Produkt, ggf. neue "
            "Artikelnummer). Wenn keiner passt: match false, old_article null.\n"
            "Neuer Artikel: " + json.dumps(new, ensure_ascii=False)
            + "\nAlte Kandidaten: " + json.dumps(candidates, ensure_ascii=False)
        )
        numbers = {c["artikelnummer"] for c in candidates}

        def check(m: MatchJudgement):
            if m.new_article != new["artikelnummer"]:
                raise ValueError("new_article passt nicht zur Anfrage")
            if m.match and m.old_article not in numbers:
                raise ValueError("old_article ist kein Kandidat")
            if not m.match and m.old_article is not None and m.old_article not in numbers:
                raise ValueError("old_article ist kein Kandidat")

        return self.ask(prompt, MatchJudgement, check)

    def suggest_rule(self, text: str) -> RuleSuggestion:
        prompt = (
            "Übersetze die Beschreibung einer Preiskalkulation in Schritte. Erlaubte Schritt-Objekte:\n"
            '{"type":"discount","percent":"15","base":"start|current|step:N"}, '
            '{"type":"surcharge","percent":"4","base":"start|current|step:N"}, '
            '{"type":"fixed","amount":"3.40"}, {"type":"multiply","factor":"2.6"}, {"type":"round","increment":"0.05","mode":"HALF_UP|UP|DOWN"}, '
            '{"type":"round_ending","ending":"0.90","direction":"UP|DOWN|NEAREST"}, '
            '{"type":"min_quantity","quantity":"10"}, {"type":"tier","quantity":"10"}.\n'
            "Zahlen als Text mit Punkt. Keine Formeln. Erkläre kurz in explanation.\n"
            "Beschreibung: " + text[:1000]
        )
        return self.ask(prompt, RuleSuggestion)


def _cell(v) -> str | None:
    if v is None:
        return None
    return str(v)[:80]


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        _check_local(settings.ollama_url)
        self.base = settings.ollama_url.rstrip("/")

    def _request(self, path: str, payload: dict | None = None, timeout: float = 5) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - nur lokale URL (geprüft)
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AIUnavailable(f"Ollama nicht erreichbar: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AIUnavailable("Ollama lieferte keine gültige Antwort") from exc

    def status(self) -> AIStatus:
        try:
            tags = self._request("/api/tags", timeout=2)
        except AIUnavailable as exc:
            return AIStatus(False, self.name, self.settings.ai_model, str(exc))
        names = {m.get("name") for m in tags.get("models", [])}
        model = self.settings.ai_model
        if model not in names and f"{model}:latest" not in names:
            return AIStatus(False, self.name, model, f"Modell {model} ist nicht installiert")
        loaded = None
        try:
            ps = self._request("/api/ps", timeout=2)
            loaded = sum(m.get("size", 0) for m in ps.get("models", [])) // (1024 * 1024) or None
        except AIUnavailable:
            pass
        return AIStatus(True, self.name, model, "KI aktiv", loaded)

    def _complete(self, system: str, prompt: str, schema: dict) -> str:
        payload = {
            "model": self.settings.ai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "format": schema,  # Structured Outputs
            "stream": False,
            "keep_alive": self.settings.ai_keep_alive,
            "options": {"temperature": 0},
        }
        resp = self._request("/api/chat", payload, timeout=self.settings.ai_timeout_seconds)
        return (resp.get("message") or {}).get("content", "")


class LocalModelProvider(AIProvider):
    """OpenAI-kompatibler lokaler Server (z. B. llama.cpp `llama-server`) mit JSON-Schema-Ausgabe."""

    name = "local"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        _check_local(settings.local_model_url)
        self.base = settings.local_model_url.rstrip("/")

    def _post(self, path: str, payload: dict | None, timeout: float) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - nur lokale URL (geprüft)
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AIUnavailable(f"Lokaler KI-Server nicht erreichbar: {exc}") from exc

    def status(self) -> AIStatus:
        try:
            self._post("/v1/models", None, 2)
        except AIUnavailable as exc:
            return AIStatus(False, self.name, self.settings.ai_model, str(exc))
        return AIStatus(True, self.name, self.settings.ai_model, "KI aktiv")

    def _complete(self, system: str, prompt: str, schema: dict) -> str:
        payload = {
            "model": self.settings.ai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_schema", "json_schema": {"name": "antwort", "schema": schema}},
        }
        resp = self._post("/v1/chat/completions", payload, self.settings.ai_timeout_seconds)
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""


class MockProvider(AIProvider):
    """Für automatische Tests: liefert vorgegebene Antworten (Text), der Reihe nach."""

    name = "mock"

    def __init__(self, settings: Settings, responses: list[str] | None = None, active: bool = True):
        super().__init__(settings)
        self.responses = list(responses or [])
        self.active = active
        self.prompts: list[str] = []

    def status(self) -> AIStatus:
        return AIStatus(self.active, self.name, "mock", "KI aktiv (Mock)" if self.active else "Mock inaktiv")

    def _complete(self, system: str, prompt: str, schema: dict) -> str:
        if not self.active:
            raise AIUnavailable("Mock inaktiv")
        self.prompts.append(prompt)
        if not self.responses:
            return "{}"
        return self.responses.pop(0)


_override: AIProvider | None = None
_status_cache: tuple[float, AIStatus] | None = None


def set_provider(provider: AIProvider | None) -> None:
    """Für Tests: festen Anbieter setzen."""
    global _override, _status_cache
    _override = provider
    _status_cache = None


def get_provider(settings: Settings) -> AIProvider:
    if _override is not None:
        return _override
    kind = settings.ai_provider.lower()
    if kind == "ollama":
        return OllamaProvider(settings)
    if kind == "local":
        return LocalModelProvider(settings)
    if kind == "mock":
        return MockProvider(settings)
    return AIProvider(settings)


def cached_status(settings: Settings, max_age: float = 30) -> AIStatus:
    global _status_cache
    now = time.monotonic()
    if _status_cache and now - _status_cache[0] < max_age:
        return _status_cache[1]
    try:
        status = get_provider(settings).status()
    except ValueError as exc:
        status = AIStatus(False, settings.ai_provider, settings.ai_model, str(exc))
    _status_cache = (now, status)
    return status
