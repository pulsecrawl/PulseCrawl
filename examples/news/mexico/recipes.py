"""Mexico-wide news recipes for the URL-scoped template-stack example.

This module is deliberately data-only.  It does not create hosted resources or
start crawls, which makes the surveyed mappings usable by the eventual example
without coupling the research to an API contract that is still being built.

``build_publishers`` turns symbolic custom-field names into real field IDs.
``build_stack_entries`` then turns created template names into the proposed
Python SDK ``template_stack`` payload.  System templates are intentionally not
listed: the worker should append compatible system templates automatically
after every authored stack entry has failed to produce values.
"""

from __future__ import annotations

from typing import Any, Mapping


CUSTOM_FIELDS = (
    ("body", "string", "full article or video transcript text"),
    ("section", "string", "publisher section or category"),
    ("tags", "string", "keywords, comma-joined"),
    ("source_name", "string", "publisher name"),
    ("modified_at", "datetime", "last modification time"),
)

SYSTEM_FIELDS = (
    "fld_sys_title",
    "fld_sys_url",
    "fld_sys_description",
    "fld_sys_author",
    "fld_sys_published_at",
    "fld_sys_image_url",
)

SCHEMA_NAME = "mexico news article deep v1"
DATASET_NAME = "mexico-news-deep"
SCOPE = {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6}


def article_jsonld(
    field_ids: Mapping[str, str], *, body_paths: tuple[str, ...] = ()
) -> dict[str, Any]:
    """A deep schema.org Article mapping, including all observed subtypes."""
    mappings: dict[str, Any] = {
        "fld_sys_title": ["Article.headline", "Article.name"],
        "fld_sys_url": [
            "Article.url",
            "Article.mainEntityOfPage.@id",
            "Article.mainEntityOfPage",
        ],
        "fld_sys_description": "Article.description",
        "fld_sys_author": ["Article.author.name", "Article.author"],
        "fld_sys_published_at": "Article.datePublished",
        "fld_sys_image_url": ["Article.image.url", "Article.image"],
        field_ids["modified_at"]: "Article.dateModified",
        field_ids["section"]: "Article.articleSection",
        field_ids["tags"]: "Article.keywords",
    }
    if body_paths:
        mappings[field_ids["body"]] = list(body_paths)
    return {"engine": "jsonld", "mappings": mappings}


def video_jsonld(field_ids: Mapping[str, str]) -> dict[str, Any]:
    """N+ publishes transcript-led news pages as VideoObject, not Article."""
    return {
        "engine": "jsonld",
        "mappings": {
            "fld_sys_title": "VideoObject.name",
            "fld_sys_url": [
                "VideoObject.url",
                "VideoObject.mainEntityOfPage.@id",
                "VideoObject.mainEntityOfPage",
            ],
            "fld_sys_description": "VideoObject.description",
            "fld_sys_author": ["VideoObject.author.name", "VideoObject.author"],
            "fld_sys_published_at": "VideoObject.uploadDate",
            "fld_sys_image_url": "VideoObject.thumbnailUrl",
            field_ids["body"]: "VideoObject.transcript",
        },
    }


def article_meta(field_ids: Mapping[str, str], publisher: str) -> dict[str, Any]:
    """OpenGraph/article metadata observed across the surveyed publishers."""
    return {
        "engine": "meta",
        "mappings": {
            "fld_sys_title": ["og:title", "twitter:title", "<title>"],
            "fld_sys_url": ["og:url"],
            "fld_sys_description": [
                "og:description",
                "description",
                "twitter:description",
            ],
            "fld_sys_author": ["article:author", "author", "parsely-author"],
            "fld_sys_published_at": [
                "article:published_time",
                "parsely-pub-date",
                "date",
            ],
            "fld_sys_image_url": ["og:image", "twitter:image"],
            field_ids["modified_at"]: ["article:modified_time", "og:updated_time"],
            field_ids["section"]: ["article:section", "parsely-section"],
            field_ids["tags"]: [
                "article:tag",
                "news_keywords",
                "keywords",
                "parsely-tags",
            ],
            # This literal is safe only because every generated stack entry is
            # host/path scoped.  It also exercises the literal-leak regression.
            field_ids["source_name"]: ["og:site_name", f"literal:{publisher}"],
        },
    }


def css_body(field_ids: Mapping[str, str], selector: str) -> dict[str, Any]:
    """Body-only CSS mapping; it cannot create a title-only listing record."""
    return {
        "engine": "css",
        "mappings": {field_ids["body"]: [f"{selector} p::all"]},
    }


