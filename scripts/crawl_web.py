from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "generated" / "web_chunks.jsonl"
USER_AGENT = "KelleyAIPrototype/0.1 (+local proof-of-concept; respectful curated crawl)"
ALLOWED_DOMAINS = {"kelley.iu.edu", "careers.kelley.iu.edu"}
SEED_URLS = [
    "https://kelley.iu.edu/undergraduate/index.html",
    "https://kelley.iu.edu/undergraduate/academics/index.html",
    "https://kelley.iu.edu/undergraduate/advising/index.html",
    "https://kelley.iu.edu/undergraduate/advising/contact-us/index.html",
    "https://kelley.iu.edu/undergraduate/advising/academic-support/index.html",
    "https://kelley.iu.edu/undergraduate/advising/forms-apps/index.html",
    "https://kelley.iu.edu/undergraduate/student-life/index.html",
    "https://kelley.iu.edu/undergraduate/student-life/student-organizations/index.html",
    "https://kelley.iu.edu/undergraduate/student-life/student-government/index.html",
    "https://kelley.iu.edu/undergraduate/academics/majors-minors-certificates/index.html",
    "https://kelley.iu.edu/undergraduate/academics/workshops/index.html",
    "https://kelley.iu.edu/undergraduate/academics/study-abroad/index.html",
    "https://kelley.iu.edu/undergraduate/academics/business-honors/index.html",
    "https://careers.kelley.iu.edu/",
    "https://careers.kelley.iu.edu/resources/kelley-resume-template-option-1/",
]

ALLOWED_PREFIXES = (
    "https://kelley.iu.edu/undergraduate/",
    "https://kelley.iu.edu/recruiters-companies/undergrad/students/",
    "https://careers.kelley.iu.edu/",
)
EXCLUDED_PATTERNS = (
    "/programs/",
    "/graduate",
    "/faculty-research/",
    "/executive-education",
    "/alumni/",
    "/giving",
    "/news-events/",
    "/about/directory/faculty",
    "/phd",
)
TOPIC_TERMS = {
    "academic",
    "advising",
    "advisor",
    "appointment",
    "major",
    "minor",
    "certificate",
    "degree",
    "i-core",
    "icore",
    "support",
    "tutoring",
    "workshop",
    "study",
    "abroad",
    "honors",
    "student",
    "organization",
    "involvement",
    "career",
    "coaching",
    "resume",
    "interview",
    "networking",
    "fair",
    "recruiting",
    "internship",
    "handshake",
    "forms",
    "applications",
    "contact",
}


@dataclass
class Section:
    heading: str
    text: str
    links: list[dict[str, str]]


def normalize_url(url: str) -> str:
    url = urldefrag(url)[0]
    parsed = urlparse(url)
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path == "/":
        path = "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or parsed.netloc.lower() not in ALLOWED_DOMAINS:
        return False
    normalized = normalize_url(url)
    if not any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return False
    lowered = normalized.lower()
    return not any(pattern in lowered for pattern in EXCLUDED_PATTERNS)


def topic_score(text: str) -> int:
    words = set(re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()))
    return len(words & TOPIC_TERMS)


def robot_parser(origin: str) -> RobotFileParser:
    parser = RobotFileParser()
    parser.set_url(urljoin(origin, "/robots.txt"))
    try:
        parser.read()
    except Exception:
        parser.parse("")
    return parser


def canonical_url(soup: BeautifulSoup, url: str) -> str:
    link = soup.find("link", rel=lambda value: value and "canonical" in value)
    href = link.get("href") if link else None
    if href:
        canonical = normalize_url(urljoin(url, href))
        if allowed_url(canonical):
            return canonical
    return normalize_url(url)


