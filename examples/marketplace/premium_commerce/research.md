# Source review and evidence boundaries

Reviewed October 11, 2026 (America/Los_Angeles). The retained audit completed
at `2026-10-12T04:00:22.030568+00:00`, which is October 11 locally.

This is a source-selection and policy review, **not live extraction evidence**.
The ten sources form a bounded example set reviewed through official storefront
product and policy pages. No provisioned services, transactions, credentials,
accounts, or private APIs were used.

## What was actually checked

- Official product URLs and their public host/path structures were located
  through primary storefront sources. Search/rendering availability does not
  establish access by the local Python HTTP client.
- An initial ten-origin connectivity check read only `robots.txt`. The retained
  second audit used this example's `audit.py` and the identifying user agent
  `PulseCrawlResearch/0.1 (+https://github.com/pulsecrawl/PulseCrawl)`.
- The retained audit made at most ten GET attempts, one per origin, no retries
  or redirects, with two-second spacing, ten-second timeouts, and 512 KiB caps.
  Its metadata, decoded-text hashes, and sample URLs are retained in
  `robots-audit-2026-10-11.json`; third-party bodies are not retained.
- There were **zero local-client product requests**. Known restrictions,
  unreadable robots, and unresolved policy scopes were not bypassed. Therefore
  the availability of JSON-LD, microdata, product metadata, prices, currency,
  and variants to the local non-browser client remains unvalidated on every
  live site. Live accuracy and repeated live price observations were not tested.
- `controlled-demo-summary.json` instead records a successful original-fixture
  demonstration through the real local runtime. It is separate from this audit
  and from any separate benchmark corpora or retained results.

## Selected official samples and policies

All entries remain **disabled-provisional**. A successful robots response or
conservative audit result is not an activation decision. The audit's wildcard
guard checks disallows from all groups and ignores allow exceptions, so it can
over-restrict the identifying user agent. Its negative result is not necessarily
a definitive user-agent-specific robots prohibition.

