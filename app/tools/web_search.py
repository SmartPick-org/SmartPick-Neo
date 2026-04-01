"""
Web search tools for the AdvisorAgent.

Available backends:
  - naver_blog : Naver Blog Search API  (NAVER_CLIENT_ID + NAVER_CLIENT_SECRET required)
  - naver_web  : Naver Web Search API   (NAVER_CLIENT_ID + NAVER_CLIENT_SECRET required)
  - tavily     : Tavily Search API      (TAVILY_API_KEY required)
  - duckduckgo : DuckDuckGo             (no API key, duckduckgo-search package required)
  - serper     : Serper.dev (Google)    (SERPER_API_KEY required)

Each function returns a list[dict] with at least {"title", "description", "link"}.
Use format_results() to convert any list to a plain-text ToolMessage string.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

import requests


# ===========================< Exceptions >============================

class WebSearchError(Exception):
    pass


class NaverSearchError(Exception):
    pass


# ===========================< Helpers >============================

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _naver_headers() -> Dict[str, str]:
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise NaverSearchError(
            "NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 환경 변수가 설정되지 않았습니다."
        )
    return {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }


# ===========================< Naver >============================

_NAVER_BLOG_ENDPOINT = "https://openapi.naver.com/v1/search/blog.json"
_NAVER_WEB_ENDPOINT = "https://openapi.naver.com/v1/search/webkr.json"


def search_blog(
    query: str,
    display: int = 5,
    start: int = 1,
    sort: str = "sim",
) -> List[Dict[str, Optional[str]]]:
    """
    네이버 블로그 검색 API를 호출해 결과를 반환합니다.
    반환 형식: [{"title": ..., "description": ..., "link": ..., "bloggername": ..., "postdate": ...}, ...]
    """
    if not query:
        return []

    params = {
        "query": query,
        "display": max(1, min(display, 10)),
        "start": max(1, min(start, 1000)),
        "sort": sort,
    }
    url = _NAVER_BLOG_ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_naver_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        raise NaverSearchError(f"네이버 검색 API 호출 실패: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NaverSearchError("네이버 검색 API 응답 파싱 실패") from exc

    return [
        {
            "title": it.get("title"),
            "description": it.get("description"),
            "link": it.get("link"),
            "bloggername": it.get("bloggername"),
            "postdate": it.get("postdate"),
        }
        for it in data.get("items", [])
    ]


def search_web(
    query: str,
    display: int = 5,
    start: int = 1,
) -> List[Dict[str, Optional[str]]]:
    """
    네이버 웹 검색 API를 호출해 결과를 반환합니다.
    블로그보다 공식 사이트, 뉴스, 카드사 페이지 등 폭넓은 결과를 포함합니다.
    반환 형식: [{"title": ..., "description": ..., "link": ...}, ...]
    """
    if not query:
        return []

    params = {
        "query": query,
        "display": max(1, min(display, 10)),
        "start": max(1, min(start, 1000)),
    }
    url = _NAVER_WEB_ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_naver_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        raise NaverSearchError(f"네이버 웹 검색 API 호출 실패: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NaverSearchError("네이버 웹 검색 API 응답 파싱 실패") from exc

    return [
        {
            "title": it.get("title"),
            "description": it.get("description"),
            "link": it.get("link"),
        }
        for it in data.get("items", [])
    ]


# ===========================< Tavily >============================

def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Tavily Search API — good general web coverage, returns clean snippets.
    Requires: TAVILY_API_KEY in environment.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise WebSearchError("TAVILY_API_KEY 환경 변수가 설정되지 않았습니다.")

    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    return [
        {
            "title": item.get("title", ""),
            "description": item.get("content", ""),
            "link": item.get("url", ""),
        }
        for item in data.get("results", [])
    ]


# ===========================< DuckDuckGo >============================

def duckduckgo_search(query: str, max_results: int = 5) -> list[dict]:
    """
    DuckDuckGo text search — no API key needed.
    Requires: duckduckgo-search package  (uv add duckduckgo-search)
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError as exc:
        raise WebSearchError(
            "duckduckgo-search 패키지가 설치되지 않았습니다. `uv add duckduckgo-search`를 실행하세요."
        ) from exc

    results = []
    with DDGS() as ddgs:
        for hit in ddgs.text(query, max_results=max_results):
            results.append(
                {
                    "title": hit.get("title", ""),
                    "description": hit.get("body", ""),
                    "link": hit.get("href", ""),
                }
            )
    return results


# ===========================< Serper (Google) >============================

def serper_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Serper.dev Google Search API — real Google results.
    Requires: SERPER_API_KEY in environment.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise WebSearchError("SERPER_API_KEY 환경 변수가 설정되지 않았습니다.")

    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": max_results, "gl": "kr", "hl": "ko"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    return [
        {
            "title": item.get("title", ""),
            "description": item.get("snippet", ""),
            "link": item.get("link", ""),
        }
        for item in data.get("organic", [])[:max_results]
    ]


# ===========================< Shared formatter >============================

def format_results(results: list[dict]) -> str:
    if not results:
        return "검색 결과 없음"
    lines: list[str] = []
    for i, item in enumerate(results, start=1):
        title = _strip_html(item.get("title", ""))
        desc = _strip_html(item.get("description", ""))
        link = item.get("link", "")
        lines.append(f"{i}. {title}\n   {desc}\n   {link}")
    return "\n\n".join(lines)