# Survey metadata. ``authored=False`` means the site remains a seed but receives
# no org template yet, intentionally exercising automatic system fallback and
# the execution's needs-template diagnostics.
PUBLISHER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "el_universal",
        "name": "El Universal",
        "seed": "https://www.eluniversal.com.mx/nacion/",
        "hosts": ["eluniversal.com.mx"],
        "url_patterns": [
            "/nacion/*/",
            "/mundo/*/",
            "/estados/*/",
            "/economia/*/",
            "/metropoli/*/",
            "/cultura/*/",
            "/ciencia-y-salud/*/",
        ],
        "sample_url": "https://www.eluniversal.com.mx/nacion/sheinbaum-rechaza-acusaciones-contra-gobernadora-marina-del-pilar-no-hay-ninguna-informacion-asegura/",
        "jsonld_body": (),
        "body_selector": ".story-content .body",
    },
    {
        "key": "milenio",
        "name": "Milenio",
        "seed": "https://www.milenio.com/politica",
        "hosts": ["milenio.com"],
        "url_patterns": [
            "/politica/*",
            "/negocios/*",
            "/estados/*",
            "/internacional/*",
            "/cultura/*",
            "/ciencia-y-salud/*",
        ],
        "sample_url": "https://www.milenio.com/politica/morena-perfila-desafuero-alito-perfila-presidente-seccion-instructora",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".nd-content-body",
    },
    {
        "key": "excelsior",
        "name": "Excelsior",
        "seed": "https://www.excelsior.com.mx/nacional",
        "hosts": ["excelsior.com.mx"],
        "url_patterns": [
            "/nacional/*",
            "/global/*",
            "/dinero/*",
            "/comunidad/*",
            "/expresiones/*",
            "/hacker/*",
        ],
        "sample_url": "https://www.excelsior.com.mx/nacional/sheinbaum-ve-relevante-detencion-fausto-corrales-para-aclarar-traslado-mayo-eu",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".c-detail__body",
    },
    {
        "key": "la_jornada",
        "name": "La Jornada",
        "seed": "https://www.jornada.com.mx/ultimas",
        "hosts": ["jornada.com.mx"],
        "url_patterns": ["/noticia/20??/??/??/*/*"],
        "sample_url": "https://www.jornada.com.mx/noticia/2026/06/24/politica/historicamente-el-pan-ha-buscado-subordinarse-a-eu-dice-sheinbaum-desconoce-si-maru-campos-fue-reclutada-por-la-cia",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".content_nitf",
    },
    {
        "key": "el_financiero",
        "name": "El Financiero",
        "seed": "https://www.elfinanciero.com.mx/nacional/",
        "hosts": ["elfinanciero.com.mx"],
        "url_patterns": [
            "/nacional/20??/??/??/*/",
            "/economia/20??/??/??/*/",
            "/empresas/20??/??/??/*/",
            "/mundo/20??/??/??/*/",
        ],
        "sample_url": "https://www.elfinanciero.com.mx/nacional/2026/06/01/alcanza-sheinbaum-aprobacion-de-69-en-mayo-encuesta-ef/",
        "jsonld_body": (),
        "body_selector": ".b-article-body",
    },
    {
        "key": "el_economista",
        "name": "El Economista",
        "seed": "https://www.eleconomista.com.mx/politica",
        "hosts": ["eleconomista.com.mx"],
        "url_patterns": [
            "/politica/*.html",
            "/empresas/*.html",
            "/economia/*.html",
            "/mercados/*.html",
        ],
        "sample_url": "https://www.eleconomista.com.mx/politica/sep-ajusta-horarios-frio-extremo-regreso-clases-2026-estados-cambios-20260112-794872.html",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".c-detail__body",
    },
    {
        "key": "proceso",
        "name": "Proceso",
        "seed": "https://www.proceso.com.mx/nacional/",
        "hosts": ["proceso.com.mx"],
        "url_patterns": [
            "/nacional/20??/??/??/*.html",
            "/internacional/20??/??/??/*.html",
        ],
        "sample_url": "https://www.proceso.com.mx/nacional/2026/8/21/mas-de-5-mil-fosas-clandestinas-fueron-localizadas-en-mexico-en-tres-sexenios-378455.html",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".article-body",
    },
    {
        "key": "grupo_animal",
        "name": "Grupo Animal / Animal Politico",
        "seed": "https://grupoanimal.mx/noticias",
        "hosts": ["grupoanimal.mx", "animalpolitico.com"],
        "url_patterns": ["/noticias/*"],
        "sample_url": "https://grupoanimal.mx/noticias/aranceles-autos-chinos-mexico-impuestos-industria",
        "jsonld": False,
        "body_selector": "#ssr-article",
    },
    {
        "key": "aristegui_noticias",
        "name": "Aristegui Noticias",
        "seed": "https://aristeguinoticias.com/category/mexico/",
        "hosts": ["aristeguinoticias.com"],
        "url_patterns": ["/????/mexico/*/"],
        "sample_url": "https://aristeguinoticias.com/2008/mexico/congreso-aprueba-renuncia-de-monica-soto-al-tepjf-entre-criticas-por-falta-de-una-causa-grave/",
        "jsonld_body": (),
        "body_selector": ".nota-txt",
    },
    {
        "key": "sdp_noticias",
        "name": "SDP Noticias",
        "seed": "https://www.sdpnoticias.com/mexico/",
        "hosts": ["sdpnoticias.com"],
        "url_patterns": [
            "/mexico/*/",
            "/estados/*/*/",
            "/negocios/*/",
            "/internacional/*/",
        ],
        "sample_url": "https://www.sdpnoticias.com/mexico/claudia-sheinbaum-se-reune-con-zoe-robledo-con-cubrebocas-tras-reportar-fuerte-gripe/",
        "jsonld_body": (),
        "body_selector": ".b-article-body",
    },
    {
        "key": "uno_tv",
        "name": "Uno TV",
        "seed": "https://www.unotv.com/nacional/",
        "hosts": ["unotv.com"],
        "url_patterns": [
            "/nacional/*/",
            "/estados/*/*/",
            "/internacional/*/",
            "/negocios/*/",
        ],
        "sample_url": "https://www.unotv.com/nacional/155-personas-desaparecidas-en-una-semana-adolescentes-y-jovenes-los-mas-afectados/",
        "jsonld_body": (),
        "body_selector": ".box_container .txt",
    },
    {
        "key": "nmas",
        "name": "N+",
        "seed": "https://www.nmas.com.mx/temas/nacional/",
        "hosts": ["nmas.com.mx"],
        "url_patterns": [
            "/seguridad/*/",
            "/politica/*/",
            "/sociedad/*/",
            "/economia/*/",
            "/internacional/*/",
            "/estados/*/",
            "/cdmx/*/",
        ],
        "sample_url": "https://www.nmas.com.mx/seguridad/se-incrementan-golpes-ciberneticos-contra-satelites-hubo-7-ataques-en-mexico-en-el-ultimo-ano/",
        "jsonld_kind": "video",
        "body_selector": ".lexical-content",
    },
    {
        "key": "publimetro",
        "name": "Publimetro Mexico",
        "seed": "https://www.publimetro.com.mx/noticias/",
        "hosts": ["publimetro.com.mx"],
        "url_patterns": ["/noticias/20??/??/??/*/"],
        "sample_url": "https://www.publimetro.com.mx/noticias/2026/08/21/claudia-sheinbaum-suspende-actividades-por-fuerte-enfermedad-cual-es-su-estado-de-salud/",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".b-article-body",
    },
    {
        "key": "forbes_mexico",
        "name": "Forbes Mexico",
        "seed": "https://forbes.com.mx/actualidad/",
        "hosts": ["forbes.com.mx"],
        "url_patterns": ["/*/"],
        "sample_url": "https://forbes.com.mx/aranceles-de-trump-y-sheinbaum-tiran-4-9-las-importaciones-y-exportaciones-de-autos-por-los-puertos-mexicanos/",
        "jsonld_body": (),
        "body_selector": ".entry-content",
    },
    {
        "key": "expansion",
        "name": "Expansion",
        "seed": "https://expansion.mx/economia",
        "hosts": ["expansion.mx"],
        "url_patterns": [
            "/economia/20??/??/??/*",
            "/empresas/20??/??/??/*",
            "/tecnologia/20??/??/??/*",
            "/mundo/20??/??/??/*",
        ],
        "sample_url": "https://expansion.mx/economia/2026/08/21/mexico-busca-convertir-la-innovacion-en-patentes-y-riqueza",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".BlocksArticleBody-items",
    },
    {
        "key": "eje_central",
        "name": "Eje Central",
        "seed": "https://www.ejecentral.com.mx/nuestroeje",
        "hosts": ["ejecentral.com.mx"],
        "url_patterns": ["/nuestro-eje/*", "/internacional/*", "/economia/*"],
        "sample_url": "https://www.ejecentral.com.mx/nuestro-eje/sheinbaum-y-mara-lezama-revisan-estrategia-contra-el-sargazo-en-quintana-roo",
        # The sampled JSON-LD uses the nonstandard lowercase `articlebody`.
        "jsonld_body": ("Article.articleBody", "Article.articlebody"),
        "body_selector": ".RichTextEjeCentralArticleBody",
    },
    {
        "key": "la_razon",
        "name": "La Razon de Mexico",
        "seed": "https://www.razon.com.mx/mexico/",
        "hosts": ["razon.com.mx"],
        "url_patterns": [
            "/mexico/20??/??/??/*/",
            "/negocios/20??/??/??/*/",
            "/mundo/20??/??/??/*/",
        ],
        "sample_url": "https://www.razon.com.mx/mexico/2026/08/21/huachicol-fiscal-exhibe-debilidades-estructurales-energeticas-especialista/",
        "jsonld_body": ("Article.articleBody",),
        "body_selector": ".layout-article__article__body",
    },
    {
        "key": "el_sol_de_mexico",
        "name": "El Sol de Mexico",
        "seed": "https://oem.com.mx/elsoldemexico/mexico/",
        "hosts": ["oem.com.mx"],
        "url_patterns": ["/elsoldemexico/*/*-[0-9]*"],
        "sample_url": "https://oem.com.mx/elsoldemexico/mexico/oposicion-critica-regreso-de-rocha-moya-al-gobierno-de-sinaloa-acusa-pacto-de-impunidad-31679821",
        "jsonld_body": (),
        # The raw response has metadata but the article body is client-loaded.
        "body_selector": None,
    },
    {
        "key": "24_horas",
        "name": "24 Horas",
        "seed": "https://24-horas.mx/mexico/",
        "hosts": ["24-horas.mx"],
        "url_patterns": ["/mexico/*/"],
        "sample_url": None,
        "authored": False,
        "research_status": "cloudflare_challenge",
    },
    {
        "key": "sin_embargo",
        "name": "SinEmbargo",
        "seed": "https://www.sinembargo.mx/",
        "hosts": ["sinembargo.mx"],
        "url_patterns": ["/*"],
        "sample_url": None,
        "authored": False,
        "research_status": "access_denied",
    },
)


