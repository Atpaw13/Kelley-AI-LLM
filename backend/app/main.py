from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CHUNKS_PATH = DATA_DIR / "generated" / "chunks.jsonl"
CHROMA_PATH = Path(os.getenv("CHROMA_PATH", str(DATA_DIR / "chroma")))
if not CHROMA_PATH.is_absolute():
    CHROMA_PATH = ROOT / CHROMA_PATH
COLLECTION_NAME = os.getenv("KELLEY_CHROMA_COLLECTION", "kelley_sources")
OLLAMA_URL = os.getenv("OLLAMA_URL") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

app = FastAPI(title="Kelley AI Prototype API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class Source(BaseModel):
    id: str
    document: str
    page: int | None = None
    section: str | None = None
    excerpt: str
    score: float | None = None
    source_type: str = "Kelley Document"
    url: str | None = None
    title: str | None = None
    links: list[dict[str, str]] = Field(default_factory=list)


class RecommendedResource(BaseModel):
    title: str
    description: str
    url: str


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    source_count: int
    confidence: str
    suggested_followups: list[str]
    recommended_resources: list[RecommendedResource] = []


HANDBOOK_DOCUMENT = "Kelley Student Organization Handbook.pdf"
KNOWN_UNRESOLVED_ORG_URLS = {
    "https://www.tamidatindiana.com/",
    "https://cmciu.com/index.html",
    "https://beinvolved.indiana.edu/organization/passiveincome",
}


STOPWORDS = {
    "about",
    "and",
    "are",
    "can",
    "for",
    "from",
    "how",
    "kelley",
    "policy",
    "should",
    "the",
    "this",
    "what",
    "where",
    "with",
    "one",
    "my",
    "do",
    "i",
    "me",
}


def tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", text.lower()) if t not in STOPWORDS}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def classify_intent(question: str) -> str | None:
    q = normalize_text(question)
    if re.search(r"\bdrop\b|\bwithdraw\b", q) and re.search(r"\bclass|\bclasses|\bcourse|\bcourses\b", q):
        return "drop_class"
    if "advis" in q and ("appointment" in q or "schedule" in q):
        return "advising_appointment"
    if (
        "student organization" in q
        or "student organizations" in q
        or "get involved" in q
        or "involvement" in q
        or "club" in q
        or "clubs" in q
        or "organization" in q
        or "organizations" in q
        or "student government" in q
        or "ksg" in q
    ):
        return "student_organizations"
    if "undergraduate career services" in q or "career resources" in q or "career coaching" in q:
        return "career_resources"
    if "consulting" in q:
        return "consulting_start"
    if "career fair" in q:
        return "career_fair"
    if "resume" in q:
        return "resume"
    if "major" in q and ("decide" in q or "select" in q or "choose" in q or "resources" in q):
        return "major_resources"
    if "interview" in q:
        return "interview_prep"
    return None


INTENT_TERMS: dict[str, set[str]] = {
    "advising_appointment": {"advising", "advisor", "advisors", "appointment", "schedule", "soar", "one.iu"},
    "consulting_start": {
        "consulting",
        "advisory",
        "case",
        "interview",
        "career",
        "coaching",
        "kelley",
        "connect",
        "first",
        "year",
        "freshman",
    },
    "career_fair": {"career", "fair", "resume", "elevator", "pitch", "strategy", "research", "employers", "connect"},
    "resume": {"resume", "resumes", "star", "one", "page", "proofread", "accurate", "concise", "professional", "action", "results"},
    "major_resources": {"major", "majors", "career", "careers", "choosing", "selecting", "advisor", "advisors", "ucS", "research"},
    "interview_prep": {"interview", "interviews", "preparation", "prepare", "behavioral", "case", "questions", "company", "research"},
    "student_organizations": {"student", "organization", "organizations", "involvement", "clubs", "community", "interests"},
    "career_resources": {"career", "careers", "services", "coaching", "resume", "interview", "networking", "recruiting", "handshake"},
}


INTENT_EVIDENCE: dict[str, tuple[str, ...]] = {
    "advising_appointment": ("soar", "schedule an appointment", "kelley advising appointment"),
    "consulting_start": ("consulting", "case interviews", "career coaching", "kelley connect"),
    "career_fair": ("career fair", "elevator pitch", "selected companies", "kelley connect"),
    "resume": ("your resume should be", "star method", "one page", "proofread"),
    "major_resources": ("steps to choosing a major", "major selections", "academic advisors", "career paths"),
    "interview_prep": ("interview checklist", "behavioral interview", "sample interview questions", "know yourself"),
    "student_organizations": (
        "student organizations",
        "find your fit",
        "explore student organizations",
        "student organization",
        "recruiting information",
        "eligible applicants",
        "relevant industries",
        "time commitment",
    ),
    "career_resources": ("undergraduate career services", "career coaching", "resume", "interview preparation", "recruiting"),
}

INTENT_WEB_PREFIXES: dict[str, tuple[str, ...]] = {
    "advising_appointment": ("https://kelley.iu.edu/undergraduate/advising/",),
    "consulting_start": ("https://careers.kelley.iu.edu/", "https://kelley.iu.edu/undergraduate/advising/academic-support/"),
    "career_fair": ("https://careers.kelley.iu.edu/",),
    "resume": ("https://careers.kelley.iu.edu/",),
    "major_resources": ("https://kelley.iu.edu/undergraduate/academics/majors-minors-certificates/", "https://kelley.iu.edu/undergraduate/advising/"),
    "interview_prep": ("https://careers.kelley.iu.edu/",),
    "student_organizations": ("https://kelley.iu.edu/undergraduate/student-life/student-organizations/",),
    "career_resources": ("https://careers.kelley.iu.edu/",),
}

INTENT_ALLOWED_URLS: dict[str, set[str]] = {
    "advising_appointment": {
        "https://kelley.iu.edu/undergraduate/advising/index.html",
        "https://kelley.iu.edu/undergraduate/advising/contact-us/index.html",
    },
    "resume": {
        "https://careers.kelley.iu.edu/resources/kelley-resume-template-option-1/",
    },
    "major_resources": {
        "https://kelley.iu.edu/undergraduate/academics/majors-minors-certificates/index.html",
        "https://kelley.iu.edu/undergraduate/advising/index.html",
        "https://kelley.iu.edu/undergraduate/advising/contact-us/index.html",
    },
}

INTENT_SOURCE_DOCUMENTS: dict[str, set[str]] = {
    "student_organizations": {"Kelley Student Organization Handbook.pdf"},
}

INTENT_SOURCE_PAGES: dict[str, set[tuple[str, int]]] = {
    "advising_appointment": {
        ("The Kelley Playbook - Google Docs.pdf", 11),
        ("The Kelley Playbook - Google Docs.pdf", 12),
        ("The Kelley Playbook - Google Docs.pdf", 13),
    },
    "consulting_start": {
        ("Kelley-Career-Guide.pdf", 3),
        ("Kelley-Career-Guide.pdf", 5),
        ("Kelley-Career-Guide.pdf", 6),
        ("Kelley-Career-Guide.pdf", 10),
        ("Kelley-Career-Guide.pdf", 12),
        ("Kelley-Career-Guide.pdf", 38),
        ("The Kelley Playbook - Google Docs.pdf", 17),
        ("The Kelley Playbook - Google Docs.pdf", 18),
    },
    "career_fair": {
        ("Kelley-Career-Guide.pdf", 3),
        ("Kelley-Career-Guide.pdf", 5),
        ("Kelley-Career-Guide.pdf", 10),
        ("Kelley-Career-Guide.pdf", 11),
        ("Kelley-Career-Guide.pdf", 12),
    },
    "resume": {
        ("Kelley-Career-Guide.pdf", 18),
        ("Kelley-Career-Guide.pdf", 19),
        ("Kelley-Career-Guide.pdf", 20),
        ("Kelley-Career-Guide.pdf", 21),
        ("Kelley-Career-Guide.pdf", 22),
    },
    "major_resources": {
        ("Kelley-Career-Guide.pdf", 6),
        ("Kelley-Career-Guide.pdf", 7),
        ("The Kelley Playbook - Google Docs.pdf", 5),
        ("The Kelley Playbook - Google Docs.pdf", 6),
        ("The Kelley Playbook - Google Docs.pdf", 7),
        ("The Kelley Playbook - Google Docs.pdf", 8),
        ("The Kelley Playbook - Google Docs.pdf", 9),
        ("The Kelley Playbook - Google Docs.pdf", 10),
        ("The Kelley Playbook - Google Docs.pdf", 11),
        ("The Kelley Playbook - Google Docs.pdf", 13),
    },
    "interview_prep": {
        ("Kelley-Career-Guide.pdf", 34),
        ("Kelley-Career-Guide.pdf", 35),
        ("Kelley-Career-Guide.pdf", 36),
        ("Kelley-Career-Guide.pdf", 37),
        ("Kelley-Career-Guide.pdf", 38),
        ("Kelley-Career-Guide.pdf", 39),
        ("Kelley-Career-Guide.pdf", 40),
        ("Kelley-Career-Guide.pdf", 41),
        ("Kelley-Career-Guide.pdf", 42),
    },
}


ORG_TOPIC_TERMS = {
    "accounting",
    "advertising",
    "analytics",
    "consulting",
    "data",
    "entrepreneurship",
    "finance",
    "fintech",
    "fraternity",
    "government",
    "healthcare",
    "honor",
    "investing",
    "investment",
    "law",
    "marketing",
    "sales",
    "sports",
    "supply",
    "technology",
}


def organization_query_topics(question: str) -> set[str]:
    topics = {term for term in tokenize(question) if term in ORG_TOPIC_TERMS}
    lowered = question.lower()
    if "ai" in lowered:
        topics.add("ai")
    if "gen ai" in lowered:
        topics.add("gen")
    return topics


def detected_interest_labels(question: str) -> list[str]:
    q = normalize_text(question)
    labels: list[str] = []
    checks = [
        ("Freshman", r"\bfreshman\b|\bfirst[- ]year\b"),
        ("Finance", r"\bfinance\b|\binvesting\b|\binvestment\b|\bbanking\b"),
        ("Consulting", r"\bconsulting\b|\bconsultant\b"),
        ("Entrepreneurship", r"\bentrepreneur\w*\b|\bstartup\b|\bventure\b|\binnovation\b"),
        ("Technology", r"\btechnology\b|\btech\b|\bai\b|\bdata\b|\banalytics\b|\bsoftware\b"),
        ("Marketing", r"\bmarketing\b|\badvertising\b|\bsales\b"),
        ("Music", r"\bmusic\b"),
        ("Sports", r"\bsports\b|\bgolf\b"),
        ("Sustainability", r"\bsustainability\b|\bsustainable\b|\bsocial impact\b"),
        ("Accounting", r"\baccounting\b|\baudit\b|\btax\b"),
        ("Volunteering", r"\bvolunteer\b|\bservice\b|\bcommunity\b|\bphilanthropy\b"),
        ("Building / Creativity", r"\blego\b|\blegos\b|\bbuild\b|\bbuilding\b|\bmake\b|\bmaking\b|\bcreate\b|\bcreating\b|\bcreative\b|\bcreativity\b|\bdesign\b|\bhands[- ]on\b"),
    ]
    for label, pattern in checks:
        if re.search(pattern, q):
            labels.append(label)
    return labels or ["Student Organizations"]


def organization_topic_overlap(question: str, match: dict[str, Any]) -> int:
    text = normalize_text(f"{match.get('section') or ''} {match.get('text') or ''}")
    if "gen ai club" in question.lower():
        return 5 if "gen ai club" in text else 0
    if "student government" in question.lower() or "ksg" in question.lower():
        return 5 if "kelley student government" in text or "ksg" in text else 0
    if match.get("document") == "Kelley Student Organization Handbook.pdf":
        return len(organization_interest_hits(question, match)) * 5
    topics = organization_query_topics(question)
    if not topics:
        return 0
    return len(topics & tokenize(text))


def handbook_chunks() -> list[dict[str, Any]]:
    return [chunk for chunk in load_chunks() if chunk.get("document") == HANDBOOK_DOCUMENT]


def organization_name(match: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", match.get("text", "")).strip()
    section = (match.get("section") or "").strip()
    if " Description " in section:
        name = section.split(" Description ", 1)[0]
    elif " Description " in text:
        name = text.split(" Description ", 1)[0]
    else:
        name = section or text.split(" Relevant Industries ", 1)[0]
    name = re.sub(r"\blicnuoC\s+\S+\s*", "", name)
    name = re.sub(r"\blicnuoC\s+ytinretarF\s+lanoisseforP\s*", "", name)
    name = re.sub(r"\blanoisseforP\b|\bevitceleS\b|\bnepO\b", "", name)
    return re.sub(r"\s+", " ", name).strip(" .")[:100]


def organization_description(match: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", match.get("text", "")).strip()
    text = re.sub(r"\bevitceleS\b|\bnepO\b|\blicnuoC\s+\S+\b", "", text)
    if " Description " in text:
        text = text.split(" Description ", 1)[1]
    text = re.split(r" Relevant Industries | Recruiting Information | Time Commitment & Eligibility | Contact Information / Website ", text)[0]
    return trim_summary(text, limit=360)


def organization_link(match: dict[str, Any]) -> str | None:
    for link in match.get("links", []) or []:
        url = link.get("url", "")
        if url in KNOWN_UNRESOLVED_ORG_URLS:
            continue
        if url.startswith("http://") or url.startswith("https://"):
            return url
    return None


def organization_interest_hits(question: str, match: dict[str, Any]) -> set[str]:
    q = normalize_text(question)
    text = normalize_text(f"{match.get('section') or ''} {match.get('text') or ''}")
    page = match.get("page") or 0
    hits: set[str] = set()
    if re.search(r"\bfreshman\b|\bfirst[- ]year\b", q) and "eligible applicants: freshmen" in text:
        hits.add("freshman")
    if re.search(r"\bfinance\b|\binvesting\b|\binvestment\b|\bbanking\b", q):
        if 42 <= page <= 64 or page == 17:
            hits.add("finance")
    if re.search(r"\bconsulting\b|\bconsultant\b", q):
        if 7 <= page <= 18 or "consulting" in text:
            hits.add("consulting")
    if re.search(r"\bentrepreneur\w*\b|\bstartup\b|\bventure\b|\binnovation\b", q):
        if re.search(r"\bentrepreneur\w*\b|\bstartup\w*\b|\bventure\b|\binnovation\b|\bbusiness development\b|\bgenerate and preserve income\b", text):
            hits.add("entrepreneurship")
    if re.search(r"\blego\b|\blegos\b|\bbuild\b|\bbuilding\b|\bmake\b|\bmaking\b|\bcreate\b|\bcreating\b|\bcreative\b|\bcreativity\b|\bdesign\b|\bhands[- ]on\b", q):
        if re.search(r"\bhands[- ]on\b|\bbuild\w*\b|\bcreat\w*\b|\bcreative\b|\bdesign\b|\binnovation\b|\bai\b|\btechnology\b|\bdata\b|\bsoftware\b|\bhardware\b|\bproject\w*\b|\bcase competition\b", text):
            hits.add("building_creativity")
    if re.search(r"\btechnology\b|\btech\b|\bai\b|\bdata\b|\banalytics\b|\bsoftware\b", q):
        if 83 <= page <= 88 or page == 48 or re.search(r"\btechnology\b|\btech\b|\bai\b|\bdata\b|\banalytics\b|\bsoftware\b|\bcoding\b", text):
            hits.add("technology")
    if re.search(r"\bmarketing\b|\badvertising\b", q):
        if 80 <= page <= 81 or re.search(r"\bmarketing\b|\badvertising\b|\bbrand strategy\b|\bcreative development\b", text):
            hits.add("marketing")
    if re.search(r"\bsales\b", q):
        if 80 <= page <= 81 or re.search(r"\bsales\b|\bmarketing\b|\badvertising\b", text):
            hits.add("marketing")
    if "music" in q and "music" in text:
        hits.add("music")
    if re.search(r"\bsports\b|\bgolf\b", q) and re.search(r"\bsports\b|\bgolf\b", text):
        hits.add("sports")
    if re.search(r"\bsustainability\b|\bsustainable\b|\bsocial impact\b", q):
        if re.search(r"\bsustainab\w*\b|\bsocial impact\b|\bsocially responsible\b|\bnonprofits?\b|\bmission[- ]driven\b", text):
            hits.add("sustainability")
    if re.search(r"\baccounting\b|\baudit\b|\btax\b", q) and "accounting" in text:
        hits.add("accounting")
    if re.search(r"\bvolunteer\b|\bservice\b|\bphilanthropy\b|\boutside business\b", q):
        if re.search(r"\bservice\b|\bphilanthropy\b|\bnonprofits?\b|\bsocial impact\b|\bmission[- ]driven\b|\bsocially responsible\b|\bhealthcare\b|\bmental health\b|\bsustainable\b", text):
            hits.add("volunteering")
    return hits


def organization_recommendation_matches(question: str, limit: int = 5) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any], set[str]]] = []
    labels = detected_interest_labels(question)
    for chunk in handbook_chunks():
        if (chunk.get("page") or 0) < 7:
            continue
        if " Description " not in chunk.get("text", ""):
            continue
        if organization_name(chunk).lower().startswith("table of contents"):
            continue
        hits = organization_interest_hits(question, chunk)
        lowered_question = question.lower()
        if re.search(r"\bfinance\b|\binvesting\b|\binvestment\b|\bbanking\b", lowered_question) and "finance" not in hits:
            continue
        if re.search(r"\bconsulting\b|\bconsultant\b", lowered_question) and "consulting" not in hits:
            continue
        if re.search(r"\bmarketing\b|\badvertising\b|\bsales\b", lowered_question) and "marketing" not in hits:
            continue
        if not hits and "Student Organizations" not in labels:
            continue
        score = float(len(hits) * 2)
        if "freshman" in hits:
            score += 0.8
        if {"finance", "building_creativity"} <= hits:
            score += 2.2
        if {"finance", "entrepreneurship"} <= hits:
            score += 2.0
        if {"technology", "entrepreneurship"} <= hits:
            score += 1.8
        if {"marketing", "music"} <= hits or {"marketing", "building_creativity"} <= hits:
            score += 2.4
        if "marketing" in hits and (chunk.get("page") or 0) in {80, 81}:
            score += 3.0
        if {"consulting", "sports"} <= hits or {"consulting", "volunteering"} <= hits:
            score += 1.6
        if "lego" in question.lower() or "legos" in question.lower():
            text = normalize_text(chunk.get("text", ""))
            if re.search(r"\bentrepreneur\w*\b|\bstartup\w*\b|\bai\b|\btechnology\b|\bdata\b|\bhands[- ]on\b|\bcreate\b|\bbuild\b", text):
                score += 0.9
        if score > 0:
            item = dict(chunk)
            item["score"] = score
            item["interest_hits"] = sorted(hits)
            scored.append((score, item, hits))
    scored.sort(key=lambda item: item[0], reverse=True)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, item, _ in scored:
        name = organization_name(item).lower()
        if not name or name in seen:
            continue
        deduped.append(item)
        seen.add(name)
        if len(deduped) >= limit:
            break
    return deduped


