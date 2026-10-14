"""Scoped extraction recipes for the Chihuahua newspaper case study.

This module is intentionally side-effect free. It describes templates for a
local workspace, but never creates resources or starts a crawl. Compatible
fallback templates are supplied by the local provisioner and apply only after
every applicable authored template misses.

``build_recipes`` takes the six custom field IDs created by the example and
returns publication records.  Each template carries the final-URL scope to copy
into the local job's ``templates`` list through the shared provisioner.
"""

from __future__ import annotations

from typing import Any, Mapping


CUSTOM_FIELDS = (
    ("body", "string", "full article text"),
    ("section", "string", "site section / category"),
    ("tags", "string", "keywords, comma-joined"),
    ("city", "string", "newspaper's home city (scoped authored constant)"),
    ("source_name", "string", "newspaper name"),
    ("modified_at", "datetime", "last modification time"),
)

SYSTEM_FIELD_IDS = (
    "fld_sys_title",
    "fld_sys_url",
    "fld_sys_description",
    "fld_sys_author",
    "fld_sys_published_at",
    "fld_sys_image_url",
)

# ``sameDomainOnly`` is host-based.  Because OEM hosts many publications on
# one domain, keep its pending URLs inside the three selected publisher prefixes.
# The second expression admits all paths on the remaining newspaper hosts so
# their home/section pages can still lead to the article URL patterns below.
DISCOVERY_INCLUDE_PATTERNS = (
    r"^https?://(?:www\.)?oem\.com\.mx/"
    r"(?:elheraldodechihuahua|elheraldodejuarez|elsoldeparral)(?:/|$)",
    r"^https?://(?:www\.)?(?:"
    r"eldiariodechihuahua\.mx|diario\.mx|nortedigital\.mx|"
    r"laverdadjuarez\.com|raichali\.com|elpuntero\.com\.mx|"
    r"netnoticias\.mx|laopcion\.com\.mx|elpueblo\.com|tiempo\.com\.mx|"
    r"puentelibre\.mx|omnia\.com\.mx|segundoasegundo\.com|lapolaka\.com|"
    r"cronicadechihuahua\.com|yociudadano\.com\.mx|entrelineas\.com\.mx"
    r")(?:/|$)",
)

# One concrete article/indexed URL per publication. Local examples seed these
# before broader discovery so a prolific shared host (notably OEM) cannot fill
# the global page budget before every publication gets a template evaluation.
SAMPLE_URLS = {
    "El Heraldo de Chihuahua": "https://oem.com.mx/elheraldodechihuahua/local/repuntan-casos-de-gusano-barrenador-en-chihuahua-suman-12-nuevos-y-ya-son-172-en-el-estado-31681892",
    "El Heraldo de Juárez": "https://oem.com.mx/elheraldodejuarez/local/totalgas-es-reconocida-como-super-empresa-2026-31682563",
    "El Sol de Parral": "https://oem.com.mx/elsoldeparral/local/nace-cria-de-llama-en-el-zoologico-el-toluco-de-jimenez-preparan-intercambio-a-otros-centros-31683075",
    "El Diario de Chihuahua": "https://www.eldiariodechihuahua.mx/local/2026/jul/07/hay-que-preocuparse-pero-sobre-todo-ocuparse-por-el-futuro-de-chihuahua-jauregui-815139.html",
    "El Diario de Juárez": "https://diario.mx/estado/2026/mar/10/chihuahua-cuarta-ciudad-del-pais-en-recibir-copa-mundial-1108993.html",
    "Norte Digital": "https://nortedigital.mx/donmirone/imss-manda-a-lista-de-espera-a-pacientes-con-hepatitis-c-tratamiento-cuesta-300-mil-c-u/",
    "La Verdad Juárez": "https://laverdadjuarez.com/2026/08/21/reforma-electoral-en-chihuahua-es-un-retroceso-historico-promueven-30-juicios-para-eliminarla/",
    "Raíchali": "https://raichali.com/2026/08/21/promueven-juicios-contra-reforma-electoral-chihuahua/",
    "El Puntero": "https://elpuntero.com.mx/impulsa-chihuahua-formacion-de-jovenes-con-programa-mcu-x-pegatron/",
    "Net Noticias": "https://netnoticias.mx/nacional/se-deslinda-morena-del-regreso-de-rocha-moya-al-gobierno-de-sinaloa",
    "La Opción de Chihuahua": "https://laopcion.com.mx/local/dios-bendiga-a-mexico-maru-sobre-regreso-de-rocha-moya-20260821-525635.html",
    "El Pueblo": "https://elpueblo.com/local/registra-chihuahua-26-homicidios-en-julio-20260728-479673.html",
    "Tiempo": "https://www.tiempo.com.mx/nacional/audiencia-de-fernando-farias-sera-de-manera-virtual/",
    "Puente Libre": "https://puentelibre.mx/nacional/audiencia-de-fernando-farias-sera-de-manera-virtual/",
    "Omnia": "https://www.omnia.com.mx/noticia/439241/nayo-revilla-deportista-politico-maestro-y-chihuahuense-ejemplar",
    "Segundo a Segundo": "https://segundoasegundo.com/entrega-estado-incentivos-para-fortalecer-las-actividades-productivas-de-miembros-de-los-pueblos-indigenas/",
    "La Polaka": "https://www.lapolaka.com/index.php/categories/la-polaka/mexico/narcorebelion-contra-narcomorena",
    "Crónica de Chihuahua": "https://cronicadechihuahua.com/Nuevo-examen-a-la-Prepa-margina-a-los-vulnerables.html",
    "Yo Ciudadano": "https://yociudadano.com.mx/nota/tierra-nueva-una-comunidad-logro-pavimentar-sus-calles-tras-decadas-de-terraceria",
    "Entrelíneas": "https://entrelineas.com.mx/maru-campos-continua-su-ruta-chihuahua-con-visita-al-cerenam-de-creel-bocoyna/",
}


