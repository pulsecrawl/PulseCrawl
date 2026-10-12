"""Scoped extraction recipes for 20 technology-company career sites.

The companies use three hosted applicant-tracking systems.  A recipe is kept
per company even when the mappings are shared because the URL scope (and, for
fallback mappings, the company literal) is company-specific.

``build_recipes`` accepts the field-name -> field-id mapping returned while
authoring a schema.  Omitting it leaves semantic field names in place, which
makes this module convenient for the offline validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


CUSTOM_FIELDS = (
    ("job_id", "string", "employer or ATS job identifier"),
    ("title", "string", "job title"),
    ("url", "url", "canonical job URL"),
    ("summary", "string", "short social/search description"),
    ("description", "string", "plain-text job description"),
    ("description_html", "string", "structured-data description markup"),
    ("company", "string", "hiring organization"),
    ("location", "string", "primary locality or advertised location"),
    ("region", "string", "primary state, province, or region"),
    ("country", "string", "primary country"),
    ("remote_region", "string", "remote applicant location restriction"),
    ("employment_type", "string", "full-time, contract, internship, etc."),
    ("workplace_type", "string", "remote, hybrid, or on-site"),
    ("department", "string", "team or department"),
    ("posted_at", "datetime", "posting publication date"),
    ("valid_through", "datetime", "application deadline when published"),
    ("salary_text", "string", "human-readable compensation block"),
    ("salary_currency", "string", "ISO-like salary currency"),
    ("salary_min", "number", "minimum base salary"),
    ("salary_max", "number", "maximum base salary"),
    ("salary_unit", "string", "salary unit such as YEAR"),
    ("image_url", "url", "social preview or employer image"),
)


@dataclass(frozen=True)
class Source:
    slug: str
    company: str
    platform: str
    seed: str
    hosts: tuple[str, ...]
    url_patterns: tuple[str, ...]
    sample_url: str


SOURCES = (
    # Ashby: rich JobPosting JSON-LD, scoped by tenant path on one host.
    Source(
        "notion",
        "Notion",
        "ashby",
        "https://jobs.ashbyhq.com/notion",
        ("jobs.ashbyhq.com",),
        ("https://jobs.ashbyhq.com/notion/**",),
        "https://jobs.ashbyhq.com/notion/6597b600-7781-46e6-b70a-a9af4fb2b61b",
    ),
    Source(
        "openai",
        "OpenAI",
        "ashby",
        "https://jobs.ashbyhq.com/openai",
        ("jobs.ashbyhq.com",),
        ("https://jobs.ashbyhq.com/openai/**",),
        "https://jobs.ashbyhq.com/openai/9bfc3ebf-c154-4037-8fef-900d3a49ec89",
    ),
    Source(
        "ashby",
        "Ashby",
        "ashby",
        "https://jobs.ashbyhq.com/ashby",
        ("jobs.ashbyhq.com",),
        ("https://jobs.ashbyhq.com/ashby/**",),
        "https://jobs.ashbyhq.com/ashby/0f5dbf59-687b-4d88-88a7-73ee0a66b48d",
    ),
    Source(
        "ramp",
        "Ramp",
        "ashby",
        "https://jobs.ashbyhq.com/ramp",
        ("jobs.ashbyhq.com",),
        ("https://jobs.ashbyhq.com/ramp/**",),
        "https://jobs.ashbyhq.com/ramp/be496b52-cfbf-494e-b862-61fb4a188b24",
    ),
    Source(
        "linear",
        "Linear",
        "ashby",
        "https://jobs.ashbyhq.com/linear",
        ("jobs.ashbyhq.com",),
        ("https://jobs.ashbyhq.com/linear/**",),
        "https://jobs.ashbyhq.com/linear/2ef60eea-7cff-45c2-abf2-eaedc4ea89bd",
    ),
    # Lever: JSON-LD plus stable, server-rendered posting classes.
    Source(
        "palantir",
        "Palantir",
        "lever",
        "https://jobs.lever.co/palantir",
        ("jobs.lever.co",),
        ("https://jobs.lever.co/palantir/**",),
        "https://jobs.lever.co/palantir/ac978161-6f46-4f6b-ad9e-a258e642751c",
    ),
    Source(
        "spotify",
        "Spotify",
        "lever",
        "https://jobs.lever.co/spotify",
        ("jobs.lever.co",),
        ("https://jobs.lever.co/spotify/**",),
        "https://jobs.lever.co/spotify/890b2c0f-f46f-4a4b-bb73-3a6af6e0edd5",
    ),
    Source(
        "zoox",
        "Zoox",
        "lever",
        "https://jobs.lever.co/zoox",
        ("jobs.lever.co",),
        ("https://jobs.lever.co/zoox/**",),
        "https://jobs.lever.co/zoox/f4746da4-8eb8-43e2-b7ce-bf3c7cf9640d",
    ),
    Source(
        "osmind",
        "Osmind",
        "lever",
        "https://jobs.lever.co/Osmind",
        ("jobs.lever.co",),
        ("https://jobs.lever.co/Osmind/**",),
        "https://jobs.lever.co/Osmind/c2db6fec-bf06-48c0-acc9-77a08fce5745",
    ),
    Source(
        "luxury-presence",
        "Luxury Presence",
        "lever",
        "https://jobs.lever.co/luxurypresence",
        ("jobs.lever.co",),
        ("https://jobs.lever.co/luxurypresence/**",),
        "https://jobs.lever.co/luxurypresence/00069055-e828-4369-8916-ac5673e58e3f",
    ),
    # Greenhouse: the final redirected host is job-boards.greenhouse.io.
    Source(
        "canonical",
        "Canonical",
        "greenhouse",
        "https://job-boards.greenhouse.io/canonical",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/canonical/jobs/**",),
        "https://job-boards.greenhouse.io/canonical/jobs/5569916",
    ),
    Source(
        "algolia",
        "Algolia",
        "greenhouse",
        "https://job-boards.greenhouse.io/algolia",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/algolia/jobs/**",),
        "https://job-boards.greenhouse.io/algolia/jobs/6141481004",
    ),
    Source(
        "tubi",
        "Tubi",
        "greenhouse",
        "https://job-boards.greenhouse.io/tubitv",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/tubitv/jobs/**",),
        "https://job-boards.greenhouse.io/tubitv/jobs/8128273",
    ),
    # Stripe uses Greenhouse underneath, but renders a rich JobPosting on its
    # own final host rather than the hosted Greenhouse DOM.
    Source(
        "stripe",
        "Stripe",
        "direct-jsonld",
        "https://stripe.com/jobs/search",
        ("stripe.com",),
        ("https://stripe.com/careers/listing/**",),
        "https://stripe.com/careers/listing/account-executive-ai-startups-hunter/8130725",
    ),
    Source(
        "anduril",
        "Anduril",
        "greenhouse",
        "https://job-boards.greenhouse.io/andurilindustries",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/andurilindustries/jobs/**",),
        "https://job-boards.greenhouse.io/andurilindustries/jobs/4802172007",
    ),
    Source(
        "reddit",
        "Reddit",
        "greenhouse",
        "https://job-boards.greenhouse.io/reddit",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/reddit/jobs/**",),
        "https://job-boards.greenhouse.io/reddit/jobs/7617155",
    ),
    Source(
        "figma",
        "Figma",
        "greenhouse",
        "https://job-boards.greenhouse.io/figma",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/figma/jobs/**",),
        "https://job-boards.greenhouse.io/figma/jobs/5364702004",
    ),
    Source(
        "cloudflare",
        "Cloudflare",
        "greenhouse",
        "https://job-boards.greenhouse.io/cloudflare",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/cloudflare/jobs/**",),
        "https://job-boards.greenhouse.io/cloudflare/jobs/7695702",
    ),
    Source(
        "gitlab",
        "GitLab",
        "greenhouse",
        "https://job-boards.greenhouse.io/gitlab",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/gitlab/jobs/**",),
        "https://job-boards.greenhouse.io/gitlab/jobs/8503792002",
    ),
    Source(
        "discord",
        "Discord",
        "greenhouse",
        "https://job-boards.greenhouse.io/discord",
        ("job-boards.greenhouse.io",),
        ("https://job-boards.greenhouse.io/discord/jobs/**",),
        "https://job-boards.greenhouse.io/discord/jobs/8599937002",
    ),
)


def _ids(field_ids: Mapping[str, str] | None) -> dict[str, str]:
    names = [name for name, _type, _description in CUSTOM_FIELDS]
    resolved = {name: name for name in names}
    if field_ids:
        missing = set(names).difference(field_ids)
        if missing:
            raise ValueError(f"missing job-search field ids: {sorted(missing)}")
        resolved.update(field_ids)
    return resolved


def _jsonld(F: Mapping[str, str]) -> dict[str, object]:
    return {
        "engine": "jsonld",
        "mappings": {
            F["job_id"]: "JobPosting.identifier.value",
            F["title"]: "JobPosting.title",
            F["description_html"]: "JobPosting.description",
            F["company"]: "JobPosting.hiringOrganization.name",
            F["location"]: "JobPosting.jobLocation.address.addressLocality",
            F["region"]: "JobPosting.jobLocation.address.addressRegion",
            F["country"]: "JobPosting.jobLocation.address.addressCountry",
            F["remote_region"]: "JobPosting.applicantLocationRequirements.name",
            F["employment_type"]: "JobPosting.employmentType",
            F["workplace_type"]: "JobPosting.jobLocationType",
            F["posted_at"]: "JobPosting.datePosted",
            F["valid_through"]: "JobPosting.validThrough",
            F["salary_currency"]: "JobPosting.baseSalary.currency",
            F["salary_min"]: "JobPosting.baseSalary.value.minValue",
            F["salary_max"]: "JobPosting.baseSalary.value.maxValue",
            F["salary_unit"]: "JobPosting.baseSalary.value.unitText",
        },
    }


def _meta(F: Mapping[str, str], company: str) -> dict[str, object]:
    return {
        "engine": "meta",
        "mappings": {
            F["title"]: ("og:title", "twitter:title", "<title>"),
            F["url"]: ("og:url",),
            F["summary"]: ("og:description", "twitter:description", "description"),
            F["image_url"]: ("og:image", "twitter:image"),
            # Safe only because every stack entry carrying this template is scoped.
            F["company"]: (f"literal:{company}",),
        },
    }


def _lever_css(F: Mapping[str, str], company: str) -> dict[str, object]:
    return {
        "engine": "css",
        "mappings": {
            F["title"]: (".posting-headline h2",),
            F["description"]: (
                ".posting-page .content > .section-wrapper.page-full-width:last-of-type",
            ),
            F["company"]: (f"literal:{company}",),
            F["location"]: (".posting-categories .location",),
            F["department"]: (".posting-categories .department",),
            F["employment_type"]: (".posting-categories .commitment",),
            F["workplace_type"]: (".posting-categories .workplaceTypes",),
        },
    }


def _greenhouse_css(F: Mapping[str, str], company: str) -> dict[str, object]:
    return {
        "engine": "css",
        "mappings": {
            F["title"]: (".job__title h1",),
            F["description"]: (".job__description",),
            F["company"]: (f"literal:{company}",),
            F["location"]: (".job__location",),
            F["salary_text"]: (".job__pay-ranges",),
        },
    }


def build_recipes(
    field_ids: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Return one seed and an ordered, URL-scoped template stack per company."""
    F = _ids(field_ids)
    recipes: list[dict[str, object]] = []
    for source in SOURCES:
        if source.platform in {"ashby", "direct-jsonld"}:
            templates = (_jsonld(F), _meta(F, source.company))
        elif source.platform == "lever":
            # CSS wins with clean text; JSON-LD fills dates and organization data.
            templates = (
                _lever_css(F, source.company),
                _jsonld(F),
                _meta(F, source.company),
            )
        else:
            # Current Greenhouse pages have no JobPosting JSON-LD.
            templates = (_greenhouse_css(F, source.company), _meta(F, source.company))

        stack = []
        for index, template in enumerate(templates, start=1):
            stack.append(
                {
                    "name": f"jobsearch: {source.company} · {index}-{template['engine']}",
                    "engine": template["engine"],
                    "mappings": template["mappings"],
                    "hosts": list(source.hosts),
                    "urlPatterns": list(source.url_patterns),
                }
            )
        recipes.append(
            {
                "slug": source.slug,
                "company": source.company,
                "platform": source.platform,
                "seed": source.seed,
                "sampleUrl": source.sample_url,
                "templateStack": stack,
            }
        )
    return recipes