def clean_text(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def remove_chrome(soup: BeautifulSoup) -> None:
    for selector in [
        "header",
        "footer",
        "nav",
        "script",
        "style",
        "noscript",
        "form",
        "iframe",
        "[role='navigation']",
        "[aria-label*='breadcrumb' i]",
        ".rvt-header-wrapper",
        ".rvt-header-menu",
        ".rvt-sidenav",
        ".rvt-footer",
        ".breadcrumb",
        ".breadcrumbs",
    ]:
        for node in soup.select(selector):
            node.decompose()


def main_content(soup: BeautifulSoup) -> BeautifulSoup:
    node = soup.find("main") or soup.find(id="content") or soup.find("article") or soup.body or soup
    return node


def extract_links(node, base_url: str) -> list[dict[str, str]]:
    links = []
    seen = set()
    for anchor in node.find_all("a", href=True):
        label = clean_text(anchor.get_text(" ", strip=True))
        href = normalize_url(urljoin(base_url, anchor["href"]))
        if not label or href in seen:
            continue
        if allowed_url(href) or urlparse(href).netloc.endswith("iu.edu"):
            links.append({"label": label[:120], "url": href})
            seen.add(href)
    return links[:12]


def section_text_from_nodes(nodes: Iterable) -> str:
    parts = []
    for node in nodes:
        if getattr(node, "name", None) in {"p", "li", "h2", "h3", "h4"}:
            text = clean_text(node.get_text(" ", strip=True))
            if text:
                parts.append(text)
    return clean_text(" ".join(parts))


def extract_sections(soup: BeautifulSoup, url: str) -> tuple[str, list[Section], list[str]]:
    remove_chrome(soup)
    content = main_content(soup)
    title = clean_text((soup.find("h1") or soup.find("title") or content).get_text(" ", strip=True))
    all_links = extract_links(content, url)
    headings = content.find_all(["h2", "h3"])
    sections: list[Section] = []
    if not headings:
        text = section_text_from_nodes(content.find_all(["p", "li"]))
        if len(text) > 180:
            sections.append(Section(title or "Page content", text, all_links))
        return title, sections, [link["url"] for link in all_links if allowed_url(link["url"])]

    for heading in headings:
        heading_text = clean_text(heading.get_text(" ", strip=True))
        siblings = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in {"h2", "h3"}:
                break
            siblings.append(sibling)
        text = section_text_from_nodes([heading, *siblings])
        if len(text) < 140 or topic_score(f"{heading_text} {text}") == 0:
            continue
        fake = BeautifulSoup("", "html.parser")
        wrapper = fake.new_tag("div")
        for sibling in siblings:
            try:
                wrapper.append(BeautifulSoup(str(sibling), "html.parser"))
            except Exception:
                pass
        links = extract_links(wrapper, url) or all_links[:5]
        sections.append(Section(heading_text or title, text, links))
    if not sections:
        text = section_text_from_nodes(content.find_all(["p", "li"]))
        if len(text) > 180:
            sections.append(Section(title or "Page content", text, all_links))
    return title, sections, [link["url"] for link in all_links if allowed_url(link["url"])]


def chunks_for_section(text: str, max_words: int = 260, overlap: int = 45) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(start + 1, end - overlap)
    return chunks


def crawl(max_pages: int, delay: float) -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    robots = {domain: robot_parser(f"https://{domain}") for domain in ALLOWED_DOMAINS}
    queue = deque(normalize_url(url) for url in SEED_URLS if allowed_url(url))
    seen: set[str] = set()
    chunks: list[dict] = []
    crawled_at = datetime.now(timezone.utc).date().isoformat()

    while queue and len(seen) < max_pages:
        url = queue.popleft()
        if url in seen or not allowed_url(url):
            continue
        parsed = urlparse(url)
        if not robots[parsed.netloc].can_fetch(USER_AGENT, url):
            continue
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
        except Exception as exc:
            print(f"skip {url}: {exc}")
            seen.add(url)
            continue
        if "text/html" not in response.headers.get("content-type", ""):
            seen.add(url)
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        canonical = canonical_url(soup, url)
        if canonical in seen and canonical != url:
            continue
        title, sections, discovered = extract_sections(soup, canonical)
        page_text = f"{title} {' '.join(section.text for section in sections)}"
        if sections and topic_score(page_text) >= 2:
            print(f"crawl {canonical}")
            for section_index, section in enumerate(sections, start=1):
                for chunk_index, text in enumerate(chunks_for_section(section.text), start=1):
                    chunks.append(
                        {
                            "id": f"web-{len(chunks) + 1}",
                            "document": title or canonical,
                            "page": None,
                            "section": section.heading,
                            "text": text,
                            "source_type": "Official Kelley Website",
                            "url": canonical,
                            "title": title,
                            "heading": section.heading,
                            "crawled_at": crawled_at,
                            "links": section.links,
                            "priority": 1,
                        }
                    )
        seen.add(canonical)
        for href in discovered:
            if href not in seen and allowed_url(href) and topic_score(href.replace("-", " ")) > 0:
                queue.append(href)
        time.sleep(delay)
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Curated Kelley public-web crawler.")
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("KELLEY_WEB_MAX_PAGES", "80")))
    parser.add_argument("--delay", type=float, default=float(os.getenv("KELLEY_WEB_DELAY", "0.25")))
    args = parser.parse_args()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    chunks = crawl(max_pages=args.max_pages, delay=args.delay)
    with OUT_PATH.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    print(f"Wrote {len(chunks)} Kelley web chunks to {OUT_PATH}")


if __name__ == "__main__":
    main()
