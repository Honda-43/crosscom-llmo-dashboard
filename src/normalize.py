"""normalize.py — entity name normalisation (Phase 1 §2-1).

``normalize_entity()`` turns the free-form company names that the observation
models write into a single canonical surface form so that Share of Voice can be
aggregated per company instead of per spelling.

Pipeline (in order):

1. NFKC normalisation — full-width alphanumerics become half-width
   (``三菱総研ＤＣＳ`` -> ``三菱総研DCS``), ``㈱`` becomes ``(株)``.
2. Middle dots (``・``) are dropped and runs of whitespace collapse to one
   half-width space.
3. Legal-entity forms are stripped from the head and the tail
   (``株式会社`` / ``合同会社`` / ``(株)`` / ``Inc.`` / ``Co.,Ltd.`` …).
4. Spaces *between* non-ASCII characters are removed so
   ``メンバーズ サースプラスカンパニー`` == ``メンバーズサースプラスカンパニー``.
   Spaces inside Latin names are kept (``Deloitte Tohmatsu`` stays readable).
5. ``config/entity_aliases.yaml`` is applied — the lookup is case-insensitive
   and both sides of the table go through steps 1-4, so the YAML only has to
   list genuinely different names, not every spelling of them.

Unknown companies are returned normalised but otherwise untouched (§2-1).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

import yaml

from settings import ENTITY_ALIASES_FILE

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

_MIDDLE_DOT_RE = re.compile(r"[・･·]")
_WS_RE = re.compile(r"\s+")
# A space flanked by non-ASCII (CJK/kana) characters carries no information.
_CJK_SPACE_RE = re.compile(r"(?<=[^\x00-\x7F])\s+(?=[^\x00-\x7F])")
_EDGE_CHARS = " \t,.、，。・/|-–—"


def _strip_legal_forms(text: str) -> str:
    """Remove legal-entity forms from both ends, repeatedly until stable.

    Never returns an empty string: a name that consists *only* of a legal form
    (e.g. a model that answered literally "株式会社") is kept as-is rather than
    silently vanishing from the aggregation.
    """
    current = text
    while True:
        previous = current
        current = current.strip(_EDGE_CHARS)

        for form in _JP_LEGAL_FORMS:
            if current.startswith(form) and len(current) > len(form):
                current = current[len(form):]
            if current.endswith(form) and len(current) > len(form):
                current = current[: -len(form)]

        stripped = _EN_LEGAL_RE.sub("", current)
        if stripped.strip(_EDGE_CHARS):
            current = stripped

        if current == previous:
            return current


def _normalize_core(name: Any) -> str:
    """Steps 1-4: everything except the alias lookup."""
    if name is None:
        return ""
    text = unicodedata.normalize("NFKC", str(name))
    text = _MIDDLE_DOT_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    if not text:
        return ""
    text = _strip_legal_forms(text)
    text = _CJK_SPACE_RE.sub("", text)
    return text.strip(_EDGE_CHARS).strip()


def _alias_key(text: str) -> str:
    """Case-insensitive lookup key for the alias table."""
    return text.casefold()


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
