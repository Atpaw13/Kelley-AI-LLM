"use client";

import { ArrowRight, ChevronDown, ChevronUp, ExternalLink, FileText, Loader2, Search, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Source = {
  id: string;
  document: string;
  page?: number | null;
  section?: string | null;
  excerpt: string;
  score?: number | null;
  source_type?: string;
  url?: string | null;
  title?: string | null;
  links?: { label: string; url: string }[];
};

type RecommendedResource = {
  title: string;
  description: string;
  url: string;
};

type AskResponse = {
  answer: string;
  sources: Source[];
  source_count: number;
  confidence: "grounded" | "unverified";
  suggested_followups: string[];
  recommended_resources: RecommendedResource[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const suggestedQuestions = [
  "I'm a freshman interested in consulting. Where should I start?",
  "How do I schedule an academic advising appointment?",
  "How should I prepare for a career fair?",
  "What resources can help me improve my resume?",
  "I'm interested in finance. What should I explore?",
];

const categories = ["Academics", "Careers", "Involvement", "Recruiting", "I-Core", "Resources"];
const featuredResources = [
  {
    title: "Undergraduate Career Services",
    description: "Personalized career exploration and recruiting guidance",
    url: "https://careers.kelley.iu.edu/",
  },
  {
    title: "Student Organizations",
    description: "Explore organizations aligned with your interests",
    url: "https://kelley.iu.edu/undergraduate/student-life/student-organizations/index.html",
  },
  {
    title: "Career Resources",
    description: "Interviewing, networking and recruiting tools",
    url: "https://careers.kelley.iu.edu/",
  },
];

function TridentMark() {
  return (
    <div className="grid h-14 w-14 place-items-center bg-crimson text-white" aria-label="Indiana University trident">
      <svg className="h-8 w-8" viewBox="0 0 28 34" aria-hidden="true">
        <path
          d="M-3.34344e-05 4.70897H8.83308V7.174H7.1897V21.1426H10.6134V2.72321H8.83308V0.121224H18.214V2.65476H16.2283V21.1426H19.7889V7.174H18.214V4.64047H27.0471V7.174H25.0614V23.6761L21.7746 26.8944H16.2967V30.455H18.214V33.8787H8.76463V30.592H10.6819V26.8259H5.20403L1.91726 23.6077V7.174H-3.34344e-05V4.70897Z"
          fill="currentColor"
        />
      </svg>
    </div>
  );
}

function formatAnswer(answer: string) {
  return answer
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function formatDocumentName(document: string) {
  return document
    .replace(/\.pdf$/i, "")
    .replace(/^The Kelley Playbook - Google Docs$/i, "The Kelley Playbook")
    .replace(/-/g, " ");
}

function sourceDisplayName(source: Source) {
  if (source.source_type === "Official Kelley Website") {
    return source.title || source.document;
  }
  return formatDocumentName(source.document);
}

function cleanExcerpt(excerpt: string) {
  return excerpt
    .replace(/\bcAREER\b/g, "Career")
    .replace(/\bFair the Prepare\b/g, "fair: Prepare")
    .replace(/\s+co$/i, "")
    .trim();
}

function formatSectionName(source: Source) {
  const key = `${source.document}:${source.page}`;
  const pageTitles: Record<string, string> = {
    "The Kelley Playbook - Google Docs.pdf:5": "Selecting a Major",
    "The Kelley Playbook - Google Docs.pdf:10": "Major and co-major guidance",
    "The Kelley Playbook - Google Docs.pdf:11": "Major and career-path resources",
    "The Kelley Playbook - Google Docs.pdf:12": "Academic Resources",
    "The Kelley Playbook - Google Docs.pdf:13": "Kelley Advising appointments",
    "The Kelley Playbook - Google Docs.pdf:17": "Consulting recruiting preparation",
    "The Kelley Playbook - Google Docs.pdf:18": "Consulting skills and resources",
    "Kelley-Career-Guide.pdf:3": "Introduction to Career Services",
    "Kelley-Career-Guide.pdf:5": "Online career resources",
    "Kelley-Career-Guide.pdf:6": "Career development action plan",
    "Kelley-Career-Guide.pdf:7": "Exploring Majors & Careers",
    "Kelley-Career-Guide.pdf:10": "Career fairs",
    "Kelley-Career-Guide.pdf:11": "Career fair checklist",
    "Kelley-Career-Guide.pdf:12": "Kelley Connect",
    "Kelley-Career-Guide.pdf:18": "Resume standards",
    "Kelley-Career-Guide.pdf:19": "STAR Method for resumes",
    "Kelley-Career-Guide.pdf:20": "Resume critique",
    "Kelley-Career-Guide.pdf:21": "Resume critique after example",
    "Kelley-Career-Guide.pdf:22": "First-year resume example",
    "Kelley-Career-Guide.pdf:34": "Interview preparation",
    "Kelley-Career-Guide.pdf:35": "Effective interviewing",
    "Kelley-Career-Guide.pdf:36": "Interview checklist",
    "Kelley-Career-Guide.pdf:37": "Behavioral interviews",
    "Kelley-Career-Guide.pdf:38": "Case interviews",
    "Kelley-Career-Guide.pdf:39": "Interview logistics",
    "Kelley-Career-Guide.pdf:40": "Virtual interviews",
    "Kelley-Career-Guide.pdf:41": "Closing the interview",
    "Kelley-Career-Guide.pdf:42": "Sample interview questions",
  };
  if (pageTitles[key]) return pageTitles[key];
  const section = source.section;
  if (!section) return source.source_type === "Official Kelley Website" ? "Official Kelley Website" : "Section unavailable";
  if (/^explore$/i.test(section)) return "Introduction to Career Services";
  if (/^online on the ucs website/i.test(section)) return "Online career resources";
  if (/^start the ma/i.test(section)) return "Career development action plan";
  return section;
}

export default function Home() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [openSourceId, setOpenSourceId] = useState<string | null>(null);
  const responseRef = useRef<HTMLElement | null>(null);
  const questionRef = useRef<HTMLTextAreaElement | null>(null);

  const answerLines = useMemo(() => formatAnswer(result?.answer ?? ""), [result]);

  useEffect(() => {
    if (loading || result || error) {
      window.setTimeout(() => responseRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    }
  }, [loading, result, error]);

  async function askKelley(nextQuestion = question) {
    const trimmed = nextQuestion.trim();
    if (!trimmed || loading) return;
    setQuestion(trimmed);
    setLoading(true);
    setError("");
    setResult(null);
    setOpenSourceId(null);

    try {
      const response = await fetch(`${API_URL}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      if (!response.ok) throw new Error("The Kelley prototype service did not return an answer.");
      setResult((await response.json()) as AskResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong while searching Kelley resources.");
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void askKelley(questionRef.current?.value ?? question);
  }

  return (
    <main className="min-h-screen bg-white">
      <header className="border-b border-black/10 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
          <div className="flex items-center gap-4">
            <TridentMark />
            <div className="leading-tight">
              <p className="font-bold-iu text-xl text-ink">Kelley School of Business</p>
              <p className="text-sm text-black/62">Indiana University</p>
            </div>
          </div>
          <div className="hidden items-center gap-2 border border-crimson/25 bg-crimson/5 px-3 py-2 text-sm font-bold text-crimson sm:flex">
            <ShieldCheck className="h-4 w-4" />
            AI Resource Prototype
          </div>
        </div>
        <nav className="bg-ink text-white" aria-label="Prototype section navigation">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 overflow-x-auto px-5">
            <div className="flex min-h-12 items-center gap-7 text-sm font-bold">
              {["Undergraduate", "Academics", "Careers", "Student Life", "Resources"].map((item) => (
                <span key={item} className="whitespace-nowrap">{item}</span>
              ))}
            </div>
            <span className="font-mono-iu hidden whitespace-nowrap text-xs uppercase text-white/70 md:block">Limited demo</span>
          </div>
        </nav>
      </header>

      <section className="border-b border-black/10 bg-limestone">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-10 lg:grid-cols-[1fr_320px] lg:py-12">
          <div>
          <p className="font-mono-iu mb-4 text-xs uppercase text-crimson">Kelley AI Resource Prototype</p>
          <h2 className="font-bold-iu max-w-3xl text-3xl leading-tight text-ink sm:text-4xl lg:text-[44px]">
            What can we help you find at Kelley?
          </h2>
          <p className="mt-4 max-w-2xl text-lg leading-8 text-black/68">
            Ask questions about Kelley academics, careers, involvement, recruiting, and student resources.
          </p>

          <form onSubmit={onSubmit} className="mt-7 border border-black/15 bg-white p-2 shadow-soft">
            <label htmlFor="question" className="sr-only">
              Ask a question about Kelley
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <textarea
                id="question"
                ref={questionRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onInput={(event) => setQuestion(event.currentTarget.value)}
                placeholder="Ask a question about Kelley..."
                className="min-h-24 flex-1 resize-none border-0 bg-white px-4 py-3 text-base leading-7 text-ink outline-none placeholder:text-black/42 sm:min-h-14"
              />
              <button
                type="submit"
                disabled={loading}
                className="font-bold-iu inline-flex min-w-28 items-center justify-center gap-2 bg-crimson px-5 py-3 text-white transition hover:bg-[#7d0000] disabled:cursor-not-allowed disabled:bg-black/25"
              >
                {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Search className="h-5 w-5" />}
                Ask
              </button>
            </div>
          </form>

          <div className="mt-5 grid gap-x-8 gap-y-2 border-t border-black/10 pt-5 sm:grid-cols-2">
            {suggestedQuestions.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => void askKelley(item)}
                className="group flex items-start justify-between gap-3 py-2 text-left text-sm font-bold leading-6 text-ink transition hover:text-crimson"
              >
                <span>{item}</span>
                <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-crimson transition group-hover:translate-x-1" />
              </button>
            ))}
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            <span className="font-bold-iu text-black/50">Explore</span>
            {categories.map((category) => (
              <span key={category} className="font-bold text-crimson">
                {category}
              </span>
            ))}
          </div>
        </div>

        <aside className="border-t-4 border-crimson bg-white p-6 shadow-soft">
          <p className="font-mono-iu text-xs uppercase text-crimson">Knowledge base</p>
          <h3 className="font-bold-iu mt-3 text-xl text-ink">Kelley sources in this prototype</h3>
          <div className="mt-6 grid gap-3 border-t border-black/10 pt-5">
            {featuredResources.map((resource) => (
              <a
                key={resource.title}
                href={resource.url}
                target="_blank"
                rel="noreferrer"
                className="group flex gap-3 border-l-2 border-crimson/35 pl-3"
              >
                <FileText className="mt-1 h-4 w-4 shrink-0 text-crimson" />
                <div>
                  <p className="font-bold-iu text-sm text-ink group-hover:text-crimson">{resource.title}</p>
                  <p className="mt-1 text-sm leading-5 text-black/58">{resource.description}</p>
                  <p className="font-bold-iu mt-2 inline-flex items-center gap-1 text-sm text-crimson">
                    Visit <ArrowRight className="h-3.5 w-3.5" />
                  </p>
                </div>
              </a>
            ))}
          </div>
        </aside>
        </div>
      </section>

      <section ref={responseRef} className="mx-auto max-w-6xl scroll-mt-4 px-5 py-9">
        {loading && (
          <div className="border border-black/10 bg-white p-6 shadow-soft">
            <div className="flex items-center gap-3 text-ink">
              <Loader2 className="h-5 w-5 animate-spin" />
              <p className="font-bold-iu">Searching approved Kelley resources...</p>
            </div>
            <div className="mt-5 grid gap-3">
              <div className="h-3 w-2/3 bg-black/10" />
              <div className="h-3 w-5/6 bg-black/10" />
              <div className="h-3 w-1/2 bg-black/10" />
            </div>
          </div>
        )}

        {error && (
          <div className="border-l-4 border-crimson bg-limestone p-6 text-ink shadow-soft">
            <p className="font-bold-iu">Unable to retrieve Kelley information</p>
            <p className="mt-2 text-sm leading-6 text-black/65">{error}</p>
          </div>
        )}

        {result && (
          <article className="border border-black/10 bg-white shadow-soft">
            <div className="border-b border-black/10 p-6 sm:p-7">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="font-mono-iu text-xs uppercase text-crimson">Question</p>
                <p className="font-mono-iu text-xs uppercase text-black/50">
                  Answer grounded in {result.source_count} Kelley {result.source_count === 1 ? "source" : "sources"}
                </p>
              </div>
              <h3 className="font-bold-iu mt-3 text-2xl leading-9 text-ink">{question}</h3>
            </div>

            <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_390px]">
              <div className="p-6 sm:p-8">
                <p className="font-mono-iu text-xs uppercase text-crimson">Answer</p>
                <div className="mt-5 space-y-5 text-[17px] leading-8 text-black/76">
                  {answerLines.map((line, index) => {
                    const numbered = /^\d{2}\s/.test(line);
                    const heading = /recommended kelley resources/i.test(line);
                    if (heading) {
                      return (
                        <h4 key={`${line}-${index}`} className="font-bold-iu border-t border-black/10 pt-6 text-xl text-ink">
                          Recommended Kelley Resources
                        </h4>
                      );
                    }
                    if (numbered) {
                      const number = line.slice(0, 2);
                      const text = line.slice(3);
                      return (
                        <div key={`${line}-${index}`} className="grid grid-cols-[42px_1fr] gap-4 border-l-4 border-crimson bg-limestone px-4 py-4">
                          <span className="font-mono-iu text-sm text-crimson">{number}</span>
                          <p className="font-bold-iu text-ink">{text}</p>
                        </div>
                      );
                    }
                    return (
                      <p key={`${line}-${index}`}>
                        {line}
                      </p>
                    );
                  })}
                </div>

                {result.recommended_resources.length > 0 && (
                  <div className="mt-8 border-t border-black/10 pt-6">
                    <p className="font-mono-iu text-xs uppercase text-crimson">Recommended Kelley Resources</p>
                    <div className="mt-4 grid gap-3 sm:grid-cols-3">
                      {result.recommended_resources.map((resource) => (
                        <a
                          key={resource.url}
                          href={resource.url}
                          target="_blank"
                          rel="noreferrer"
                          className="border border-black/10 bg-limestone p-4 transition hover:border-crimson"
                        >
                          <span className="font-bold-iu block text-ink">{resource.title}</span>
                          <span className="mt-2 block text-sm leading-5 text-black/62">{resource.description}</span>
                          <span className="font-bold-iu mt-3 inline-flex items-center gap-1 text-sm text-crimson">
                            Visit resource <ArrowRight className="h-3.5 w-3.5" />
                          </span>
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                {result.suggested_followups.length > 0 && (
                  <div className="mt-8 border-t border-black/10 pt-6">
                    <p className="font-mono-iu text-xs uppercase text-black/50">Suggested follow-up questions</p>
                    <div className="mt-4 grid gap-2 sm:grid-cols-3">
                      {result.suggested_followups.map((item) => (
                        <button
                          type="button"
                          key={item}
                          onClick={() => void askKelley(item)}
                          className="border border-black/10 bg-white px-3 py-3 text-left text-sm font-bold leading-5 text-ink transition hover:border-crimson hover:text-crimson"
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="border-t border-black/10 bg-limestone p-6 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-y-auto lg:border-l lg:border-t-0">
                <p className="font-mono-iu text-xs uppercase text-crimson">Sources Used</p>
                {result.sources.length === 0 ? (
                  <p className="mt-4 border border-black/10 bg-white p-4 text-sm font-semibold leading-6 text-black/60">
                    No source excerpts were strong enough to support an answer.
                  </p>
                ) : (
                  <>
                    <div className="mt-4 space-y-3">
                      {result.sources.map((source) => {
                        const open = source.id === openSourceId;
                        return (
                          <div key={source.id} className="border border-black/10 bg-white">
                            <button
                              type="button"
                              onClick={() => setOpenSourceId(open ? null : source.id)}
                              className="flex w-full items-start justify-between gap-3 p-4 text-left"
                            >
                              <span>
                                <span className="font-bold-iu block text-ink">{sourceDisplayName(source)}</span>
                                <span className="mt-1 block text-sm leading-5 text-black/55">
                                  {formatSectionName(source)}
                                  {source.page ? ` · p. ${source.page}` : ""}
                                </span>
                                <span className="font-mono-iu mt-2 block text-[11px] uppercase text-black/40">
                                  {source.source_type || "Kelley Document"}
                                </span>
                              </span>
                              {open ? <ChevronUp className="h-5 w-5 text-crimson" /> : <ChevronDown className="h-5 w-5 text-crimson" />}
                            </button>
                            {open && (
                              <div className="border-t border-black/10 p-4">
                                {source.url && (
                                  <a
                                    href={source.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="font-bold-iu mb-3 inline-flex items-center gap-1 text-sm text-crimson"
                                  >
                                    Open source <ExternalLink className="h-3.5 w-3.5" />
                                  </a>
                                )}
                                <p className="text-sm leading-6 text-black/68">{cleanExcerpt(source.excerpt)}</p>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}
              </div>
            </div>
          </article>
        )}
      </section>

      <footer className="border-t border-black/10 bg-ink px-5 py-6 text-center text-sm text-white/72">
        Kelley AI Prototype · Responses are generated from a limited demonstration knowledge base.
      </footer>
    </main>
  );
}
