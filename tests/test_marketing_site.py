from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


SITE_ROOT = Path(__file__).resolve().parents[1] / "marketing-site"
DIST_ROOT = SITE_ROOT / "dist"


class SiteDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms = 0
        self.links: list[str] = []
        self.assets: list[str] = []
        self.title_parts: list[str] = []
        self._inside_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self.forms += 1
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"] or "")
        if tag in {"img", "script"} and attributes.get("src"):
            self.assets.append(attributes["src"] or "")
        if tag == "link" and attributes.get("href"):
            self.assets.append(attributes["href"] or "")
        if tag == "title":
            self._inside_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self.title_parts).strip()


def parse_document(path: Path) -> SiteDocumentParser:
    parser = SiteDocumentParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def local_path(reference: str) -> Path | None:
    parsed = urlparse(reference)
    if parsed.scheme or parsed.netloc or reference.startswith(("#", "mailto:")):
        return None
    relative = parsed.path.lstrip("/") or "index.html"
    return DIST_ROOT / relative


def test_hosting_manifest_targets_static_output() -> None:
    manifest = (SITE_ROOT / ".openai" / "hosting.json").read_text(encoding="utf-8")
    assert '"project_id": "appgprj_6af2b6c101e481918255e4a6b7882845"' in manifest
    assert '"directory": "dist"' in manifest
    assert (DIST_ROOT / "index.html").is_file()


def test_internal_links_and_assets_resolve() -> None:
    missing: list[str] = []
    for document in DIST_ROOT.glob("*.html"):
        parser = parse_document(document)
        for reference in parser.links + parser.assets:
            target = local_path(reference)
            if target is not None and not target.is_file():
                missing.append(f"{document.name}: {reference}")
    assert not missing, "Missing marketing site files:\n" + "\n".join(missing)


def test_homepage_has_product_and_legal_paths_without_collection_forms() -> None:
    homepage = parse_document(DIST_ROOT / "index.html")
    assert homepage.title == "InternTrack — Turn applications into next actions"
    assert "https://github.com/jhyan-beep/interntrack" in homepage.links
    assert "/privacy.html" in homepage.links
    assert "/terms.html" in homepage.links
    assert homepage.forms == 0