def expanded_terms(question: str) -> set[str]:
    terms = tokenize(question)
    intent = classify_intent(question)
    if intent and intent in INTENT_TERMS:
        terms |= {term.lower() for term in INTENT_TERMS[intent]}
    if "freshman" in question.lower():
        terms |= {"first", "year"}
    return terms


def load_chunks() -> list[dict[str, Any]]:
    generated_dir = DATA_DIR / "generated"
    paths = sorted(generated_dir.glob("*.jsonl"))
    if CHUNKS_PATH.exists() and CHUNKS_PATH not in paths:
        paths.append(CHUNKS_PATH)
    chunks: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            chunks.extend(json.loads(line) for line in handle if line.strip())
    return chunks


def lexical_search(question: str, limit: int = 8) -> list[dict[str, Any]]:
    q_terms = expanded_terms(question)
    original_terms = tokenize(question)
    intent = classify_intent(question)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for chunk in load_chunks():
        chunk_text = normalize_text(chunk["text"])
        c_terms = tokenize(chunk_text)
        overlap = len(q_terms & c_terms)
        if overlap == 0:
            continue
        original_overlap = len(original_terms & c_terms)
        score = (overlap / max(len(q_terms), 1)) + (0.18 * original_overlap)
        if intent:
            for phrase in INTENT_EVIDENCE.get(intent, ()):
                if phrase in chunk_text:
                    score += 0.45
        source_priority = int(chunk.get("priority", 3))
        score += max(0, 4 - source_priority) * 0.12
        if chunk.get("source_type") == "Official Kelley Website":
            score += 0.25
        if intent and chunk.get("url") in INTENT_ALLOWED_URLS.get(intent, set()):
            score += 1.25
        if intent and chunk.get("url") and any(
            chunk["url"].startswith(prefix) for prefix in INTENT_WEB_PREFIXES.get(intent, ())
        ):
            score += 0.85
        if intent == "student_organizations":
            section_text = normalize_text(chunk.get("section") or "")
            candidate_text = f"{section_text} {chunk_text}"
            query_topics = organization_query_topics(question)
            if chunk.get("document") == "Kelley Student Organization Handbook.pdf":
                score += 0.45
                if query_topics:
                    topic_overlap = organization_topic_overlap(question, chunk)
                    score += topic_overlap * 1.25
                    if topic_overlap == 0:
                        score -= 1.1
                if "gen ai club" in question.lower() and "gen ai club" in candidate_text:
                    score += 3.0
                if "student government" in question.lower() and "kelley student government" in candidate_text:
                    score += 2.0
            elif query_topics:
                score -= 0.45
        if intent == "consulting_start" and chunk["document"] == "The Kelley Playbook - Google Docs.pdf" and chunk["page"] in {17, 18}:
            score += 0.35
        if intent == "major_resources" and chunk["document"] == "Kelley-Career-Guide.pdf" and chunk["page"] == 7:
            score += 0.55
        if intent == "interview_prep" and chunk["document"] == "Kelley-Career-Guide.pdf" and chunk["page"] in {34, 36, 37, 38, 42}:
            score += 0.35
        if intent == "resume" and chunk["document"] == "Kelley-Career-Guide.pdf" and chunk["page"] in {18, 19, 20, 21, 22}:
            score += 0.35
        if intent and intent in INTENT_SOURCE_PAGES and (chunk["document"], chunk["page"]) not in INTENT_SOURCE_PAGES[intent]:
            score -= 0.45
        if intent == "drop_class":
            score -= 1.0
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, chunk in ranked[:limit]:
        item = dict(chunk)
        item["score"] = score
        results.append(item)
    return results


