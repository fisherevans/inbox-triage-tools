"""
email_extract — pull the primary link, unsubscribe link, and a one-line gist out of a
raw email. Single-file, standard-library only, no install step.

    python3 email_extract.py body.json [--pretty]

where body.json is {"html": ..., "plaintext": ..., "subject": ...} (html and plaintext
are both optional; at least one is required). Prints a JSON object with keys
primary_link, unsubscribe_link, gist.

Parsing is done by Python's stdlib `html.parser.HTMLParser` — a real incremental
tokenizer, not a regex tag-stripper. That distinction is load-bearing: marketing email
HTML is minified, deeply nested, and padded with invisible characters, and regex over it
silently produces wrong answers (swallowing `<script>` bodies as visible text, breaking
on `>` inside attribute values, missing a word split across inline tags).

GENERATED FILE — do not edit. Built from the `email_extract` package by
build_single_file.py; edit there and rebuild, or your change will be overwritten.
"""

from __future__ import annotations



# ==========================================================================
# from email_extract/htmlmini.py
# ==========================================================================

from html.parser import HTMLParser

# bs4 omits these two elements' contents from get_text(). Comments are dropped by
# virtue of HTMLParser routing them to handle_comment, which we don't implement.
NON_TEXT_ELEMENTS = frozenset({"script", "style"})


class Element:
    """One parsed element, carrying only what the extractor asks of it."""

    __slots__ = ("name", "attrs", "_strings", "_imgs")

    def __init__(self, name: str, attrs: dict[str, str]):
        self.name = name
        self.attrs = attrs
        self._strings: list[str] = []
        self._imgs: list["Element"] = []

    def __getitem__(self, key: str) -> str:
        return self.attrs[key]

    def get(self, key: str, default=None):
        return self.attrs.get(key, default)

    def get_text(self, separator: str = "", strip: bool = False) -> str:
        parts = self._strings
        if strip:
            parts = [p.strip() for p in parts]
            parts = [p for p in parts if p]
        return separator.join(parts)

    def find(self, name: str):
        """Only `find("img")` is used; kept narrow on purpose rather than pretending
        to be a general selector engine."""
        if name != "img":
            raise NotImplementedError(f"find({name!r}) is not supported")
        return self._imgs[0] if self._imgs else None

    def __repr__(self) -> str:
        return f"<Element {self.name} {self.attrs!r}>"


class Document:
    """Parse result. Exposes the two entry points the extractor uses."""

    __slots__ = ("_anchors", "_strings")

    def __init__(self):
        self._anchors: list[Element] = []
        self._strings: list[str] = []

    def get_text(self, separator: str = "", strip: bool = False) -> str:
        parts = self._strings
        if strip:
            parts = [p.strip() for p in parts]
            parts = [p for p in parts if p]
        return separator.join(parts)

    def find_all(self, name: str, href: bool | None = None) -> list[Element]:
        if name != "a":
            raise NotImplementedError(f"find_all({name!r}) is not supported")
        if href:
            return [a for a in self._anchors if "href" in a.attrs]
        return list(self._anchors)


class _Collector(HTMLParser):
    def __init__(self, doc: Document):
        # convert_charrefs=True matches bs4's html.parser builder: entities are decoded
        # into the text stream, so `&zwnj;` arrives as U+200C rather than 6 literal chars.
        super().__init__(convert_charrefs=True)
        self._doc = doc
        self._open_anchors: list[Element] = []
        self._suppress = 0

    def handle_starttag(self, tag: str, attrs):
        if tag in NON_TEXT_ELEMENTS:
            self._suppress += 1
            return
        collected = {}
        for key, value in attrs:
            collected.setdefault(key, value if value is not None else "")
        if tag == "a":
            element = Element("a", collected)
            self._doc._anchors.append(element)
            self._open_anchors.append(element)
        elif tag == "img":
            element = Element("img", collected)
            for anchor in self._open_anchors:
                anchor._imgs.append(element)

    def handle_endtag(self, tag: str):
        if tag in NON_TEXT_ELEMENTS:
            if self._suppress:
                self._suppress -= 1
            return
        if tag == "a" and self._open_anchors:
            self._open_anchors.pop()

    def handle_data(self, data: str):
        if self._suppress:
            return
        self._doc._strings.append(data)
        for anchor in self._open_anchors:
            anchor._strings.append(data)


