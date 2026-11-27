"""The contact sheet: a static HTML gallery for a run's evidence.

One self-sufficient HTML file per run, generated with the stdlib only —
no template engine, no external assets. By default the file is written
into the run directory and references evidence by relative path (images
load from disk, videos play); ``embed=True`` inlines media as data URIs
for a single shareable file at the cost of size.

Supplying an evaluation overlays scores: an overall badge, per-scenario
badges, and each criterion's verdict linked to the evidence items it
cited.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from darkroom.evaluation import Evaluation, coerce_evaluation, loads_evaluation
from darkroom.manifest import load_manifest
from darkroom.model import EvidenceItem, RunManifest
from darkroom.render import default_registry

# The mark, inlined rather than linked. A gallery is one self-contained
# file an operator opens from a run directory, often with no network and
# sometimes after the run has been moved; a logo fetched from anywhere is
# a broken image in exactly those conditions. The gradient ids are
# namespaced so they cannot collide with anything this page grows later.
_MARK = """<svg class="mark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 760" role="img"
  aria-label="darkroom">
  <defs>
    <linearGradient id="dr-beam" gradientUnits="userSpaceOnUse" x1="410" y1="552" x2="868"
      y2="676">
      <stop offset="0" stop-color="#FF2D2D"/>
      <stop offset=".42" stop-color="#FF2D2D" stop-opacity=".5"/>
      <stop offset="1" stop-color="#FF2D2D" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="dr-wall" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#FF3A3A"/>
      <stop offset="1" stop-color="#A81515"/>
    </linearGradient>
    <linearGradient id="dr-ceil" gradientUnits="userSpaceOnUse" x1="0" y1="110" x2="0" y2="210">
      <stop offset="0" stop-color="#000" stop-opacity=".75"/>
      <stop offset="1" stop-color="#000" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="dr-top" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#E6E6E6"/>
      <stop offset="1" stop-color="#FFFFFF"/>
    </linearGradient>
    <linearGradient id="dr-face" gradientUnits="userSpaceOnUse" x1="260" y1="60" x2="60"
      y2="520">
      <stop offset="0" stop-color="#3A3A3A"/>
      <stop offset="1" stop-color="#141414"/>
    </linearGradient>
  </defs>
    <polygon fill="url(#dr-beam)"
      points="260,512 354,463.6 603.6,514.4 892,592.3 892,757.6 260,568"/>
    <polygon fill="#000" points="260,110 603.6,166 603.6,514.4 354,463.6 354,184.4"/>
    <polygon fill="url(#dr-wall)" points="260,110 354,184.4 354,463.6 260,512"/>
    <polygon fill="url(#dr-ceil)" points="260,110 354,184.4 354,463.6 260,512"/>
    <polygon fill="url(#dr-top)" points="260,38 634,138 603.6,166 260,110"/>
    <polygon fill="#FFFFFF" points="634,138 634,517 603.6,514.4 603.6,166"/>
    <polygon fill="url(#dr-face)" points="40,168 260,38 260,572 40,509.6"/>
