---
name: literature-search
description: Search, verify, and present academic literature for reviews, author publication lists, topic searches, and citation checking. Use whenever the user asks to find papers, literature, references, author publications, journal quartiles, DOI links, Google Scholar/SerpApi searches, or a literature review.
---

# Literature Search

## Workflow

1. Clarify the topic, date range, document types, and the requested ranking system only when it materially changes the result. Otherwise search directly.
2. Use legitimate metadata sources. Prefer SerpApi's Google Scholar results when `SERPAPI_KEY` is available; otherwise use Crossref, PubMed, publisher pages, institutional repositories, and web search.
3. Do not scrape Google Scholar directly or open pages that trigger human verification. Do not use the in-app browser for publisher pages merely to verify metadata; use a publisher's indexed metadata, DOI, Crossref, PubMed, or other public source instead.
4. For author searches, disambiguate same-name authors using affiliation, email, subject area, coauthors, ORCID, and institutional profile. State uncertainty rather than merging identities.
5. Prefer DOI links, then publisher landing pages, then trusted repository records. Do not claim a full text is accessible unless verified.

## SerpApi budget

- Treat one SerpApi HTTP request as one search. A request for more than ten Scholar results may use multiple pages and therefore multiple searches.
- When the local SerpApi tool and its usage file are available, enforce a calendar-month cap of 240 requests. Count a request before sending it and report the remaining quota after a search.
- Never store or print `SERPAPI_KEY`; read it only from the environment.

## Required chat format

Present each journal article exactly in this order:

`年份｜期刊名称（JCR Qx；或“分区待核”）｜论文标题`

Put the source URL in its own `text` code block immediately below the entry, so the user can use the code-block copy control. Do not rely on Markdown title links, because the user prefers copyable links and their app may open links in an unstable internal browser.

Example:

2026｜*Sensors and Actuators B: Chemical*（JCR Q1）｜Plasticized PVC/CNT flexible electrodes for highly responsive, stable, and durable soft actuators and wearable sensors

```text
https://doi.org/10.1016/j.snb.2025.138894
```

## Quality rules

- Say whether “分区” means JCR or CAS when the user specifies it. If unspecified, label the system used; do not present a current quartile as the historical quartile at publication.
- Mark conference papers as `会议／EI` rather than inventing a journal quartile.
- Separate directly relevant papers from tangential results and avoid duplicate records, preprints, and corrected versions unless requested.
- Include author, year, journal, DOI or persistent URL when available. Keep explanations brief unless the user requests a synthesis.
- In chat, present the useful result first. Save a local table or bibliography only when asked or when it materially helps the task.