def parse(markup: str | None) -> Document:
    doc = Document()
    if markup:
        collector = _Collector(doc)
        collector.feed(markup)
        collector.close()
    return doc


def BeautifulSoup(markup: str | None, features: str | None = None) -> Document:
    """Drop-in shim so call sites (and the existing test suite) read unchanged.

    `features` is accepted and ignored: the only backend is the stdlib tokenizer,
    which is what the caller was already asking for.
    """
    return parse(markup)



# ==========================================================================
# from email_extract/extractor.py
# ==========================================================================

import html
import re
import unicodedata
from dataclasses import dataclass


# Zero-width / invisible characters marketing ESPs use as list-detection padding
# (we saw this literally in a real Kohl's email: dozens of `&zwnj;` entities —
# and Gmail's plaintext conversion leaves them as the *literal 6-char entity
# string*, not a decoded character, so html.unescape() has to run first).
_INVISIBLE_CHARS = re.compile(r"[​‌‍﻿\xa0]")
_WHITESPACE = re.compile(r"\s+")
_URL_ONLY_LINE = re.compile(r"^https?://\S+$", re.I)

UNSUBSCRIBE_TEXT_PATTERNS = (
    re.compile(r"\bunsubscribe\b", re.I),
    re.compile(r"\bopt[\s-]?out\b", re.I),
)
MANAGE_PREFS_TEXT_PATTERNS = (
    re.compile(r"\bmanage\s+(email\s+)?preferences\b", re.I),
    re.compile(r"\bemail\s+preferences\b", re.I),
    re.compile(r"\bmanage\s+subscriptions?\b", re.I),
)
UNSUBSCRIBE_HREF_PATTERN = re.compile(r"unsubscribe|optout|opt-out", re.I)

# Anchor text that means "this link is the point of the email" — checked in order,
# first match wins. Lowercased, matched as substrings against normalized anchor text.
PRIMARY_LINK_KEYWORDS = (
    "shop now", "buy now", "order now",
    "view sale", "see sale", "shop the sale", "shop sale",
    "view order", "track order", "track package", "track my order",
    "view details", "see details", "view event", "event details",
    "rsvp", "confirm", "confirm your", "view invoice", "view receipt",
    "download", "claim", "redeem", "get tickets", "buy tickets",
    "view offer", "see offer", "view coupon", "activate",
    "view account", "manage your account",
    "read more", "read online", "continue reading", "full story",
)

# Chrome/navigation anchor text to never pick as the primary link.
PRIMARY_LINK_SKIP = (
    "view in browser", "view this email in your browser",
    "customer service", "find a store", "store locator",
    "privacy", "privacy policy", "terms", "terms of service",
    "unsubscribe", "opt out", "opt-out", "manage preferences",
    "manage subscriptions", "email preferences",
    "app store", "google play", "download the app",
    "facebook", "twitter", "instagram", "pinterest", "youtube", "tiktok",
    "contact us", "help", "faq", "customer support",
)


@dataclass
class ExtractionResult:
    primary_link: str | None
    unsubscribe_link: str | None
    gist: str


def _clean_text(text: str) -> str:
    text = html.unescape(text)
    text = _INVISIBLE_CHARS.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    return _WHITESPACE.sub(" ", text).strip()


def _anchor_text(a) -> str:
    # Anchors that are just an image (alt text) still count.
    text = a.get_text(" ", strip=True)
    if not text:
        text = a.get("alt", "") or a.get("title", "") or ""
    img = a.find("img")
    if not text and img is not None:
        text = img.get("alt", "") or img.get("title", "") or ""
    return _clean_text(text)


