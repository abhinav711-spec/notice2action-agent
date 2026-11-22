# Notice2Action Analysis Contract

Notice2Action does not send documents to a generative model and does not rely on a prompt to remember past notices. The extraction, evidence checks, profile comparison, action list, and version diff run in Python.

## Evidence-first extraction

- Read selectable text from each PDF page and retain one-based page numbers.
- Apply bounded local patterns to identify a small set of explicit dates, thresholds, fee statements, document names, and contact details.
- Never invent a date, amount, issuing authority, eligibility requirement, or missing source quote to fill a gap.
- Keep each extracted claim attached to the exact line used as its evidence.
- Compare profile values only when a matching threshold has a verified source quote.
- Treat patterns as a discovery aid: users must confirm the complete rule and exceptions in the original notice.

## Verification and trust boundaries

- Validate the PDF signature, byte limit, and page limit before analysis.
- Remove control and bidirectional override characters from extracted text.
- Flag common instruction-injection phrases for review; document text is never executable instructions.
- Verify every saved claim against its cited page. Failed claims are quarantined from Notice Watch and profile audits.
- Escape all extracted values before inserting them into HTML.
- Generate actions and calendar reminders only from discovered rules. Never substitute an invented date when a date cannot be parsed.

## Notice Watch contract

- Browser storage contains extracted structured notice data, source quotes, version labels, and saved times. It excludes PDFs and applicant profiles.
- The browser sends the two selected snapshots to `POST /api/watch/compare` for one stateless comparison. They are not written to server-side storage.
- The comparison includes only fields whose claim IDs were verified in the respective source version.
- Added, removed, and changed rules preserve before/after quote and page citations.
- Matching ignores whitespace and case but reports changed rule values; quote wording and page reflow alone do not create a change.
- History is local to one browser. It is not a website crawler, alert service, legal opinion, or official eligibility determination.
