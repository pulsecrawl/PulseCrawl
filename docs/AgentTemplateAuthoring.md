# Agent-assisted template authoring

PulseCrawl exposes a model-vendor-neutral authoring lifecycle. A person, a
script, or an external agent may inspect representative pages and propose a
template draft. PulseCrawl itself does not call a model. Scheduled extraction
continues to use deterministic CSS, JSON-LD, and metadata mappings.

## Lifecycle

1. Create a normal job with seeds, scope, robots policy, rate limits, and URL
   budgets.
2. Call `workspace.authoring.sample(...)` with a smaller explicit page budget.
   This creates an ordinary execution intent and uses the same durable
   frontier, robots service, organization-origin gate, redirect admission,
   response limits, and lifetime budget as every other local crawl.
   Sampling retains pages but publishes no records or URL-ledger observations.
   Its real HTTP attempts still count against the source job's lifetime budget,
   so use a dedicated authoring job when production and authoring budgets must
   be separated.
3. Inspect the retained pages with `workspace.authoring.inspect(page)`.
4. Let a person or external agent propose one or more scoped mappings with
   `create_draft(...)`.
5. Validate the draft against positive and negative pages. The report includes
   field coverage, fallback and unmatched pages, scope-containment signals,
   ambiguity, multi-entity results, and field-level provenance.
6. Explicitly approve the latest passing validation.
7. Promote the approved draft. Promotion creates immutable catalog templates
   and a stack payload, but it never edits an active job.

```python
from pulsecrawl import RepresentativePage, Workspace

with Workspace("./my-crawls") as pc:
    sample = pc.authoring.sample(
        "job_news",
        max_pages=20,
        max_depth=2,
    )
    inspections = [pc.authoring.inspect(page) for page in sample["pages"]]

    # Send only the inspection material you have approved to any external
    # agent. The framework does not select or call that agent.
    proposed_entries = external_agent_proposes_templates(inspections)
    draft = pc.authoring.create_draft(
        "Publisher article",
        output_schema_id="schema_article",
        templates=proposed_entries,
        source_job_id="job_news",
    )

    positives = [
        RepresentativePage(
            url="https://publisher.example/articles/known-story",
            body=saved_positive_html,
            role="positive",
        )
    ]
    negatives = [
        RepresentativePage(
            url="https://publisher.example/about",
            body=saved_negative_html,
            role="negative",
        )
    ]
    report = pc.authoring.validate(draft.draft_id, positives + negatives)
    if report["passed"]:
        approved = pc.authoring.approve(
            draft.draft_id,
            validation_id=report["validationId"],
            approved_by="user@example.org",
        )
        promoted = pc.authoring.promote(approved.draft_id)
        print(promoted["templateStack"])
```

The undefined `external_agent_proposes_templates` function is intentionally
outside PulseCrawl. It can be an interactive user, a local model, or ordinary
code.

Inspection redacts metadata values and selector text samples by default. A
caller may set `include_content_samples=True` only after making an explicit
privacy decision. JSON-LD entity counts, traversal, and property paths are
bounded to prevent adversarial documents from creating unbounded inspection
work.

## Public Python API

| Method | Behavior |
|---|---|
| `authoring.sample(job_id, max_pages=, max_depth=)` | Governed, downward-bounded representative crawl |
| `authoring.load_execution_pages(execution_id)` | Load retained pages from a completed execution |
| `authoring.inspect(page)` | Report final URL, JSON-LD paths, metadata, selector candidates, repeated structures, and response provenance |
| `authoring.create_draft(...)` | Save a versioned, inactive draft |
| `authoring.validate(...)` | Run deterministic positive, negative, contamination, coverage, fallback, ambiguity, and provenance checks |
| `authoring.approve(..., validation_id=, approved_by=)` | Record the actor explicitly approving the latest passing validation |
| `authoring.promote(...)` | Create catalog templates without editing jobs |
| `authoring.diagnose_drift(...)` | Compare active-template behavior on baseline and current saved pages |
| `authoring.repair_draft(...)` | Copy an active template into a new inactive repair draft |

The standalone `inspect_page` and `validate_template_stack` functions support
tools that do not use a persistent workspace. They never make network calls.
Approval requires at least one positive page, at least one negative page, no
required-field or type-coercion failure, and no truncated validation page.
Any authored or system-fallback match on a negative page fails validation.
Callers can choose the required field IDs; workspace validation defaults to the
declared schema fields.
Positive pages may also provide `expectedRecords`. Each expected field/value
subset must match one extracted and type-coerced record, and every emitted
record must be accounted for when an oracle is present. Without these oracles,
validation proves applicability, coverage, containment, and type compatibility,
but it does not prove that a selector chose the semantically correct text.

## Security and privacy boundary

Webpage HTML, visible text, metadata, JSON-LD, links, and attributes are
untrusted input. Text such as "ignore your rules" is page data, not an
instruction. An external agent must not receive credentials, cookies, environment variables, or unrestricted network tools.
It must not expand hosts, increase budgets, disable robots handling, approve a
draft, or promote a template because a page asks it to do so.

Persisted drafts require `source_job_id`. PulseCrawl injects the job's seed
hosts into unscoped entries and rejects declared hosts outside that set, with
`www.` treated as the same site. Wildcards are rejected because they expand
beyond the explicit seed hosts. Offline tools that do not
have a job may use the standalone inspection and validation functions, but
they cannot enter the approval or promotion lifecycle.
The local `approved_by` value is durable workflow provenance, not an
authentication boundary. Filesystem access controls determine who may operate
a local workspace.

Sampling is the only authoring method that reaches the network, and it does so
through a normal PulseCrawl job. `inspect`, `validate`, drift diagnostics, and
repair operate only on supplied or retained bytes.

Sending HTML or inspection output off the local machine is a data-egress
decision. Review page content for personal, confidential, copyrighted, or
contract-restricted material before transmission. Prefer local models or
redacted structural inspection when the data policy does not permit egress.

## Suggested evaluation metrics

Measure authoring time, number of revisions, positive-page precision and
recall, negative-page false positives, cross-scope match signals, required
field coverage, system-fallback rate, unmatched rate, ambiguous or multi-entity
pages, human corrections, model token cost, and survival after controlled
markup drift. Keep the model name, version, prompt, representative-page sample,
and final deterministic artifacts with the experiment so the result can be
reproduced.
