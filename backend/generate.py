"""ACL-safe answer generation (mode 5b): Vertex Gemini over the trimmed docs only.

Used when ANSWER_MODE=gemini. Grounds strictly on documents the user is allowed to see
(unless web search is explicitly enabled — see below).

Knobs:
- model:      flash by default (fast/cheap); a caller-chosen model from the server allowlist
              (config.answer_models). On context overflow we fail over to the larger pro
              model (config.GEMINI_PRO_MODEL); a bad attachment falls back to text-only.
- thinking:   "high"/"low"/budget int/"" — Q&A paths use high for better answers.
- use_search: attach Gemini's Google Search grounding tool (opt-in; ADDS public web context
              for research — never exposes ACL'd docs, only augments with public info).
"""
from google import genai
from google.genai import types

import config
import core

_client = None

# substrings that indicate the request was too large for the model's context window
_OVERFLOW = ("token", "context", "exceeds", "too large", "payload size",
             "resource_exhausted", "maximum")


def _c():
    global _client
    if _client is None:
        loc = config.LOCATION if config.LOCATION != "global" else "global"
        _client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=loc)
    return _client


def _thinking_config(thinking):
    """Best-effort ThinkingConfig across SDK/model variants: prefer Gemini-3 thinking_level
    ("high"/"low"), fall back to a budget int. Returns None if unsupported (degrade, never
    break)."""
    if not thinking:
        return None
    val = str(thinking)
    if val.lstrip("-").isdigit():
        try:
            return types.ThinkingConfig(thinking_budget=int(val))
        except Exception:
            return None
    try:
        return types.ThinkingConfig(thinking_level=val)          # Gemini 3
    except Exception:
        budget = {"high": 24576, "low": 512}.get(val, 0)         # older SDK: map to a budget
        try:
            return types.ThinkingConfig(thinking_budget=budget) if budget else None
        except Exception:
            return None


def _gen_config(thinking, use_search):
    kwargs = {}
    tc = _thinking_config(thinking)
    if tc is not None:
        kwargs["thinking_config"] = tc
    if use_search:
        try:
            kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        except Exception:
            pass
    if not kwargs:
        return None
    try:
        return types.GenerateContentConfig(**kwargs)
    except Exception:
        return None


def _run(model, parts, thinking=None, use_search=False):
    cfg = _gen_config(thinking, use_search)
    resp = _c().models.generate_content(model=model, contents=parts, config=cfg)
    return (resp.text or "").strip()


def _too_large(e):
    s = str(e).lower()
    return any(k in s for k in _OVERFLOW)


def _generate(text_part, attach_parts, primary=None, thinking=None, use_search=False):
    """Run generation with failover: chosen/flash model → (on overflow) pro → text-only.
    Returns {text, model, search} — `model` is the one that ACTUALLY ran (for logging),
    `search` whether web grounding was in the winning call. `primary` is the caller-selected
    model id (validated upstream); None → default flash (multimodal flash with attachments)."""
    primary = primary or (config.MULTIMODAL_MODEL if (config.MULTIMODAL_ANSWERS and attach_parts)
                          else config.GEMINI_MODEL)
    pro = config.GEMINI_PRO_MODEL
    full = [text_part] + attach_parts
    try:
        return {"text": _run(primary, full, thinking, use_search), "model": primary, "search": use_search}
    except Exception as e:
        # 1) too big for the chosen model → escalate to the larger pro model (keep docs)
        if pro and pro != primary and _too_large(e):
            try:
                return {"text": _run(pro, full, thinking, use_search), "model": pro, "search": use_search}
            except Exception:
                pass
        # 2) likely a bad attachment → retry text-only on the chosen model
        if attach_parts:
            try:
                return {"text": _run(primary, [text_part], thinking, use_search),
                        "model": primary, "search": use_search}
            except Exception:
                pass
        # 3) last resort → text-only, no thinking/tools (in case the config itself failed)
        try:
            return {"text": _run(primary, [text_part]), "model": primary, "search": False}
        except Exception:
            if pro and pro != primary:
                return {"text": _run(pro, [text_part]), "model": pro, "search": False}
            raise


def answer(query, docs, model=None, thinking=None, use_search=False):
    """Returns {text, model, search}."""
    if not docs and not use_search:
        return {"text": "No documents you have access to matched this query.",
                "model": "", "search": False}
    text = types.Part.from_text(text=core.build_prompt(query, docs))
    attach = []
    if config.MULTIMODAL_ANSWERS:
        attach = [types.Part.from_uri(file_uri=u, mime_type="application/pdf")
                  for u in core.pdf_uris(docs, config.MULTIMODAL_MAX_DOCS)]
    return _generate(text, attach, model, thinking, use_search)


def answer_about_doc(question, title, gcs_uri="", context_text="", model=None,
                     thinking=None, use_search=False):
    """Single-document Q&A / summarize, grounded on ONE doc. Returns {text, model, search}."""
    text = types.Part.from_text(text=core.build_doc_prompt(question, title, context_text))
    attach = []
    if config.MULTIMODAL_ANSWERS and gcs_uri and gcs_uri.lower().endswith(".pdf"):
        attach = [types.Part.from_uri(file_uri=gcs_uri, mime_type="application/pdf")]
    return _generate(text, attach, model, thinking, use_search)