def chroma_search(question: str, limit: int = 8) -> list[dict[str, Any]]:
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except Exception:
        return lexical_search(question, limit)

    if not CHROMA_PATH.exists():
        return lexical_search(question, limit)

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection = client.get_collection(COLLECTION_NAME)
        model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        embedding = model.encode(question).tolist()
        result = collection.query(query_embeddings=[embedding], n_results=limit)
    except Exception:
        return lexical_search(question, limit)

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    source_chunks = {chunk["id"]: chunk for chunk in load_chunks()}
    matches = []
    for idx, text in enumerate(documents):
        meta = metadatas[idx] or {}
        source_chunk = source_chunks.get(ids[idx], {})
        matches.append(
            {
                "id": ids[idx],
                "text": text,
                "document": meta.get("document", "Unknown document"),
                "page": int(meta.get("page", 0) or 0),
                "section": meta.get("section"),
                "source_type": meta.get("source_type") or "Kelley Document",
                "url": meta.get("url") or None,
                "title": meta.get("title") or None,
                "links": source_chunk.get("links", []),
                "priority": source_chunk.get("priority", meta.get("priority", 3)),
                "score": 1 / (1 + float(distances[idx])) if idx < len(distances) else None,
            }
        )
    blended: dict[str, dict[str, Any]] = {item["id"]: item for item in matches}
    for item in lexical_search(question, limit=limit):
        existing = blended.get(item["id"])
        if existing is None or (item.get("score") or 0) > (existing.get("score") or 0):
            blended[item["id"]] = item
    return sorted(blended.values(), key=lambda item: item.get("score") or 0, reverse=True)[:limit]