def build_publishers(field_ids: Mapping[str, str]) -> list[dict[str, Any]]:
    """Build concrete templates plus URL scopes for all surveyed publishers."""
    required = {name for name, _type, _description in CUSTOM_FIELDS}
    missing = sorted(required.difference(field_ids))
    if missing:
        raise ValueError(f"missing custom field IDs: {', '.join(missing)}")

    publishers: list[dict[str, Any]] = []
    for spec in PUBLISHER_SPECS:
        publisher = dict(spec)
        templates: list[dict[str, Any]] = []
        if spec.get("authored", True):
            if spec.get("jsonld", True):
                if spec.get("jsonld_kind") == "video":
                    recipe = video_jsonld(field_ids)
                    label = "video-jsonld"
                else:
                    recipe = article_jsonld(
                        field_ids, body_paths=spec.get("jsonld_body", ())
                    )
                    label = "article-jsonld"
                templates.append({"name": f"tmpl: {spec['name']} · {label}", **recipe})
            templates.append(
                {
                    "name": f"tmpl: {spec['name']} · article-meta",
                    **article_meta(field_ids, spec["name"]),
                }
            )
            if spec.get("body_selector"):
                templates.append(
                    {
                        "name": f"tmpl: {spec['name']} · body-css",
                        **css_body(field_ids, spec["body_selector"]),
                    }
                )
        publisher["templates"] = templates
        publishers.append(publisher)
    return publishers


def build_stack_entries(
    publishers: list[dict[str, Any]],
    template_ids_by_name: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Build the proposed ordered SDK stack from templates created by name."""
    entries: list[dict[str, Any]] = []
    for publisher in publishers:
        for template in publisher["templates"]:
            entries.append(
                {
                    "template_id": template_ids_by_name[template["name"]],
                    "hosts": list(publisher["hosts"]),
                    "url_patterns": list(publisher["url_patterns"]),
                }
            )
    return entries


def seeds() -> list[str]:
    """All seeds, including fallback-only sites whose authored mappings are pending."""
    return [spec["seed"] for spec in PUBLISHER_SPECS]