def _jsonld(
    fields: Mapping[str, str],
    *,
    body: bool = False,
    keywords: bool = True,
    section: bool = True,
) -> tuple[str, dict[str, Any]]:
    mappings: dict[str, Any] = {
        "fld_sys_title": "Article.headline",
        "fld_sys_url": "Article.url",
        "fld_sys_description": "Article.description",
        "fld_sys_author": "Article.author.name",
        "fld_sys_published_at": "Article.datePublished",
        "fld_sys_image_url": "Article.image",
        fields["modified_at"]: "Article.dateModified",
    }
    if body:
        mappings[fields["body"]] = "Article.articleBody"
    if section:
        mappings[fields["section"]] = "Article.articleSection"
    if keywords:
        mappings[fields["tags"]] = "Article.keywords"
    return "jsonld", mappings


def _meta(
    fields: Mapping[str, str],
    city: str,
    source_name: str,
    *,
    published: tuple[str, ...] = (),
    modified: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    section: tuple[str, ...] = (),
) -> tuple[str, dict[str, Any]]:
    # Literals are safe only because every caller attaches a URL scope.  The
    # meta engine also refuses to emit a literal-only record.
    return "meta", {
        "fld_sys_title": ["og:title", "<title>"],
        "fld_sys_url": ["og:url"],
        "fld_sys_description": ["og:description", "description"],
        "fld_sys_author": ["article:author", "author"],
        "fld_sys_published_at": [*published, "article:published_time"],
        "fld_sys_image_url": ["og:image"],
        fields["modified_at"]: [
            *modified,
            "article:modified_time",
            "og:updated_time",
        ],
        fields["tags"]: [*tags, "article:tag", "news_keywords", "keywords"],
        fields["section"]: [*section, "article:section"],
        fields["source_name"]: [f"literal:{source_name}"],
        fields["city"]: [f"literal:{city}"],
    }


def _css_body(fields: Mapping[str, str], selector: str) -> tuple[str, dict[str, Any]]:
    # Do not add an h1 mapping here.  A broad h1 would make a body template
    # claim section and home pages even when its body selector missed.
    return "css", {fields["body"]: [f"{selector} p::all"]}


def _scope(host: str, *url_patterns: str) -> dict[str, list[str]]:
    return {"hosts": [host], "url_patterns": list(url_patterns)}


