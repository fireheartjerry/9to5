"""Robust extraction from an Ollama chat response.

THE BUG THIS FIXES: the ollama-python client (>=0.4, here 0.6.2) returns pydantic
``ChatResponse`` / ``Message`` objects, NOT plain dicts. Code that gated extraction on
``isinstance(resp, dict)`` therefore saw EVERY real response as empty -- the model
generated tokens server-side, but the client threw them away and reported an empty
completion (the "Brain (Ollama) unavailable; empty completion" notice).

``responseText``/``responseJson`` handle a dict response, a pydantic response (attribute
or mapping access), AND every malformed shape the 7B brain / test fakes emit (None resp,
non-dict message, non-string / None content). ``memory.retrieval`` already used this
dict-or-attr pattern for embeddings; these helpers bring chat extraction in line.
"""
from __future__ import annotations

import json
import re


def _field(obj, key):
    """Pull ``key`` from a dict OR a pydantic/attribute object. None on any miss -- never raises."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    # pydantic ChatResponse/Message: attribute access, then mapping .get() for back-compat.
    val = getattr(obj, key, None)
    if val is None:
        getter = getattr(obj, "get", None)
        if callable(getter):
            try:
                val = getter(key)
            except Exception:  # noqa: BLE001
                val = None
    return val


def responseText(resp) -> str:
    """``resp['message']['content']`` as text. '' for ANY malformed shape (dict or pydantic)."""
    try:
        content = _field(_field(resp, "message"), "content")
        return content if isinstance(content, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _firstBalancedObject(text: str):
    """Extract the first balanced {…} from *text*, respecting nesting and string literals.

    The naive ``re.search(r"\\{.*\\}", text, re.DOTALL)`` is maximally greedy: on any
    output that contains two separate JSON objects it spans from the first ``{`` to the
    LAST ``}``, producing a concatenated blob that fails ``json.loads``. This extractor
    walks character-by-character and closes at the correct depth-0 ``}``."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def responseJson(resp):
    """Parse the JSON body of a chat response. None on any shape/parse problem.

    Salvages the two ways a 7B model commonly breaks strict JSON: wrapping it in a ```json
    fence, and emitting prose around the object (extract the first balanced ``{...}``)."""
    text = responseText(resp).strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    chunk = _firstBalancedObject(text)   # salvage: balanced-brace walk avoids greedy-regex span bug
    if chunk:
        try:
            return json.loads(chunk)
        except Exception:  # noqa: BLE001
            return None
    return None
