"""experiment.py — LLMO効果測定実験の判定(2026-09-14).

1観測(collect_llm のレコード)から、llm_experiment の判定列を作る。

判定は**文字列とURLの照合だけ**で決める。抽出(extract.py の Haiku)は通さない。
実験の前後比較で見たいのは「引用元に出たか」「社名が出たか」という事実で、
LLMの解釈が挟まると、判定のぶれが施策の効果と区別できなくなるため。

- cited_domain  … 引用元に cross-com.jp(サブドメイン含む)のURLがあるか
- cited_article … 引用元にその記事のURLがあるか(www・末尾スラッシュ・
                  クエリ・#見出し の違いは同じ記事として扱う)
- mentioned     … 回答本文に「クロスコム」が含まれるか(旧ルール。9/15 から変えずに残す)
- mentioned_v2  … 社名の表記ゆれ(MENTION_TERMS_V2)のどれかを含むか(2026-10-01 修正。
                  大文字小文字・全角半角を区別しない)。9/15 以降の行は answer_text から
                  遡って数え直した(backfill_mentioned_v2.py)。**参考指標で判定には使わない**
- cited_domains … 引用元のドメイン一覧(出現順・重複なし)

「引用元」は collect_llm の ``cited_urls``(モデルが返した引用URLと、
本文中に書かれたURLの和集合)。Gemini の引用は vertexaisearch の
リダイレクトなので実URLに解決してから照合する。解決できなかった件数は
``unresolved_redirects`` に残す。**0件でない日の 0 は「引用されなかった」
とは言い切れない。**

欠測(収集エラー)の行は判定列を空にする。0 を置くと「観測したが引用されな
かった」と区別できず、ビフォーの引用率が実際より低く出る。
"""
from __future__ import annotations

import unicodedata
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import retired_urls

SELF_DOMAIN = "cross-com.jp"
MENTION_TERM = "クロスコム"
# 2026-10-01：社名の表記ゆれ。「クロスコム」だけでは英字表記・中黒入りを落としていた。
# NFKC(全角英数・半角カナをそろえる)と casefold(大文字小文字)をかけてから照合する。
# ※ "cross-com" は本文に書かれた cross-com.jp の URL にも当たる(社名の言及として数える)
MENTION_TERMS_V2 = ("クロスコム", "Cross-Com", "CrossCom", "Crosscom", "cross-com", "クロス・コム")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


_MENTION_KEYS_V2 = tuple(dict.fromkeys(_fold(t) for t in MENTION_TERMS_V2))


def mention_hits_v2(text: str) -> List[Tuple[int, int]]:
    """表記ゆれに当たった箇所 (開始, 終了)。位置は NFKC 後の文字列での位置。"""
    folded = _fold(text)
    hits = []
    for key in _MENTION_KEYS_V2:
        start = folded.find(key)
        while start != -1:
            hits.append((start, start + len(key)))
            start = folded.find(key, start + 1)
    return sorted(hits)


def is_mentioned_v2(text: str) -> int:
    folded = _fold(text)
    return int(any(key in folded for key in _MENTION_KEYS_V2))

Resolver = Callable[[str], Optional[str]]


def domain_of(url: str) -> str:
    """URLのホスト名(小文字・www. とポートを除く)。取れなければ空。"""
    try:
        host = (urlsplit(str(url).strip()).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_self_domain(domain: str) -> bool:
    return domain == SELF_DOMAIN or domain.endswith("." + SELF_DOMAIN)


def normalize_url(url: str) -> str:
    """同じ記事かどうかの比較用。ホスト + パス(末尾スラッシュなし)。"""
    try:
        path = urlsplit(str(url).strip()).path
    except ValueError:
        return ""
    return domain_of(url) + path.rstrip("/")


def resolve_urls(urls: Sequence[str],
                 resolver: Optional[Resolver] = None) -> Tuple[List[str], int]:
    """リダイレクトを実URLに解決する。戻り値は (URL一覧, 解決できなかった件数)。"""
    resolver = resolver or retired_urls.resolve_redirect
    out: List[str] = []
    unresolved = 0
    for url in urls:
        url = str(url).strip()
        if not url:
            continue
        if retired_urls.REDIRECT_MARKER in url:
            real = resolver(url)
            if real is None:
                unresolved += 1
                continue
            url = real
        if url not in out:
            out.append(url)
    return out, unresolved


def evaluate(record: Dict[str, Any], prompt: Dict[str, Any],
             resolver: Optional[Resolver] = None) -> Dict[str, Any]:
    """collect_llm のレコードに足す実験の列を返す。"""
    fields: Dict[str, Any] = {
        "experiment_id": prompt["id"],
        # pool=統計の対象 / watch=観測だけ続ける(2026-09-23。E37)
        "experiment_flag": prompt.get("experiment_flag") or "pool",
        "layer": prompt.get("layer", ""),
        "target_url": prompt["url"],
        "answer_text": record.get("answer") or "",
    }
    if record.get("error"):
        fields.update(cited_domain="", cited_article="", mentioned="", mentioned_v2="",
                      cited_domains=[], resolved_urls=[], unresolved_redirects="")
        return fields

    urls, unresolved = resolve_urls(record.get("cited_urls") or [], resolver)
    domains: List[str] = []
    for url in urls:
        domain = domain_of(url)
        if domain and domain not in domains:
            domains.append(domain)
    target = normalize_url(prompt["url"])
    fields.update(
        cited_domain=int(any(is_self_domain(d) for d in domains)),
        cited_article=int(any(normalize_url(u) == target for u in urls)),
        mentioned=int(MENTION_TERM in fields["answer_text"]),
        mentioned_v2=is_mentioned_v2(fields["answer_text"]),
        cited_domains=domains,
        resolved_urls=urls,
        unresolved_redirects=unresolved,
    )
    return fields