def _templates(
    scope: Mapping[str, list[str]],
    specs: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    labels = {"jsonld": "ld", "meta": "meta", "css": "body"}
    return [
        {
            "key": labels[engine],
            "engine": engine,
            "mappings": mappings,
            "scope": dict(scope),
        }
        for engine, mappings in specs
    ]


def build_recipes(fields: Mapping[str, str]) -> list[dict[str, Any]]:
    """Return the 20 ordered, scoped publication recipes.

    ``scope.url_patterns`` are shell globs for normalized *final* URLs.  The
    leading ``*`` before most hosts covers both bare and ``www`` forms while
    the accompanying exact host guard prevents a cross-site match.
    """
    required = {name for name, _, _ in CUSTOM_FIELDS}
    missing = required.difference(fields)
    if missing:
        raise ValueError(f"missing custom field ids: {', '.join(sorted(missing))}")

    recipes: list[dict[str, Any]] = []

    def add(
        name: str,
        city: str,
        seed: str,
        scope: dict[str, list[str]],
        specs: list[tuple[str, dict[str, Any]]],
        *,
        robots: str = "allowed",
        confidence: str = "sampled-2026-08-21",
    ) -> None:
        recipes.append(
            {
                "name": name,
                "city": city,
                "seed": seed,
                "sample_url": SAMPLE_URLS[name],
                "robots": robots,
                "confidence": confidence,
                "templates": _templates(scope, specs),
            }
        )

    # Organización Editorial Mexicana now canonicalizes all three papers to
    # one host.  The publisher slug is therefore mandatory in every scope.
    for name, city, publisher in (
        ("El Heraldo de Chihuahua", "Chihuahua", "elheraldodechihuahua"),
        ("El Heraldo de Juárez", "Cd. Juárez", "elheraldodejuarez"),
        ("El Sol de Parral", "Parral", "elsoldeparral"),
    ):
        scoped = _scope(
            "oem.com.mx",
            f"https://oem.com.mx/{publisher}/*/*-[0-9]*",
        )
        add(
            name,
            city,
            f"https://oem.com.mx/{publisher}/",
            scoped,
            [_jsonld(fields), _meta(fields, city, name)],
        )

    # These three sites disallow the crawler's user agent.  The mappings are
    # retained from the earlier survey so resource authoring remains possible,
    # but executions must stay empty while robots.txt remains unchanged.
    add(
        "El Diario de Chihuahua",
        "Chihuahua",
        "https://eldiariodechihuahua.mx/",
        _scope(
            "eldiariodechihuahua.mx",
            "https://*eldiariodechihuahua.mx/*/20[0-9][0-9]/*/*/*.html",
        ),
        [
            _jsonld(fields, body=True, keywords=False),
            _meta(fields, "Chihuahua", "El Diario de Chihuahua"),
            _css_body(fields, "div.article-body"),
        ],
        robots="disallow-all",
        confidence="historical-unverified",
    )
    add(
        "El Diario de Juárez",
        "Cd. Juárez",
        "https://diario.mx/",
        _scope(
            "diario.mx",
            "https://*diario.mx/*/20[0-9][0-9]/*/*/*.html",
        ),
        [
            _jsonld(fields, body=True, keywords=False),
            _meta(fields, "Cd. Juárez", "El Diario de Juárez"),
            _css_body(fields, "div.article-body"),
        ],
        robots="disallow-all",
        confidence="historical-unverified",
    )

    add(
        "Norte Digital",
        "Cd. Juárez",
        "https://nortedigital.mx/",
        _scope(
            "nortedigital.mx",
            "https://*nortedigital.mx/*-*/",
            "https://*nortedigital.mx/*/*-*/",
        ),
        [
            _jsonld(fields),
            _meta(fields, "Cd. Juárez", "Norte Digital"),
            _css_body(fields, "div.entry-content"),
        ],
    )
    add(
        "La Verdad Juárez",
        "Cd. Juárez",
        "https://laverdadjuarez.com/",
        _scope("laverdadjuarez.com", "https://*laverdadjuarez.com/20[0-9][0-9]/*/*/*/"),
        [
            _jsonld(fields),
            _meta(fields, "Cd. Juárez", "La Verdad Juárez"),
            _css_body(fields, "[itemprop='articleBody']"),
        ],
    )
    add(
        "Raíchali",
        "Chihuahua",
        "https://raichali.com/",
        _scope("raichali.com", "https://*raichali.com/20[0-9][0-9]/*/*/*/"),
        [
            _jsonld(fields),
            _meta(fields, "Chihuahua", "Raíchali"),
            _css_body(fields, "div.td-post-content"),
        ],
    )
    add(
        "El Puntero",
        "Chihuahua",
        "https://elpuntero.com.mx/",
        _scope("elpuntero.com.mx", "https://*elpuntero.com.mx/*-*/"),
        [
            _jsonld(fields, section=False),
            _meta(fields, "Chihuahua", "El Puntero"),
            _css_body(fields, "div.td-post-content"),
        ],
    )
    add(
        "Net Noticias",
        "Cd. Juárez",
        "https://netnoticias.mx/",
        _scope("netnoticias.mx", "https://*netnoticias.mx/*/*-*"),
        [
            _jsonld(fields, keywords=False),
            _meta(fields, "Cd. Juárez", "Net Noticias"),
            _css_body(fields, "div.article-body"),
        ],
    )
    add(
        "La Opción de Chihuahua",
        "Chihuahua",
        "https://laopcion.com.mx/",
        _scope("laopcion.com.mx", "https://*laopcion.com.mx/*/*-[0-9]*-[0-9]*.html"),
        [
            _jsonld(fields, body=True, keywords=False),
            _meta(fields, "Chihuahua", "La Opción de Chihuahua"),
            _css_body(fields, "div.newsfull__body"),
        ],
    )
    add(
        "El Pueblo",
        "Chihuahua",
        "https://elpueblo.com/",
        _scope("elpueblo.com", "https://*elpueblo.com/*/*-[0-9]*-[0-9]*.html"),
        [
            _jsonld(fields, body=True, keywords=False),
            _meta(fields, "Chihuahua", "El Pueblo"),
            _css_body(fields, "article"),
        ],
        robots="disallow-all",
        confidence="historical-unverified",
    )

    date_meta = {
        "published": ("og:article:published_time", "date", "DC.date.issued"),
    }
    add(
        "Tiempo",
        "Chihuahua",
        "https://tiempo.com.mx/",
        _scope("tiempo.com.mx", "https://*tiempo.com.mx/*/*-*/"),
        [
            _meta(fields, "Chihuahua", "Tiempo", **date_meta),
            _css_body(fields, "article#article-post"),
        ],
    )
    add(
        "Puente Libre",
        "Cd. Juárez",
        "https://puentelibre.mx/",
        _scope("puentelibre.mx", "https://*puentelibre.mx/*/*-*/"),
        [
            _meta(fields, "Cd. Juárez", "Puente Libre", **date_meta),
            _css_body(fields, "article#article-post"),
        ],
    )
    add(
        "Omnia",
        "Chihuahua",
        "https://omnia.com.mx/",
        _scope("omnia.com.mx", "https://*omnia.com.mx/noticia/[0-9]*/*"),
        [
            _meta(fields, "Chihuahua", "Omnia"),
            _css_body(fields, "div.articulo"),
        ],
        robots="robots-missing",
    )
    add(
        "Segundo a Segundo",
        "Chihuahua",
        "https://segundoasegundo.com/",
        _scope("segundoasegundo.com", "https://*segundoasegundo.com/*-*/"),
        [
            _meta(fields, "Chihuahua", "Segundo a Segundo"),
            _css_body(fields, "div.mvp-post-add-body"),
        ],
    )
    add(
        "La Polaka",
        "Cd. Juárez",
        "https://lapolaka.com/",
        _scope("lapolaka.com", "https://*lapolaka.com/index.php/categories/*/*/*"),
        [
            _meta(fields, "Cd. Juárez", "La Polaka"),
            _css_body(fields, "[itemprop='articleBody']"),
        ],
    )
    add(
        "Crónica de Chihuahua",
        "Chihuahua",
        "https://cronicadechihuahua.com/",
        _scope("cronicadechihuahua.com", "https://*cronicadechihuahua.com/*.html"),
        [
            _meta(fields, "Chihuahua", "Crónica de Chihuahua"),
            _css_body(fields, "div.col7.articulo.print"),
        ],
    )
    add(
        "Yo Ciudadano",
        "Cd. Juárez",
        "https://yociudadano.com.mx/",
        _scope("yociudadano.com.mx", "https://*yociudadano.com.mx/nota/*"),
        [
            _meta(fields, "Cd. Juárez", "Yo Ciudadano"),
            _css_body(fields, "div.art-body"),
        ],
    )
    add(
        "Entrelíneas",
        "Chihuahua",
        "https://entrelineas.com.mx/",
        _scope("entrelineas.com.mx", "https://*entrelineas.com.mx/*-*/"),
        [
            _jsonld(fields),
            _meta(fields, "Chihuahua", "Entrelíneas"),
            _css_body(fields, "[data-widget_type='theme-post-content.default']"),
        ],
    )
    return recipes


def stack_entry(template_id: str, template: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one registered recipe template to the Python SDK input shape."""
    scope = template["scope"]
    return {
        "template_id": template_id,
        "hosts": list(scope["hosts"]),
        "url_patterns": list(scope["url_patterns"]),
    }
