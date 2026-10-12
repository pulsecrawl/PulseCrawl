"""Recipe loading and normalization, with no HTTP or workspace dependencies."""

import importlib
from typing import Any, Mapping
from .catalog import Case


def normalize(
    case: Case, fields: Mapping[str, str]
) -> tuple[list[dict[str, Any]], list[str]]:
    module = importlib.import_module(case.module)

    if case.key == "news/chihuahua":
        sources = module.build_recipes(fields)
        normalised = []
        for source in sources:
            templates = []
            for recipe in source["templates"]:
                templates.append(
                    {
                        "name": f"Chihuahua · {source['name']} · {recipe['key']}",
                        "engine": recipe["engine"],
                        "mappings": recipe["mappings"],
                        "hosts": recipe["scope"]["hosts"],
                        "urlPatterns": recipe["scope"]["url_patterns"],
                    }
                )
            normalised.append({**source, "templates": templates})
    elif hasattr(module, "build_publishers"):
        normalised = module.build_publishers(fields)
    elif hasattr(module, "build_retailers"):
        normalised = module.build_retailers(fields)
    elif hasattr(module, "build_suppliers"):
        normalised = module.build_suppliers(fields)
    elif hasattr(module, "build_sources"):
        normalised = module.build_sources(fields)
    else:
        raw = module.build_recipes(fields)
        normalised = []
        for source in raw:
            templates = []
            for template in source["templateStack"]:
                templates.append(
                    {
                        "name": template["name"],
                        "engine": template["engine"],
                        "mappings": template["mappings"],
                        "hosts": template["hosts"],
                        "urlPatterns": template["urlPatterns"],
                    }
                )
            normalised.append({**source, "templates": templates})

    seeds: list[str] = []
    for source in normalised:
        sample = source.get("sample_url") or source.get("sampleUrl")
        if sample and sample not in seeds:
            seeds.append(sample)
    for source in normalised:
        seed = source["seed"]
        if seed not in seeds:
            seeds.append(seed)
    return normalised, seeds
