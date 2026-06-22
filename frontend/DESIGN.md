# Frontend design — derived from the Amgen mockups (slides 4 & 5)

The UI replicates the look & feel of Amgen's "Intelligent Search" mockups, **modernized**
with Tailwind and anchored on **Amgen's official brand** (so it sits well with the Amgen
logo). Slide text was OCR'd and mapped to components below.

## Brand (adopted from Amgen's own portal sample)
- Primary **Amgen blue** `#0063C3`, deep blue `#0056B3`, **teal** `#15909C`, **green** `#92BE43`.
- Font **Open Sans**. Logo + favicon are Amgen's real assets in `public/`.
- Tokens live in `tailwind.config.js` (`amgen.*`). The original mockup used an indigo/lime
  palette; we shifted to Amgen brand for cohesion with the logo.

## Considered: Jesus Chavez's `science-search-portal` frontend
Reviewed it as a starting point. It's a **chat-style** app with ~3.4k lines of bespoke CSS,
MSAL auth — a different layout from these mockups and not Tailwind. **Decision: build fresh
in Tailwind to match the mockups, but reuse his Amgen brand assets + colors + library
choices** (`react-markdown`, `remark-gfm`, `lucide-react`).

## Slide 5 → Hero landing (`HeroLanding.tsx`)
| OCR | Implementation |
|---|---|
| "Intelligent / Search" wordmark | `Logo.tsx` `<Wordmark>` + Amgen logo lockup |
| green ticker "…the smarter it becomes (Roadmap)" | header pill (Amgen green) |
| user button + dropdown | `PersonaSwitcher.tsx` (switches demo user → `X-Demo-User`) |
| green hexagon emblem (magnifier + lightbulb) | `HexEmblem.tsx` (SVG, teal→green) |
| "Find, Explore and Discover" | hero headline |
| "Over 6M documents from 14 sources." (6M green) | hero subtitle (numbers in green) |
| hero search bar ("Amgen holidays") | elevated pill input + suggestion chips |
| left floating icon dock (search/list/people/graph) | `SideDock.tsx` |
| bottom chevron | animated `floaty` chevron |

## Slide 4 → Results view (`App.tsx` + components)
| OCR | Implementation |
|---|---|
| blue header + embedded search ("What is cell therapy?", X, magnifier) | `Header.tsx` |
| lime "Service Restoration Notice" banner + Expand/X | `NoticeBanner.tsx` (Amgen green, dismissible) |
| tabs "All Sources / Custom / Functional Apps", "+ Custom Group", "Filter(s)" | folded into `FilterBar.tsx` |
| source pills MyAmgen·CDOCS·SharePoint·ServiceNow·Amgen RIM | **replaced** by *dynamic* facet chips from real VAIS metadata (company / source / type / area / year), ACL-aware |
| "Top Search Results" + "Export" (download) | results header + Export button |
| "Processing query…" spinner + skeleton bars | `AnswerCard.tsx` loading state (`skeleton` shimmer) |
| Document card: badge, breadcrumb, blue title, 👍👎🚩, snippet, "Read More…" | `ResultCard.tsx` |
| right-edge vertical "Feedback" tab | `FeedbackTab.tsx` |

## Data-driven, not hard-coded
The mockup's static source pills (MyAmgen, CDOCS, …) are **aspirational**. v1 renders
**real, dynamic filters** from `availableFilters` (VAIS metadata tallied over the user's
ACL-trimmed results — see PLAN §4.4), so chips reflect exactly what each persona can see.
Result cards link back to the original `sourceUrl` (and the stored GCS copy). Export,
feedback thumbs, source-tabs, and the side dock are visual affordances in v1.