| Source | Official product structure/sample | Retained robots result | Policy/review boundary |
|---|---|---|---|
| lululemon | [`/p/{name}/{id}`](https://shop.lululemon.com/p/align-pant-2/i4goprzy85?color=77648&locale=en_US) | Timeout | [Terms of Use](https://shop.lululemon.com/help/legal/terms-of-use/) explicitly restrict automated access, scraping, and extraction. No permission exception was established. |
| Alo Yoga | [`/products/{handle}`](https://www.aloyoga.com/products/w5561r-high-waist-airlift-legging-black?variant=22032629170294) | HTTP 200; conservative sample check true | [Terms of Use](https://www.aloyoga.com/pages/terms-of-use) contain separate storefront and Wellness Club terms. The automated-tool restriction located in the latter must not be misrepresented as a verified universal storefront rule. Storefront collection authorization remains unresolved; no product was fetched. |
| Nordstrom | [`/s/{name}/{id}`](https://www.nordstrom.com/s/alo-airbrush-high-waist-leggings/5538850) | HTTP 200; conservative sample check true | [Terms & Conditions](https://www.nordstrom.com/browse/customer-service/policy/terms-conditions) explicitly restrict robots/scrapers and crawling. No permission exception was established. |
| REVOLVE | [`/{name}/dp/{code}/`](https://www.revolve.com/nike-air-footscape-woven-og-sneakers-in-black-white/dp/NIKR-MZ933/) | Timeout | [Terms of Use](https://www.revolve.com/r/infoTerms.jsp) restrict data-mining and extraction methods. No permission exception was established. |
| Nike | [`/t/{name}/{style-color}`](https://www.nike.com/t/air-force-1-07-ayakkab%C4%B1s%C4%B1-rWtqPn/CW2288-001) | HTTP 200; conservative all-group check false | The [official agreement-service reference](https://agreementservice.svs.nike.com/gb/en_gb/rest/agreement?agreementType=termsOfUse&uxId=com.nike&country=US&language=en&requestType=redirect) was inaccessible to the research reader. Terms/permission remain unresolved; the conservative robots result is not a definitive applicable-group decision. |
| Adidas | [`/us/{name}/{code}.html`](https://www.adidas.com/us/samba-og-shoes/B75806.html) | HTTP 403 | [US Terms & Conditions](https://www.adidas.com/us/help/us-company-information/what-are-the-terms-and-conditions) require express written permission for automated access. No such permission was established. |
| New Balance | [`/pd/{name}/{id}.html`](https://www.newbalance.com/pd/made-in-usa-990v6/M990NV6-D-11.html) | HTTP 403 | [Terms & Conditions](https://www.newbalance.com/terms.html) were located, but no collection authorization was established. Restrictions in separate loyalty-program terms are not treated as a universal storefront finding. The access denial was not bypassed. |
| On | [`/en-us/products/{model}/{audience}/{variant}`](https://www.on.com/en-us/products/cloudmonster-2-m-3mf3115/mens/ivory-steel-shoes-3MF31154571) | HTTP 200; conservative sample check true | [Terms and conditions](https://www.on.com/en-us/terms-and-conditions) were located. Absence of a located scraping clause is not a permission finding. Collection authorization and local product markup remain unresolved. |
| HOKA | [`/en/us/{category}/{name}/{id}.html`](https://www.hoka.com/en/us/mens-everyday-running-gear/clifton-11/1176572.html?dwvar_1176572_color=BKCS) | HTTP 200; conservative selected-query check false | [US terms](https://www.hoka.com/en/us/terms-and-conditions.html), Global Terms and Conditions of Use, restrict data mining and extraction tools. Robots also includes `/*dwvar` restrictions relevant to the selected color-query URL. Parameters were not removed to evade that restriction. |
| UGG | [`/{category}/{name}/{id}.html`](https://www.ugg.com/women-boots/classic-ultra-mini/1116109.html?dwvar_1116109_color=CRBO&dwvar_1116109_size=11) | HTTP 200; conservative selected-query check false | [US terms](https://www.ugg.com/terms-and-conditions.html), Global Terms and Conditions of Use, restrict data mining and extraction tools. Robots includes `/*dwvar` restrictions relevant to the selected color/size-query URL. Parameters were not removed to evade that restriction. |

The sample Nordstrom page can be sold out and other linked products can change
or disappear. These links document URL structures, not a guaranteed stock list.
The synthetic records intentionally do not reproduce the samples' real names,
prices, identifiers, sizes, colors, or availability.

## What is implemented versus provisional

Implemented and tested locally:

- Thirty declarative scoped entries; ten explicit source selections; one typed
  dataset/job; two ordinary Workspace executions with no HTTP transport.
- Original fixtures covering JSON-LD, `@graph`, metadata, semantic microdata,
  malformed JSON-LD fallback, and a distinct aggregate price-range case.
- Negative host/collection scope probes and an empty access-denial page check.
- Typed values, separate product/offer identifiers, optional variant context,
  nullable currency, append-all price history, pinned-version reads, and a
  deterministic retained result projection with twenty input hashes.

Not established:

- Permission to crawl any selected retailer, successful local product fetches,
  current live selector accuracy, all-variant coverage, checkout prices, or
  correct compare-at/regular-price extraction.
- Cross-retailer product equivalence, automatic variant matching, browser-only
  extraction, or anti-bot circumvention.
- Ten-site longitudinal price monitoring, a diverse 1,000-page extraction
  corpus, or 1,000/10,000-page end-to-end runtime performance measurements.

An authorized future integration needs explicit policy/permission resolution,
user-agent-specific robots review with correct wildcard handling, a bounded
current local-client product sample, independently checked field/variant
expectations, and negative/fallback validation before any activation. None of
those pending steps is presented as completed live validation.