</svg>"""

_STYLE = """
  body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 0;
         background: #f5f3ef; color: #22262e; }
  header { background: #0B0B0B; color: #f5f3ef; padding: 16px 28px;
           display: flex; align-items: center; gap: 14px; }
  header .mark { width: 30px; height: auto; flex: 0 0 auto; }
  header h1 { font-size: 18px; margin: 0; }
  header p { margin: 4px 0 0; font-size: 13px; opacity: .75; }
  .badge { display: inline-block; border-radius: 10px; padding: 2px 10px;
           font-size: 12px; font-weight: 600; margin-left: 8px; }
  .pass { background: #dcefe2; color: #23703f; }
  .fail { background: #f6dcdc; color: #8f2727; }
  main { max-width: 1100px; margin: 0 auto; padding: 20px 28px 60px; }
  section { background: white; border: 1px solid #ddd6c9; border-radius: 6px;
            padding: 18px 22px; margin-top: 22px; }
  h2 { font-size: 16px; margin: 0 0 12px; }
  /* One item per row. A wrapping strip reads as a filmstrip, which flatters
     a run of screenshots and misrepresents everything else: the items of a
     scenario are a sequence a person follows in order, and side by side they
     read as alternatives. Vertical also lets a caption sit with its item
     instead of being squeezed under a 320px column. */
  .strip { display: flex; flex-direction: column; gap: 18px; }
  figure { margin: 0; max-width: 720px; }
  figure img { max-width: 100%; border: 1px solid #ccc; border-radius: 3px; }
  figure.failure img { border: 3px solid #c0392b; }
  figcaption { font-size: 12px; color: #6b6154; margin-top: 4px; }
  video { max-width: 480px; display: block; }
  details { margin-top: 10px; font-size: 13px; }
  details pre { background: #f7f6f3; border: 1px solid #e4ddd0; padding: 10px;
                overflow-x: auto; font-size: 12px; }
  ul.criteria { list-style: none; padding: 0; margin: 0 0 14px; font-size: 13px; }
  ul.criteria li { margin: 3px 0; }
  a { color: #7a5c3e; }
"""


def _slug(item: EvidenceItem) -> str:
    return "item-" + item.path.as_posix().replace("/", "-").replace(".", "-")


def _data_uri(path: Path, mime: str) -> str:
    payload = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{payload}"


def _media_src(item: EvidenceItem, base_dir: Path, embed: bool) -> str | None:
    path = item.path if item.path.is_absolute() else base_dir / item.path
    if not path.exists():
        return None
    if embed:
        return _data_uri(path, item.mime)
    return html.escape(item.path.as_posix())


def _score_badge(earned: float, possible: float, passed: bool) -> str:
    css = "pass" if passed else "fail"
    if possible:
        label = f"{100.0 * earned / possible:.1f}%"
    else:
        label = "unscored"
    return f'<span class="badge {css}">{html.escape(label)}</span>'


def _criteria_list(scenario_eval, known_slugs: dict[str, str]) -> str:
    rows = []
    for criterion in scenario_eval.criteria:
        mark = "✓" if criterion.passed else "✗"
        css = "pass" if criterion.passed else "fail"
        cites = []
        for cited in criterion.evidence:
            slug = known_slugs.get(cited)
            label = html.escape(cited)
            cites.append(f'<a href="#{slug}">{label}</a>' if slug else label)
        cite_text = f" — {', '.join(cites)}" if cites else ""
        note = f" <em>{html.escape(criterion.notes)}</em>" if criterion.notes else ""
        rows.append(
            f'<li><span class="badge {css}">{mark}</span> '
            f"{html.escape(criterion.criterion)} "
            f"({criterion.points_earned:g}/{criterion.points_possible:g})"
            f"{cite_text}{note}</li>"
        )
    return f'<ul class="criteria">{"".join(rows)}</ul>'


def _item_html(item: EvidenceItem, base_dir: Path, embed: bool, registry) -> str:
    slug = _slug(item)
    caption = f"{html.escape(item.step)} · {html.escape(item.kind)}"
    failure = " failure" if item.step == "FAILURE" else ""

    if item.mime.startswith("image/"):
        src = _media_src(item, base_dir, embed)
        if src is None:
            return f'<figure id="{slug}"><figcaption>{caption} (file missing)</figcaption></figure>'
        return (
            f'<figure id="{slug}" class="shot{failure}">'
            f'<a href="{src}"><img src="{src}" alt="{caption}"></a>'
            f"<figcaption>{caption}</figcaption></figure>"
        )

    if item.mime.startswith("video/"):
        src = _media_src(item, base_dir, embed)
        if src is None:
            return f'<figure id="{slug}"><figcaption>{caption} (file missing)</figcaption></figure>'
        return (
            f'<figure id="{slug}"><video controls src="{src}"></video>'
            f"<figcaption>{caption}</figcaption></figure>"
        )

    rendered = registry.render(item, base_dir)
    return (
        f'<details id="{slug}"><summary>{caption}</summary>'
        f"<pre>{html.escape(rendered.text)}</pre></details>"
    )


def render_gallery(
    manifest: RunManifest,
    base_dir: Path,
    evaluation: Evaluation | None = None,
    embed: bool = False,
) -> str:
    registry = default_registry()
    known_slugs = {
        item.path.as_posix(): _slug(item)
        for bundle in manifest.scenarios
        for item in bundle.items
    }

    header_badge = ""
    if evaluation is not None:
        header_badge = _score_badge(
            evaluation.total_earned, evaluation.total_possible, evaluation.all_passed
        )
        if evaluation.rubric_version:
            header_badge += (
                f' <span class="badge">rubric v'
                f"{html.escape(evaluation.rubric_version)}</span>"
            )

    sections = []
    for bundle in manifest.scenarios:
        scenario_eval = (
            evaluation.for_scenario(bundle.scenario) if evaluation else None
        )
        badge = ""
        criteria = ""
        if scenario_eval is not None:
            badge = _score_badge(
                scenario_eval.points_earned,
                scenario_eval.points_possible,
                scenario_eval.passed,
            )
            criteria = _criteria_list(scenario_eval, known_slugs)
        media = [
            _item_html(item, base_dir, embed, registry) for item in bundle.items
        ]
        sections.append(
            f"<section><h2>{html.escape(bundle.scenario)}{badge}</h2>"
            f'{criteria}<div class="strip">{"".join(media)}</div></section>'
        )

    project = f" · {html.escape(manifest.project)}" if manifest.project else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>darkroom · {html.escape(manifest.run_id)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<header>{_MARK}<div>"
        f"<h1>run {html.escape(manifest.run_id)}{project}"
        f"{header_badge}</h1>"
        f"<p>schema {html.escape(manifest.schema_version)} · "
        f"written {html.escape(manifest.timestamp)}</p></div></header>"
        f"<main>{''.join(sections)}</main></body></html>"
    )


def load_evaluation_lenient(path: Path) -> Evaluation:
    """Load an evaluation file, falling back to judge-drift coercion."""
    text = Path(path).read_text()
    try:
        return loads_evaluation(text)
    except (KeyError, ValueError):
        return coerce_evaluation(json.loads(text))


def write_gallery(
    manifest_path: Path,
    out: Path | None = None,
    evaluation_path: Path | None = None,
    embed: bool = False,
) -> Path:
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    evaluation = (
        load_evaluation_lenient(evaluation_path) if evaluation_path else None
    )
    html_text = render_gallery(
        manifest, manifest_path.parent, evaluation=evaluation, embed=embed
    )
    out = Path(out) if out else manifest_path.parent / "gallery.html"
    out.write_text(html_text)
    return out
