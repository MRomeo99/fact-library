# Page Importance Scoring Specification

## Overview

Not all pages on a local business website are equally valuable for fact extraction.
The pricing page contains pricing facts. The blog contains mostly marketing content.
The privacy policy contains no business facts at all.

The Page Importance Scoring Model assigns each URL a score from 0 (skip entirely) to 5
(highest priority). The pipeline crawls pages in descending score order and skips score-0 pages.

This is the core IP of the Client Fact Library.

---

## Base Score by Page Type

Scores are assigned by matching URL path patterns. Longer/more specific patterns win
over shorter ones.

| Page Type         | Score | URL Patterns                                     |
|-------------------|-------|--------------------------------------------------|
| Service / product | 5     | `/services/`, `/treatments/`, `/solutions/`      |
| Homepage          | 4     | `/`, `/index`                                    |
| About / team      | 4     | `/about`, `/team`, `/our-story`                  |
| Pricing           | 4     | `/pricing`, `/packages`, `/rates`                |
| Locations         | 3     | `/locations`, `/service-area`, city names in URL |
| FAQ               | 3     | `/faq`, `/help`, `/questions`                    |
| Blog / articles   | 2     | `/blog`, `/news`, date-in-URL pattern (`/2024/`) |
| Testimonials      | 2     | `/reviews`, `/testimonials`                      |
| Contact           | 1     | `/contact`, `/get-in-touch`                      |
| Legal / privacy   | 0     | `/privacy`, `/terms`, `/legal` — SKIP ENTIRELY   |

**Note on blog detection:** Any URL containing a date pattern (`/YYYY-MM` or `/YYYY/MM`)
is classified as a blog/article page and scores 2.

**Note on score-0 pages:** Legal and privacy pages are never crawled. They contain no
business facts and would dilute the extraction results.

---

## Scoring Modifiers (additive, total capped at 5)

Modifiers are computed from the page's HTML content and link graph, then added to the
base score. The total is capped at 5.

| Signal                            | Modifier | Detection Method                          |
|-----------------------------------|----------|-------------------------------------------|
| JSON-LD structured data present   | +1.0     | `<script type="application/ld+json">` tag |
| Word count > 300                  | +0.5     | Count whitespace-separated tokens in text |
| H2/H3 count > 3                   | +0.5     | Count `<h2>` and `<h3>` tags              |
| Internal inbound link count > 5   | +0.5     | Count internal links pointing to this URL |
| Contains price signals ($, "fee") | +0.5     | Regex: `\$[\d,]+` or `\bfee\b`            |

### Modifier rationale

- **JSON-LD (+1):** Pages with structured data are the most reliably information-rich pages.
  Local businesses typically add JSON-LD to their homepage, service pages, and about pages.
  This is the strongest single signal.
- **Word count (+0.5):** Short pages (< 300 words) are typically navigation pages,
  confirmation pages, or thin content. Long pages contain more extractable facts.
- **Headings (+0.5):** Pages with 4+ H2/H3 headings are well-structured content pages,
  likely to contain multiple distinct facts. Navigation-heavy pages have few headings.
- **Inbound links (+0.5):** Pages that many other internal pages link to are considered
  important by the site itself. This reflects the site's implicit authority structure.
- **Price signals (+0.5):** Pages containing dollar amounts or the word "fee" are directly
  relevant to pricing fact extraction — the most commercially valuable fact type.

---

## Score Cap

The total score (base + all modifiers) is capped at 5. A services page (base=5) with all
modifiers applied would naively score 7.5. The cap ensures scores remain interpretable
on the 0–5 scale.

---

## Configuration and Overrides

The scoring model is configurable per-client via a YAML file in `config/scorers/`.

```yaml
# config/scorers/dental_practice.yml
page_type_overrides:
  - pattern: "/treatments/"
    score: 5
  - pattern: "/new-patients/"
    score: 4
  - pattern: "/dental-blog/"
    score: 1  # lower priority than default blog score
top_x_pages: 15
```

### Industry-specific examples

**Dental practice:**
- `/treatments/` → 5 (most important page type for a dental site)
- `/new-patients/` → 4 (high-value for identity and operational facts)

**Law firm:**
- `/practice-areas/` → 5 (equivalent to `/services/` for law firms)
- `/results/` or `/case-results/` → 3 (credibility facts, moderate priority)

**Home services:**
- `/service-area/` → 4 (location facts are critical for home services)
- `/services/` → 5 (default, applies)

### `top_x_pages` config

After scoring all discovered URLs, the pipeline crawls only the top-X pages by score.
This controls crawl depth per client. Default: 10. Recommended range: 10–30.

---

## Implementation Reference

The scoring logic lives in `crawler/page_scorer.py`:

```python
scorer = PageScorer(config=client_yaml_config)
score = scorer.score_page(url_path, html_content, inbound_link_count)
```

`score_page()` returns a float in [0, 5]. The pipeline filters `score > 0` before crawling.
