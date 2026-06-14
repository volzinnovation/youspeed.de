# ACM SIGSPATIAL 2026 Draft Constraints

Target: ACM SIGSPATIAL 2026 Research Track, Experiment, Benchmark & Experience paper.

Official sources:
- Research CFP: https://sigspatial2026.sigspatial.org/research-submission.html
- ACM proceedings template: https://www.acm.org/publications/proceedings-template
- ACM LaTeX guidance: https://authors.acm.org/proceedings/production-information/preparing-your-article-with-latex

Submission dates:
- Abstract submission: Friday, May 22, 2026, 11:59 PM Pacific Time.
- Paper submission: Friday, May 29, 2026, 11:59 PM Pacific Time.
- Notification: Wednesday, August 5, 2026, 11:59 PM Pacific Time.
- Camera-ready: Wednesday, August 19, 2026, 11:59 PM Pacific Time.
- Conference: November 3-6, 2026, Riverside, California, USA.

Format constraints:
- Use ACM Conference Proceedings Primary Article template.
- LaTeX class should use the `sigconf` format: `\documentclass[sigconf]{acmart}`.
- Manuscript must be submitted as PDF.
- Regular Research and Experiment/Benchmark/Experience papers: up to 10 pages, excluding references.
- Up to 2 additional pages after references may be used for appendices.
- Experiment/Benchmark/Experience paper titles must contain the suffix `[Experiment]` at submission time; the suffix is removed for camera-ready if accepted.
- SIGSPATIAL 2026 is single-blind: author names and affiliations should be listed.
- Accepted full papers appear in the ACM Digital Library proceedings.

Strategic implications for this paper:
- Position as an Experiment/Benchmark/Experience paper, not a new algorithm paper.
- Make the contribution geospatial-systems-facing: spatial packaging, mobile spatial lookup, route replay, and deployment lessons.
- Avoid unsupported ISA safety or crash-reduction claims.
- Explicitly distinguish hindsight pseudo-label replay from manually verified ground truth.
- Address the ITSC rejection by making route-level replay and system tradeoffs central, while tracking fixed-probe architecture latency as a remaining pre-submission gap.
