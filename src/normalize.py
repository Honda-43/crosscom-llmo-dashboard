"""normalize.py — entity name normalisation (Phase 1 §2-1).

``normalize_entity()`` turns the free-form company names that the observation
models write into a single canonical surface form so that Share of Voice can be
aggregated per company instead of per spelling.

Pipeline (in order):

1. NFKC normalisation — full-width alphanumerics become half-width
   (``三菱総研ＤＣＳ`` -> ``三菱総研DCS``), ``㈱`` becomes ``(株)``.
2. Parenthesised annotations are dropped (``株式会社100（100inc）`` ->
   ``株式会社100``), middle dots (``・``) are removed and runs of whitespace
   collapse to one half-width space.
3. Legal-entity forms are stripped from the head and the tail
   (``株式会社`` / ``合同会社`` / ``(株)`` / ``Inc.`` / ``Co.,Ltd.`` …).
4. Spaces *between* non-ASCII characters are removed so
   ``メンバーズ サースプラスカンパニー`` == ``メンバーズサースプラスカンパニー``.
   Spaces inside Latin names are kept (``Deloitte Tohmatsu`` stays readable).
5. ``config/entity_aliases.yaml`` is applied — the lookup ignores case *and*
   whitespace, and both sides of the table go through steps 1-4, so the YAML
   only has to list genuinely different names, not every spelling of them.

Unknown companies are returned normalised but otherwise untouched (§2-1).

``resolve_entity()`` wraps all of that and additionally drops values that are
not company names at all — leftover fragments with no letters, and the generic
phrases listed in ``config/entity_stoplist.yaml``. Aggregations should call
``resolve_entity()``; ``normalize_entity()`` alone is the pure name mapping.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

import yaml

from settings import ENTITY_ALIASES_FILE, ENTITY_STOPLIST_FILE

# --- Legal entity forms ----------------------------------------------------
# Japanese forms are removed from the head *and* the tail (§2-1: 前後から除去).
_JP_LEGAL_FORMS = (
    "特定非営利活動法人",
    "一般社団法人",
    "一般財団法人",
    "公益社団法人",
    "公益財団法人",
    "株式会社",
    "合同会社",
    "有限会社",
    "合資会社",
    "合名会社",
    "医療法人",
    "学校法人",
    "(株)",
    "(有)",
    "(合)",
)

# Latin forms are suffix-only and must be preceded by a space or a comma, so a
# name that merely *ends* in those letters (e.g. "Marco") is never truncated.
_EN_LEGAL_RE = re.compile(
    r"[\s,]+(?:"
    r"co\.?\s*,?\s*ltd\.?"
    r"|pte\.?\s*ltd\.?"
    r"|inc\.?"
    r"|corporation|corp\.?"
    r"|l\.?l\.?c\.?"
    r"|ltd\.?"
    r"|k\.?k\.?"
    r"|company|limited|plc|gmbh"
    r")\s*$",
    re.IGNORECASE,
)

# Parenthesised segments are annotations, never part of the name itself:
# "株式会社100（100inc）" -> "株式会社100", "…ファーム（2018年創業）" -> "…ファーム".
# NFKC has already folded full-width brackets to ASCII by the time this runs.
# It also disposes of the "(株)" style legal forms as a side effect.
_PARENTHETICAL_RE = re.compile(r"\([^()]*\)")
_MIDDLE_DOT_RE = re.compile(r"[・･·]")
_WS_RE = re.compile(r"\s+")
# A space is only meaningful between two Latin words ("Deloitte Tohmatsu").
# Touching a CJK/kana character on either side it is a spelling variant, so
# "EY ストラテジーアンドコンサルティング" == "EYストラテジーアンドコンサルティング".
_JP_SPACE_RE = re.compile(r"(?<=[^\x00-\x7F])\s+|\s+(?=[^\x00-\x7F])")
_EDGE_CHARS = " \t,.、，。・/|-–—"
# "Letter" in the Unicode sense: excludes digits, underscore and punctuation.
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _has_letter(text: str) -> bool:
    return bool(_LETTER_RE.search(text))


def _strip_legal_forms(text: str) -> str:
    """Remove legal-entity forms from both ends, repeatedly until stable.

    A removal is only accepted when something name-like survives it. Without
    that guard "株式会社100" collapses to the bare number "100", which then
    matches no alias and pollutes the aggregation as its own entity — the exact
    failure that put a "100" row in sov_daily. The same guard keeps a model that
    answered literally "株式会社" from vanishing entirely.
    """
    def accept(candidate: str, current: str) -> str:
        trimmed = candidate.strip(_EDGE_CHARS)
        return trimmed if trimmed and _has_letter(trimmed) else current

    current = text
    while True:
        previous = current
        current = current.strip(_EDGE_CHARS)

        for form in _JP_LEGAL_FORMS:
            if current.startswith(form):
                current = accept(current[len(form):], current)
            if current.endswith(form):
                current = accept(current[: -len(form)], current)

        current = accept(_EN_LEGAL_RE.sub("", current), current)

        if current == previous:
            return current


def _normalize_core(name: Any) -> str:
    """Steps 1-4: everything except the alias lookup."""
    if name is None:
        return ""
    text = unicodedata.normalize("NFKC", str(name))
    stripped_parens = _PARENTHETICAL_RE.sub("", text)
    if stripped_parens.strip(_EDGE_CHARS):
        text = stripped_parens
    text = _MIDDLE_DOT_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    if not text:
        return ""
    text = _strip_legal_forms(text)
    text = _JP_SPACE_RE.sub("", text)
    return text.strip(_EDGE_CHARS).strip()


def _alias_key(text: str) -> str:
    """Lookup key for the alias / stop lists.

    Case- and whitespace-insensitive, so "100 Inc" and "100inc" resolve to the
    same entry without the YAML having to list both spacings.
    """
    return _WS_RE.sub("", text).casefold()


_ALIASES: Optional[Dict[str, str]] = None


def _load_aliases() -> Dict[str, str]:
    """Build ``{normalised alias -> canonical name}`` from the YAML file.

    The canonical name is registered as an alias of itself so that a decorated
    form of the canonical name (``合同会社クロスコム``) also resolves.
    """
    try:
        with open(ENTITY_ALIASES_FILE, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        print(f"[warn] entity alias file not found: {ENTITY_ALIASES_FILE}")
        return {}

    table: Dict[str, str] = {}
    for canonical, variants in (data.get("aliases") or {}).items():
        canonical = str(canonical).strip()
        if not canonical:
            continue
        table[_alias_key(_normalize_core(canonical))] = canonical
        for variant in variants or []:
            key = _alias_key(_normalize_core(variant))
            if key:
                table[key] = canonical
    return table


def reload_aliases() -> Dict[str, str]:
    """Re-read the alias YAML (used by tests and by long-running processes)."""
    global _ALIASES
    _ALIASES = _load_aliases()
    return _ALIASES


def _aliases() -> Dict[str, str]:
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = _load_aliases()
    return _ALIASES


def normalize_entity(name: Any) -> str:
    """Return the canonical form of a company name (§2-1).

    >>> normalize_entity("株式会社メンバーズ サースプラスカンパニー")
    'メンバーズ'
    >>> normalize_entity("三菱総研ＤＣＳ")
    '三菱総研DCS'
    """
    core = _normalize_core(name)
    if not core:
        return ""
    return _aliases().get(_alias_key(core), core)


# --------------------------------------------------------------------------
# Stop list — generic phrases that are not company names
# --------------------------------------------------------------------------
_STOPLIST: Optional[Dict[str, List[str]]] = None


def _load_stoplist() -> Dict[str, List[str]]:
    """``{"exact": [...keys...], "contains": [...keys...]}`` from the YAML."""
    try:
        with open(ENTITY_STOPLIST_FILE, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        print(f"[warn] entity stop list not found: {ENTITY_STOPLIST_FILE}")
        return {"exact": [], "contains": []}

    def keys(section: str) -> List[str]:
        return [
            key
            for key in (_alias_key(_normalize_core(v)) for v in (data.get(section) or []))
            if key
        ]

    return {"exact": keys("exact"), "contains": keys("contains")}


def reload_stoplist() -> Dict[str, List[str]]:
    """Re-read the stop list YAML (used by tests)."""
    global _STOPLIST
    _STOPLIST = _load_stoplist()
    return _STOPLIST


def _stoplist() -> Dict[str, List[str]]:
    global _STOPLIST
    if _STOPLIST is None:
        _STOPLIST = _load_stoplist()
    return _STOPLIST


def is_excluded(entity: str) -> bool:
    """True when a *normalised* name must not enter the aggregation.

    Three ways to be excluded:

    - empty,
    - no letter at all ("100", "2018") — a leftover fragment, never a company,
    - listed in ``config/entity_stoplist.yaml`` (exact match, or containing one
      of the descriptive markers).
    """
    if not entity or not _has_letter(entity):
        return True

    key = _alias_key(entity)
    stoplist = _stoplist()
    if key in stoplist["exact"]:
        return True
    return any(marker in key for marker in stoplist["contains"])


def resolve_entity(name: Any) -> Optional[str]:
    """Normalise ``name`` and drop it when it is not a countable company.

    Returns the canonical name, or ``None`` if the value must be excluded.
    This is the single gate every aggregation goes through (§2-1 + stop list).
    """
    entity = normalize_entity(name)
    return None if is_excluded(entity) else entity