def _anchor_text_compact(a) -> str:
    """Same text, whitespace fully removed — catches a single word split across
    inline tags, e.g. <span>Un</span>subscribe, which a space-joined get_text()
    turns into "Un subscribe" and a \\b-anchored regex then fails to match."""
    return _WHITESPACE.sub("", _anchor_text(a))


def find_unsubscribe_link(soup: BeautifulSoup) -> str | None:
    manage_prefs_fallback = None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.lower().startswith(("mailto:", "tel:", "#")):
            continue
        text = _anchor_text(a)
        compact = _anchor_text_compact(a)

        if any(p.search(text) or p.search(compact) for p in UNSUBSCRIBE_TEXT_PATTERNS):
            return href
        if UNSUBSCRIBE_HREF_PATTERN.search(href):
            return href
        if manage_prefs_fallback is None and any(
            p.search(text) for p in MANAGE_PREFS_TEXT_PATTERNS
        ):
            manage_prefs_fallback = href

    return manage_prefs_fallback


def find_primary_link(soup: BeautifulSoup) -> str | None:
    anchors = [a for a in soup.find_all("a", href=True) if a["href"].strip()]

    def is_skippable(href: str, text_lower: str) -> bool:
        if href.lower().startswith(("mailto:", "tel:", "#")):
            return True
        if UNSUBSCRIBE_HREF_PATTERN.search(href):
            return True
        return any(skip in text_lower for skip in PRIMARY_LINK_SKIP)

    # Pass 1: first anchor whose text matches a known "this is the point" keyword.
    for a in anchors:
        href = a["href"].strip()
        text_lower = _anchor_text(a).lower()
        if is_skippable(href, text_lower):
            continue
        if any(kw in text_lower for kw in PRIMARY_LINK_KEYWORDS):
            return href

    # Pass 2: first plain http(s) link that isn't obvious chrome/nav/social/legal.
    for a in anchors:
        href = a["href"].strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        text_lower = _anchor_text(a).lower()
        if is_skippable(href, text_lower):
            continue
        return href

    return None


def extract_gist(html: str | None, plaintext: str | None, subject: str = "") -> str:
    """Best-effort one-liner. Prefers plaintext (already stripped of markup);
    falls back to the HTML's visible text if no plaintext body was supplied."""
    source = plaintext
    if not source or not source.strip():
        if html:
            source = BeautifulSoup(html, "html.parser").get_text("\n")
        else:
            source = ""

    candidates = []
    for raw_line in source.splitlines():
        line = _clean_text(raw_line)
        if not line:
            continue
        if _URL_ONLY_LINE.match(line):
            continue
        if len(line) < 8:
            continue
        if len(line) > 300:  # legal/boilerplate paragraph, not a gist
            continue
        letters = sum(c.isalpha() for c in line)
        if letters < 4:
            continue
        candidates.append(line)

    gist = candidates[0] if candidates else _clean_text(subject)
    if len(gist) > 220:
        gist = gist[:217].rstrip() + "..."
    return gist


def extract(
    html: str | None = None,
    plaintext: str | None = None,
    subject: str = "",
) -> ExtractionResult:
    if not html and not plaintext:
        raise ValueError("extract() needs at least one of html or plaintext")

    soup = BeautifulSoup(html, "html.parser") if html else None

    return ExtractionResult(
        primary_link=find_primary_link(soup) if soup else None,
        unsubscribe_link=find_unsubscribe_link(soup) if soup else None,
        gist=extract_gist(html, plaintext, subject),
    )



# ==========================================================================
# from email_extract/__main__.py
# ==========================================================================

import argparse
import dataclasses
import json
import sys



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", help="Path to a JSON file with html/plaintext/subject")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the output JSON")
    args = parser.parse_args(argv)

    with open(args.input_json, encoding="utf-8") as f:
        payload = json.load(f)

    result = extract(
        html=payload.get("html"),
        plaintext=payload.get("plaintext"),
        subject=payload.get("subject", ""),
    )

    indent = 2 if args.pretty else None
    print(json.dumps(dataclasses.asdict(result), indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