def relevant_matches(question: str, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intent = classify_intent(question)
    if intent == "drop_class":
        return []
    exact_urls = INTENT_ALLOWED_URLS.get(intent or "", set())
    allowed_documents = INTENT_SOURCE_DOCUMENTS.get(intent or "", set())
    if not intent or intent not in INTENT_SOURCE_PAGES:
        if intent in INTENT_WEB_PREFIXES:
            prefixes = INTENT_WEB_PREFIXES[intent]
            filtered = [
                m
                for m in matches
                if (
                    m.get("url")
                    and ((not exact_urls and any(m["url"].startswith(prefix) for prefix in prefixes)) or m["url"] in exact_urls)
                )
                or m.get("document") in allowed_documents
            ]
            if intent == "student_organizations" and organization_query_topics(question):
                topic_filtered = [
                    m
                    for m in filtered
                    if m.get("document") == "Kelley Student Organization Handbook.pdf"
                    and organization_topic_overlap(question, m) > 0
                ]
                if topic_filtered:
                    return sorted(
                        topic_filtered,
                        key=lambda item: (organization_topic_overlap(question, item), item.get("score") or 0),
                        reverse=True,
                    )
            return filtered or matches
        return matches
    allowed = INTENT_SOURCE_PAGES.get(intent, set())
    prefixes = INTENT_WEB_PREFIXES.get(intent, ())
    filtered = [
        m
        for m in matches
        if (
            m.get("url")
            and ((not exact_urls and any(m["url"].startswith(prefix) for prefix in prefixes)) or m["url"] in exact_urls)
        )
        or (m["document"], m.get("page")) in allowed
        or m.get("document") in allowed_documents
    ]
    return filtered or matches


def needs_human_judgment(question: str) -> bool:
    patterns = [
        r"\bdrop (this|a|my) class\b",
        r"\bshould i drop\b",
        r"\bshould i withdraw\b",
        r"\bshould i change\b.*\bmajor\b",
        r"\bwhich class should\b",
        r"\bwhat should i major\b",
        r"\bcan i get an exception\b",
    ]
    return any(re.search(pattern, question.lower()) for pattern in patterns)


def context_is_adequate(question: str, matches: list[dict[str, Any]]) -> bool:
    if not matches:
        return False
    intent = classify_intent(question)
    if intent == "drop_class":
        return False
    matches = relevant_matches(question, matches)
    if intent in INTENT_EVIDENCE:
        top_text = normalize_text(" ".join(m["text"] for m in matches[:5]))
        return any(phrase in top_text for phrase in INTENT_EVIDENCE[intent])
    top_score = matches[0].get("score") or 0
    q_terms = tokenize(question)
    source_terms = set().union(*(tokenize(m["text"]) for m in matches[:3]))
    if not q_terms:
        return False
    coverage = len(q_terms & source_terms) / len(q_terms)
    return coverage >= 0.66 or top_score >= 0.72


def build_prompt(question: str, matches: list[dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"Source {idx + 1}: {m.get('source_type', 'Kelley Document')} | {m.get('title') or m['document']} | {m.get('url') or ('p. ' + str(m.get('page')))} | {m.get('section') or 'Section unavailable'}\n{m['text']}"
        for idx, m in enumerate(matches)
    )
    return f"""You are Kelley AI Prototype, a demonstration assistant for Kelley School of Business students.
Use only the supplied Kelley source context. Do not use general knowledge for Kelley-specific facts.
If the context does not verify the answer, say: "I couldn't verify that from the Kelley information currently available to this prototype."
For individualized academic, career, or personal decisions, avoid making the decision and recommend the relevant Kelley office when the context supports it.

Format the answer as a concise structured page:
- Start with a direct opening sentence.
- Use numbered steps when helpful.
- Add a short "Recommended Kelley resources" section only when supported by the context.

Student question:
{question}

Kelley source context:
{context}
"""


def ollama_answer(question: str, matches: list[dict[str, Any]]) -> str | None:
    if os.getenv("KELLEY_ENABLE_OLLAMA", "false").lower() not in {"1", "true", "yes"}:
        return None
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": build_prompt(question, matches), "stream": False},
            timeout=45,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip() or None
    except Exception:
        return None


def strip_inline_resources(answer: str) -> str:
    return re.sub(r"\n+Recommended Kelley resources\n+.*\Z", "", answer.strip(), flags=re.IGNORECASE | re.DOTALL).strip()


def trim_summary(text: str, limit: int = 340) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .")
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = ""
    for sentence in sentences:
        candidate = f"{summary} {sentence}".strip()
        if len(candidate) > limit:
            break
        summary = candidate
    if summary:
        return summary.strip(" .")
    return text[:limit].rsplit(" ", 1)[0].strip(" .")


def organization_fit_sentence(question: str, match: dict[str, Any]) -> str:
    hits = set(match.get("interest_hits") or organization_interest_hits(question, match))
    description = organization_description(match)
    if {"finance", "building_creativity"} <= hits:
        return f"Good fit for finance plus building/creating because the source describes {description[0].lower() + description[1:] if description else 'hands-on finance-related work'}."
    if {"finance", "entrepreneurship"} <= hits:
        return f"Good fit for finance and entrepreneurship because the source connects the organization to {description[0].lower() + description[1:] if description else 'venture or income-building interests'}."
    if {"technology", "entrepreneurship"} <= hits:
        return f"Good fit for technology and entrepreneurship because the source describes {description[0].lower() + description[1:] if description else 'technology-focused building and innovation'}."
    if {"marketing", "music"} <= hits:
        return f"Good fit for marketing and music because the source describes {description[0].lower() + description[1:] if description else 'the business side of music'}."
    if {"marketing", "building_creativity"} <= hits:
        return f"Good fit for marketing and creativity because the source describes {description[0].lower() + description[1:] if description else 'creative project work'}."
    if {"consulting", "volunteering"} <= hits:
        return f"Good fit for consulting beyond business because the source describes {description[0].lower() + description[1:] if description else 'mission-driven or community-oriented consulting'}."
    if {"consulting", "sports"} <= hits:
        return f"Good fit for consulting and sports because the source describes {description[0].lower() + description[1:] if description else 'business work connected to sports'}."
    if description:
        return f"Why it fits: {description}."
    return "Why it fits: this organization matched interests found in the indexed Kelley Student Organization Handbook."


def markdown_link(label: str, url: str | None) -> str:
    if not url:
        return ""
    return f"[{label}]({url})"


def organization_answer(question: str, matches: list[dict[str, Any]]) -> str | None:
    handbook_matches = [m for m in matches if m.get("document") == HANDBOOK_DOCUMENT]
    if not handbook_matches:
        return None
    labels = detected_interest_labels(question)
    interest_line = " · ".join(labels)
    lego_note = ""
    if re.search(r"\blego\b|\blegos\b", question.lower()):
        lego_note = (
            "\n\nA NOTE ON LEGO\n"
            "I couldn't verify a LEGO-specific organization in the Kelley information currently available to this prototype, "
            "but there are several verified organizations that may fit the broader combination of finance, building, creativity, innovation, or technology."
        )
    recommendation_blocks = []
    for index, match in enumerate(handbook_matches[:5], start=1):
        name = organization_name(match)
        if not name:
            continue
        url = organization_link(match)
        link_line = markdown_link("View organization →", url)
        block = f"{index}. {name}\n{organization_fit_sentence(question, match)}"
        if link_line:
            block += f"\n{link_line}"
        recommendation_blocks.append(block)
    if not recommendation_blocks:
        return None
    resource_link = markdown_link(
        "Explore Kelley student organizations →",
        "https://kelley.iu.edu/undergraduate/student-life/student-organizations/index.html",
    )
    return (
        f"YOUR INTERESTS\n{interest_line}"
        f"{lego_note}\n\n"
        "RECOMMENDED ORGANIZATIONS\n\n"
        + "\n\n".join(recommendation_blocks)
        + "\n\nWHY THESE FIT\n"
        "These recommendations are drawn from indexed Kelley/IU organization sources and prioritize overlap across the interests in your question, rather than matching on one keyword alone.\n\n"
        "KELLEY RESOURCES\n"
        f"{resource_link}"
    )


def fallback_answer(question: str, matches: list[dict[str, Any]]) -> str:
    intent = classify_intent(question)
    matches = relevant_matches(question, matches)
    if needs_human_judgment(question) and not context_is_adequate(question, matches):
        return (
            "That depends on your circumstances, so this prototype should not make the decision for you. "
            "I couldn't verify the procedural answer from the Kelley information currently available to this prototype."
        )

    if not context_is_adequate(question, matches):
        return "I couldn't verify that from the Kelley information currently available to this prototype."

    q = question.lower()
    combined = " ".join(m["text"] for m in matches[:5]).lower()
    if intent == "advising_appointment":
        return (
            "The Kelley Playbook gives a clear path for scheduling a Kelley Advising appointment.\n\n"
            "01 Start in One.IU\n"
            "Visit One.IU and log in with your IUB credentials.\n\n"
            "02 Search for SOAR\n"
            "Type SOAR into the One.IU search bar and select SOAR.\n\n"
            "03 Choose an advisor appointment\n"
            "Under Your Advisor, select Schedule an Appointment and follow the instructions.\n\n"
            "04 Use Kelley advising for planning questions\n"
            "The Playbook says Kelley Academic Advisors can help with a four-year plan, potential major selections, Kelley organizations, and other Kelley questions.\n\n"
            "Recommended Kelley resources\n"
            "Use Kelley Academic Advising and the SOAR appointment steps in The Kelley Playbook."
        )

    if intent == "career_fair" and {"resume", "elevator", "research", "kelley", "connect"} & tokenize(combined):
        return (
            "Here is a good starting point from the Kelley career materials.\n\n"
            "01 Prepare an error-free resume\n"
            "Bring current copies, and have your resume reviewed by an Undergraduate Career Services coach before the fair.\n\n"
            "02 Practice your elevator pitch\n"
            "Be ready to introduce your name, major, and job goal clearly when you meet recruiters.\n\n"
            "03 Plan your employer strategy\n"
            "Use Kelley Connect or the career fair app to identify participating companies and choose the employers you want to prioritize.\n\n"
            "04 Research before you go\n"
            "Review employer profiles, open roles, and company information so your conversations are specific.\n\n"
            "05 Use the fair for exploration\n"
            "The career guide frames career fairs as a way to investigate positions, learn about fields, and meet representatives from organizations.\n\n"
            "Recommended Kelley resources\n"
            "Start with Undergraduate Career Services, Kelley Connect, and the career fair checklist in the Kelley Career Guide."
        )

    if intent == "resume":
        return (
            "Here is a good starting point from the Kelley career materials.\n\n"
            "01 Keep it one page\n"
            "The Kelley Career Guide says a resume should be one page, accurate, concise, professional, and customized to the position.\n\n"
            "02 Make it action and results oriented\n"
            "Use the STAR method to describe the situation, task, action, and result behind your experiences.\n\n"
            "03 Avoid simply listing duties\n"
            "The guide says recruiters prefer accomplishments and impact over a list of tasks.\n\n"
            "04 Proofread carefully\n"
            "The guide calls for proofreading multiple times for grammar and spelling.\n\n"
            "05 Use Kelley examples and reviews\n"
            "The career guide includes resume critique examples and notes that templates and examples are available on careers.kelley.iu.edu.\n\n"
            "Recommended Kelley resources\n"
            "Use the Kelley Career Guide resume section, Undergraduate Career Services, and Kelley resume examples."
        )

    if intent == "consulting_start":
        return (
            "Here is a good starting point from the Kelley career materials.\n\n"
            "01 Start with career exploration\n"
            "The career guide encourages first-year students to acclimate to college, focus on academics, and explore majors and careers early.\n\n"
            "02 Use Undergraduate Career Services\n"
            "UCS offers career coaching, drop-ins, workshops, guest speakers, career fairs, job shadows, and other career-development support.\n\n"
            "03 Use Kelley Connect for recruiting activity\n"
            "Kelley Connect is the hub for job postings, career fairs, company presentations, workshops, and recruiting resources.\n\n"
            "04 Learn how consulting interviews work\n"
            "The career guide identifies case interviews as typical for consulting and advisory roles, so case practice should be part of your preparation.\n\n"
            "05 Attend relevant fairs and presentations\n"
            "The guide lists a Consulting, Information Systems, and Supply Chain fair among the fall recruiting events.\n\n"
            "Recommended Kelley resources\n"
            "Start with Undergraduate Career Services, Kelley Connect, and the case interview guidance in the Kelley Career Guide."
        )

    if intent == "major_resources":
        return (
            "Here is a good starting point from the Kelley materials available to this prototype.\n\n"
            "01 Use the Kelley Career Guide's major-selection steps\n"
            "The guide recommends taking courses that interest you, getting involved in activities, and reflecting on what you like doing, what you value, and your strengths.\n\n"
            "02 Research Kelley majors\n"
            "The guide says to review all business majors offered at Kelley, visit academic department pages, and consider whether you would enjoy the classes for each major.\n\n"
            "03 Talk with Kelley advisors\n"
            "The Kelley Playbook says Kelley Academic Advisors can help students gain insight on potential major selections.\n\n"
            "04 Use career-path resources\n"
            "The Playbook points to Undergraduate Career Services for learning about career paths and recommends researching major-specific career outcome data.\n\n"
            "Recommended Kelley resources\n"
            "Use the Kelley Career Guide's Exploring Majors & Careers section, Kelley Academic Advising, Undergraduate Career Services, and major outcome data referenced in The Kelley Playbook."
        )

    if intent == "interview_prep":
        return (
            "Here is a good starting point from the Kelley career materials.\n\n"
            "01 Know yourself before the interview\n"
            "The Kelley Career Guide says to prepare to talk about your education, experiences, accomplishments, passions, skills, strengths, and goals.\n\n"
            "02 Tailor your preparation\n"
            "The interview checklist says to tailor preparation and company research for each interview.\n\n"
            "03 Practice behavioral examples\n"
            "The guide explains that behavioral interviews use past performance as a predictor of future behavior, so prepare specific examples from your experiences.\n\n"
            "04 Prepare thoughtful questions\n"
            "The guide lists questions students can ask employers about the role, training, culture, career path, and organizational challenges.\n\n"
            "05 Review sample interview questions\n"
            "The guide includes sample questions and says to review them to prepare for upcoming interviews.\n\n"
            "Recommended Kelley resources\n"
            "Use the Kelley Career Guide interview section, UCS interview resources, and Kelley Connect."
        )

    if intent == "student_organizations":
        org_answer = organization_answer(question, matches)
        if org_answer:
            return org_answer
        return (
            "Here is a good starting point from the Kelley website.\n\n"
            "01 Explore Kelley student organizations\n"
            "Use the Kelley student organizations pages to find communities connected to your interests and goals.\n\n"
            "02 Look for fit, not just a title\n"
            "Review organization descriptions and opportunities to understand where you might contribute and build relationships.\n\n"
            "03 Use student-life resources\n"
            "Kelley student-life pages point students toward involvement opportunities and organization resources.\n\n"
            "04 Follow the official Kelley links\n"
            "Use the current Kelley website source shown here when you are ready to explore specific organizations."
        )

    if intent == "career_resources":
        return (
            "Here is a good starting point from Kelley Undergraduate Career Services.\n\n"
            "01 Start with Undergraduate Career Services\n"
            "Kelley career resources support career exploration, resumes, interviewing, networking, recruiting, and internships.\n\n"
            "02 Use Kelley career tools\n"
            "The Kelley career site and Kelley Connect resources connect students with recruiting activity, job postings, career fairs, workshops, and employer information.\n\n"
            "03 Choose the resource that matches your next step\n"
            "Use resume resources for application materials, interview resources for preparation, and career coaching for personalized guidance."
        )

    if needs_human_judgment(question):
        lead = (
            "That depends on your circumstances, so this prototype should not make the decision for you. "
            "Use the Kelley information below as a starting point and speak with the relevant Kelley office for individualized guidance."
        )
    else:
        lead = "Here is a good starting point from the Kelley materials available to this prototype."

    points = []
    for match in matches[:4]:
        snippet = re.sub(r"\s+", " ", match["text"]).strip()
        sentences = re.split(r"(?<=[.!?])\s+", snippet)
        point = sentences[0][:260].strip()
        if point:
            points.append(point)

    body = "\n".join(f"{idx + 1:02d} {point}" for idx, point in enumerate(points))
    return f"{lead}\n\n{body}\n\nRecommended Kelley resources\nReview the listed source excerpts and follow up with the Kelley office or resource named in the source when appropriate."


def followups(question: str) -> list[str]:
    q = question.lower()
    if "career" in q or "resume" in q or "fair" in q or "consulting" in q:
        return [
            "What should I do before meeting an employer?",
            "How can I strengthen my resume?",
            "What should I do after a career fair?",
        ]
    if "class" in q or "academic" in q or "advis" in q:
        return [
            "What academic resources are available?",
            "How can I prepare for advising?",
            "Where can I find support if I am struggling in a class?",
        ]
    return [
        "What Kelley resources should I use next?",
        "Which student organizations are mentioned?",
        "How should I prepare before asking for help?",
    ]


RESOURCE_LIBRARY = {
    "advising": {
        "title": "Academic Advising",
        "description": "Plan your degree and discuss academic goals",
        "urls": (
            "https://kelley.iu.edu/undergraduate/advising/contact-us/index.html",
            "https://kelley.iu.edu/undergraduate/advising/index.html",
        ),
    },
    "ucs": {
        "title": "Undergraduate Career Services",
        "description": "Personalized career exploration and recruiting guidance",
        "urls": ("https://careers.kelley.iu.edu/",),
    },
    "organizations": {
        "title": "Student Organizations",
        "description": "Explore organizations aligned with your interests",
        "urls": ("https://kelley.iu.edu/undergraduate/student-life/student-organizations/index.html",),
    },
    "career": {
        "title": "Career Resources",
        "description": "Interviewing, networking and recruiting tools",
        "urls": (
            "https://careers.kelley.iu.edu/",
        ),
    },
    "resume_templates": {
        "title": "Kelley Resume Templates",
        "description": "Kelley resume examples and formatting support",
        "urls": ("https://careers.kelley.iu.edu/resources/kelley-resume-template-option-1/",),
    },
    "majors": {
        "title": "Majors, Minors, and Certificates",
        "description": "Explore Kelley academic options",
        "urls": ("https://kelley.iu.edu/undergraduate/academics/majors-minors-certificates/index.html",),
    },
}


def recommended_resources(question: str, matches: list[dict[str, Any]]) -> list[RecommendedResource]:
    available_urls = {m.get("url") for m in matches if m.get("url")}
    ingested_urls = {m.get("url") for m in load_chunks() if m.get("url")}
    for match in matches:
        for link in match.get("links", []) or []:
            if link.get("url"):
                available_urls.add(link["url"])
    intent = classify_intent(question)
    keys: list[str]
    if intent == "advising_appointment":
        keys = ["advising"]
    elif intent == "resume":
        keys = ["resume_templates", "ucs", "career"]
    elif intent in {"consulting_start", "career_fair", "interview_prep", "career_resources"}:
        keys = ["ucs", "career"]
    elif intent == "student_organizations":
        keys = ["organizations"]
    elif intent == "major_resources":
        keys = ["majors", "advising", "ucs"]
    else:
        keys = ["ucs", "organizations", "career"]

    resources = []
    seen = set()
    for key in keys:
        item = RESOURCE_LIBRARY[key]
        url = next((candidate for candidate in item["urls"] if candidate in available_urls), None)
        if url is None:
            url = next((candidate for candidate in item["urls"] if candidate in ingested_urls), None)
        if not url or url in seen:
            continue
        resources.append(RecommendedResource(title=item["title"], description=item["description"], url=url))
        seen.add(url)
    return resources[:3]


def group_source_matches(matches: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for match in matches:
        key = match.get("url") or f"{match.get('document')}:{match.get('page')}"
        if key not in grouped:
            grouped[key] = dict(match)
            continue
        existing = grouped[key]
        existing["score"] = max(existing.get("score") or 0, match.get("score") or 0)
        if len(existing.get("text", "")) < 900 and match.get("text") not in existing.get("text", ""):
            existing["text"] = f"{existing.get('text', '')} {match.get('text', '')}".strip()
        existing_links = {link.get("url") for link in existing.get("links", [])}
        for link in match.get("links", []) or []:
            if link.get("url") not in existing_links:
                existing.setdefault("links", []).append(link)
                existing_links.add(link.get("url"))
    return sorted(grouped.values(), key=lambda item: item.get("score") or 0, reverse=True)[:limit]


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "chunks_indexed": len(load_chunks()), "collection": COLLECTION_NAME}


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()
    matches = chroma_search(question)
    matches = relevant_matches(question, matches)
    visible_basis = matches
    if classify_intent(question) == "student_organizations":
        org_matches = organization_recommendation_matches(question, limit=5)
        if org_matches:
            org_matches = relevant_matches(question, org_matches) or org_matches
            matches = org_matches
            visible_basis = org_matches
    adequate = context_is_adequate(question, matches)
    answer = ollama_answer(question, matches) if adequate else None
    if answer is None:
        answer = fallback_answer(question, matches)
    answer = strip_inline_resources(answer)

    visible_matches = group_source_matches(visible_basis, limit=5) if adequate else []
    sources = [
        Source(
            id=m["id"],
            document=m["document"],
            page=m["page"],
            section=m.get("section"),
            excerpt=re.sub(r"\s+", " ", m["text"]).strip()[:900],
            score=m.get("score"),
            source_type=m.get("source_type") or "Kelley Document",
            url=m.get("url"),
            title=m.get("title"),
            links=m.get("links") or [],
        )
        for m in visible_matches
    ]
    return AskResponse(
        answer=answer,
        sources=sources,
        source_count=len(sources),
        confidence="grounded" if adequate else "unverified",
        suggested_followups=followups(question),
        recommended_resources=recommended_resources(question, visible_matches) if adequate else [],
    )
