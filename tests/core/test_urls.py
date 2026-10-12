from pulsecrawl.core.urls import (
    extract_links,
    host_of,
    in_scope,
    matching_url_pattern_specificity,
    normalize_url,
    same_site,
    template_scope_matches,
    url_hash,
)


class TestNormalizeUrl:
    def test_absolutizes_against_base(self):
        assert normalize_url("/about", base="https://x.example/page") == "https://x.example/about"

    def test_strips_fragments(self):
        assert normalize_url("https://x.example/a#section") == "https://x.example/a"

    def test_lowercases_host_keeps_path_case(self):
        assert normalize_url("https://X.Example/PaTh") == "https://x.example/PaTh"

    def test_strips_default_ports(self):
        assert normalize_url("https://x.example:443/a") == "https://x.example/a"
        assert normalize_url("http://x.example:80/a") == "http://x.example/a"
        assert normalize_url("https://x.example:8443/a") == "https://x.example:8443/a"

    def test_empty_path_becomes_slash(self):
        assert normalize_url("https://x.example") == "https://x.example/"

    def test_keeps_query(self):
        assert normalize_url("https://x.example/a?b=1") == "https://x.example/a?b=1"

    def test_rejects_non_http(self):
        assert normalize_url("mailto:a@b.c") is None
        assert normalize_url("javascript:void(0)") is None
        assert normalize_url("tel:+123") is None
        assert normalize_url("#anchor") is None
        assert normalize_url("ftp://x.example/f") is None
        assert normalize_url("not a url") is None
        assert normalize_url("") is None


class TestHelpers:
    def test_url_hash_is_stable_sha256(self):
        assert url_hash("https://x.example/") == url_hash("https://x.example/")
        assert len(url_hash("https://x.example/")) == 64

    def test_host_of(self):
        assert host_of("https://Shop.Example/p") == "shop.example"

    def test_same_site_treats_www_as_same(self):
        assert same_site("https://www.x.example/a", "x.example")
        assert same_site("https://x.example/a", "www.x.example")
        assert not same_site("https://other.example/a", "x.example")


class TestInScope:
    HOSTS = frozenset({"x.example"})

    def scoped(self, url, **kw):
        defaults = dict(
            seed_hosts=self.HOSTS,
            same_domain_only=True,
            include_patterns=(),
            exclude_patterns=(),
        )
        defaults.update(kw)
        return in_scope(url, **defaults)

    def test_same_domain_enforced(self):
        assert self.scoped("https://x.example/a")
        assert not self.scoped("https://other.example/a")
        assert self.scoped("https://other.example/a", same_domain_only=False)

    def test_exclude_wins_over_include(self):
        assert not self.scoped(
            "https://x.example/private/a",
            include_patterns=(r"/",),
            exclude_patterns=(r"/private/",),
        )

    def test_include_requires_match(self):
        assert self.scoped("https://x.example/products/1", include_patterns=(r"/products/",))
        assert not self.scoped("https://x.example/blog/1", include_patterns=(r"/products/",))


class TestTemplateScope:
    def test_exact_www_wildcard_and_path_globs(self):
        assert template_scope_matches(
            "https://www.x.example/news/a",
            hosts=("x.example",),
            url_patterns=("/news/*",),
        )
        assert template_scope_matches(
            "https://sub.x.example/jobs/1",
            hosts=("*.x.example",),
            url_patterns=("https://sub.x.example/jobs/*",),
        )
        assert not template_scope_matches(
            "https://other.example/news/a",
            hosts=("x.example",),
            url_patterns=("/news/*",),
        )

    def test_matching_pattern_specificity_uses_the_strongest_match(self):
        assert matching_url_pattern_specificity(
            "https://x.example/news/local/story",
            ("/news/*", "/news/local/*", "/jobs/*"),
        ) == len("/news/local/")


class TestExtractLinks:
    def test_extracts_normalized_unique_links_in_order(self):
        html = """
        <a href="/a">A</a>
        <a href="https://x.example/b#frag">B</a>
        <a href="/a">dup</a>
        <a href="mailto:hi@x.example">mail</a>
        <a href="javascript:void(0)">js</a>
        <a>none</a>
        """
        assert extract_links(html, "https://x.example/") == [
            "https://x.example/a",
            "https://x.example/b",
        ]
