"""Static HTML and evidence verification; independent of native rendering."""
import html
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
from PIL import Image
from .catalog import checked_path, file_hash, save, utc


def build_html(plan, root):
    root = Path(root)
    esc = html.escape
    nav = "".join(f'<a href="#{sid}">{esc(scene["title"])}</a>' for sid, scene in plan["scenes"].items())
    parts = []
    completed = 0
    for sid, scene in plan["scenes"].items():
        section = [f'<section id="{sid}"><h2>{esc(scene["title"])}</h2>']
        for view in (v for v in plan["views"] if v["scene_id"] == sid):
            heading = f'<article><h3>{esc(view["title"])}</h3>'
            status = view.get("status")
            if status != "completed":
                label = {"needs-camera": "待选择机位", "stale": "配置已更新，待重新渲染", "pending": "尚未渲染"}.get(status, "尚未渲染")
                section.append(heading + f'<p class="pending">{label}</p></article>')
                continue
            completed += 1
            pair = []
            for kind, label in (("raw", "原始 · 未降噪"), ("processed", "处理后 · OIDN")):
                src = esc(view["outputs"][kind]["path"], quote=True)
                alt = esc(scene["title"] + " " + view["title"] + " " + label, quote=True)
                pair.append(f'<figure><a href="{src}" target="_blank"><img loading="lazy" src="{src}" alt="{alt}"></a><figcaption>{label}</figcaption></figure>')
            width, height = view["outputs"]["raw"].get("width", plan["resolution"][0]), view["outputs"]["raw"].get("height", plan["resolution"][1])
            exposure = view.get("rendered_exposure_ev", view.get("exposure_ev"))
            meta = f'{width} × {height} · 同次渲染 / 相同曝光 {exposure} EV'
            emission = view.get("lighting_overrides", {}).get("emissive_scale")
            if emission:
                meta += f' · emission ×{emission}'
            record = esc(view["record"], quote=True)
            section.append(heading + '<div class="pair">' + ''.join(pair) +
                           f'</div><p class="meta">{meta} · <a href="{record}">配置与记录</a></p></article>')
        section.append(f'<p class="credit">{esc(scene["credit"])} · <a href="scenes/{sid}.json">场景配置</a></p></section>')
        parts.append(''.join(section))
    summary = f'{len(plan["scenes"])} 个场景 · {completed} / {len(plan["views"])} 个机位已完成 · 原始与处理后 · 点击图片查看全分辨率'
    template = Path(__file__).with_name("page.html").read_text(encoding="utf-8")
    page = template.replace('__SUMMARY__', summary).replace('__NAV__', nav).replace('__BODY__', ''.join(parts))
    (root / "index.html").write_text(page, encoding="utf-8")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.anchors = set(), set(), set()
        self.images = self.sections = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.images += tag == "img"
        self.sections += tag == "section"
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            value = attrs.get(key, "")
            split = urlsplit(value)
            if value.startswith("#"):
                self.anchors.add(value[1:])
            elif value and not split.scheme and not split.netloc:
                self.links.add(unquote(split.path))


def verify(plan, root, allow_pending=False, build_config=None):
    root = Path(root)
    findings, verified, pending, native_verified = [], [], [], []
    expected_pngs = set()
    for view in plan["views"]:
        key = view["scene_id"] + "/" + view["id"]
        status = view.get("status")
        if status != "completed":
            pending.append(key)
            if status == "stale" or not allow_pending:
                findings.append(f'{key}: {status}')
            continue
        try:
            record_path = checked_path(root, view["record"])
            record = json.loads(record_path.read_text(encoding="utf-8"))
            config_path = record_path.parent / "config.json"
            if file_hash(config_path) != record["portable_reproduction_config_sha256"]:
                findings.append(f'{key}: native config hash mismatch')
            if build_config is not None:
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                desired = build_config(plan, view)
                for config in (saved, desired):
                    config.pop("repository_root", None)
                    config.pop("output", None)
                if saved != desired:
                    findings.append(f'{key}: saved native config differs from current requested config')
                else:
                    native_verified.append(key)
            if record["scene_id"] != view["scene_id"] or record["view_id"] != view["id"]:
                findings.append(f'{key}: wrong render record identity')
            sources, displays = [], []
            for kind in ("raw", "processed"):
                data = view["outputs"][kind]
                path = checked_path(root, data["path"])
                expected_pngs.add(data["path"])
                with Image.open(path) as im:
                    im.load()
                    if list(im.size) != plan["resolution"] or list(im.size) != [data["width"], data["height"]]:
                        findings.append(f'{key}/{kind}: wrong dimensions')
                    if json.loads(im.info["Camera"]) != view["camera"]:
                        findings.append(f'{key}/{kind}: camera metadata mismatch')
                    sources.append(im.info["Linear source SHA256"])
                    displays.append(json.loads(im.info["Display"]))
                if file_hash(path) != data["sha256"]:
                    findings.append(f'{key}/{kind}: PNG hash mismatch')
            if sources != [view["paired_linear_source_sha256"]]*2 or sources[0] != record["linear_source"]["sha256"]:
                findings.append(f'{key}: paired source mismatch')
            expected_display = {k: record["display"][k] for k in ("transform", "exposure_ev")}
            if displays != [expected_display]*2:
                findings.append(f'{key}: display/exposure mismatch')
            if not record["linear_source"]["same_source_for_both_pngs"] or record["linear_source"]["retained_on_disk"]:
                findings.append(f'{key}: invalid source retention/pairing record')
            verified.append(key)
        except (OSError, KeyError, ValueError, TypeError) as error:
            findings.append(f'{key}: {error}')
    # Scouts are intentionally separate previews; inspect only the published scene trees for PNG counts.
    actual_pngs = {p.relative_to(root).as_posix() for sid in plan["scenes"] for p in (root / sid).rglob("*.png")}
    if actual_pngs != expected_pngs:
        findings.append('Published PNG set differs from completed views: ' + str(sorted(actual_pngs ^ expected_pngs)))
    floats = [p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p.suffix.lower() in ('.gz', '.pfm', '.hdr', '.rgba16f', '.rgba32f')]
    if floats:
        findings.append('Retained float files: ' + str(floats))
    links = Links()
    try:
        links.feed((root / "index.html").read_text(encoding="utf-8"))
        for relative in links.links:
            if not checked_path(root, relative).is_file():
                findings.append('Broken HTML link: ' + relative)
        if links.anchors - links.ids:
            findings.append('Missing HTML anchors: ' + str(sorted(links.anchors - links.ids)))
        if links.images != len(verified)*2 or links.sections != len(plan["scenes"]):
            findings.append('HTML counts differ from manifest; regenerate with --html')
    except (OSError, ValueError) as error:
        findings.append(f'HTML: {error}')
    report = {'checked_utc': utc(), 'passed': not findings, 'scene_count': len(plan['scenes']),
              'view_count': len(verified), 'configured_view_count': len(plan['views']), 'pending_views': pending,
              'png_count': len(actual_pngs), 'html_image_count': links.images,
              'html_scene_sections': links.sections, 'html_local_files_checked': len(links.links),
              'exact_same_source_and_display_verified_pairs': verified,
              'native_configs_regenerated_and_equal_to_saved': native_verified,
              'no_persistent_hdr_pfm': not floats,
              'total_bytes': sum(p.stat().st_size for p in root.rglob('*') if p.is_file()), 'failures': findings}
    save(root / 'verification.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if findings:
        raise RuntimeError('Gallery verification failed; see verification.json')
    return report
