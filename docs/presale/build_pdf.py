#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import math
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import markdown
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from weasyprint import HTML

ROOT: Final[Path] = Path(__file__).resolve().parent
SOURCE_MD: Final[Path] = ROOT / "leo4-vendor-execution-layer-response.md"
OUTPUT_PDF: Final[Path] = ROOT / "leo4-vendor-execution-layer-response.pdf"
MERMAID_CACHE: Final[Path] = ROOT / "_mermaid_cache"
IMG_CACHE: Final[Path] = ROOT / "_img_cache"
DOWNLOAD_TIMEOUT: Final[int] = 45
MERMAID_TIMEOUT: Final[int] = 60
# Existing placeholder images were under 10 KB; real/local-rendered assets are much larger.
PLACEHOLDER_SIZE_LIMIT: Final[int] = 20_000

HMI_IMAGES: Final[dict[str, str]] = {
    "l4-hmi-1-640.jpg": "https://raw.githubusercontent.com/OlegLebedevRU/l4-hmi/main/docs/l4-hmi-1-640.jpg",
    "l4-hmi-2-640.jpg": "https://raw.githubusercontent.com/OlegLebedevRU/l4-hmi/main/docs/l4-hmi-2-640.jpg",
}

HEADING_ICONS: Final[list[tuple[str, str]]] = [
    ("Executive summary", "📋"),
    ("Голос клиента", "💬"),
    ("Позиционирование", "🎯"),
    ("Трёхуровневая архитектура", "🏗️"),
    ("Ответ на главный security-вопрос", "🔐"),
    ("Три жёстких архитектурных кейса", "⚙️"),
    ("Deployment-модели", "🚀"),
    ("Контроль method codes", "🛡️"),
    ("События, статусы", "📡"),
    ("Надёжность доставки", "🔄"),
    ("Offline", "📴"),
    ("Kiosk UI", "🖥️"),
    ("Минимальный тестовый стенд", "🧪"),
    ("Тест-план", "✅"),
    ("Матрица соответствия", "📊"),
    ("Что нужно финализировать", "📌"),
    ("Рекомендованная формулировка", "📝"),
    ("Контроллерный контур", "🔧"),
    ("Ссылки на документацию", "🔗"),
]


@dataclass(frozen=True)
class MermaidImage:
    hash_id: str
    relative_path: str


def ensure_dirs() -> None:
    MERMAID_CACHE.mkdir(parents=True, exist_ok=True)
    IMG_CACHE.mkdir(parents=True, exist_ok=True)


def download_binary(url: str, target: Path) -> None:
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to download {url}: HTTP {response.status_code}")
    target.write_bytes(response.content)


def validate_png(path: Path) -> None:
    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
    except (OSError, ValueError, UnidentifiedImageError) as exc:  # pragma: no cover
        raise RuntimeError(f"Invalid PNG generated at {path}: {exc}") from exc

    if width < 50 or height < 50:
        raise RuntimeError(
            f"Mermaid PNG at {path} looks like an error image ({width}x{height})."
        )


def image_path(path: str) -> str:
    return (ROOT / path).resolve().as_uri()


def load_font(
    size: int, *, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def text_size(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont
) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> list[str]:
    words = text.replace("/", " / ").split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if text_size(draw, candidate, font)[0] <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current).replace(" / ", "/"))
            current = [word]
    if current:
        lines.append(" ".join(current).replace(" / ", "/"))
    return lines


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    max_width: int,
    line_height: int,
    *,
    anchor_center: bool = False,
) -> None:
    lines = wrap_text(draw, text, font, max_width)
    x, y = xy
    if anchor_center:
        y -= (line_height * len(lines)) // 2
    for line in lines:
        if anchor_center:
            width, _ = text_size(draw, line, font)
            draw.text((x - width // 2, y), line, font=font, fill=fill)
        else:
            draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def extract_flowchart(
    source: str,
) -> tuple[str, dict[str, str], list[tuple[str, str, str]]]:
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    direction = "TD"
    if lines and lines[0].startswith("flowchart"):
        parts = lines[0].split()
        if len(parts) > 1:
            direction = parts[1]

    labels: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    node_pattern = re.compile(r"([A-Za-z][\w]*)\[([^\]]+)\]")
    edge_pattern = re.compile(
        r"([A-Za-z][\w]*)(?:\[[^\]]+\])?\s*(-->|---|-.+?\.->)\s*([A-Za-z][\w]*)(?:\[[^\]]+\])?"
    )

    for line in lines[1:]:
        for node_id, label in node_pattern.findall(line):
            labels[node_id] = label
        edge_match = edge_pattern.search(line)
        if edge_match:
            start, arrow, end = edge_match.groups()
            label_match = re.search(r"\.\s*([^.]+?)\s*\.->", arrow)
            edges.append((start, end, label_match.group(1) if label_match else ""))
            labels.setdefault(start, start)
            labels.setdefault(end, end)

    return direction, labels, edges


def flowchart_levels(
    labels: dict[str, str], edges: list[tuple[str, str, str]]
) -> dict[str, int]:
    levels = {node_id: 0 for node_id in labels}
    for _ in range(len(labels) + 1):
        changed = False
        for start, end, _ in edges:
            if levels[end] <= levels[start]:
                levels[end] = levels[start] + 1
                changed = True
        if not changed:
            break
    return levels


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: str = "#4a6078",
    width: int = 3,
) -> None:
    draw.line([start, end], fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 11
    points = [
        end,
        (
            int(end[0] - size * math.cos(angle - math.pi / 6)),
            int(end[1] - size * math.sin(angle - math.pi / 6)),
        ),
        (
            int(end[0] - size * math.cos(angle + math.pi / 6)),
            int(end[1] - size * math.sin(angle + math.pi / 6)),
        ),
    ]
    draw.polygon(points, fill=fill)


def render_flowchart_local(source: str, target: Path) -> None:
    direction, labels, edges = extract_flowchart(source)
    levels = flowchart_levels(labels, edges)
    grouped: dict[int, list[str]] = {}
    for node_id, level in levels.items():
        grouped.setdefault(level, []).append(node_id)

    max_group = max((len(nodes) for nodes in grouped.values()), default=1)
    level_count = max(grouped.keys(), default=0) + 1
    left_right = direction.upper() == "LR"
    width = max(1100, (level_count if left_right else max_group) * 250 + 180)
    height = max(620, (max_group if left_right else level_count) * 150 + 160)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(22)
    small_font = load_font(16)
    node_w, node_h = 190, 72
    positions: dict[str, tuple[int, int]] = {}

    for level, nodes in grouped.items():
        nodes = sorted(nodes)
        for index, node_id in enumerate(nodes):
            if left_right:
                x = 90 + level * 250
                y = 90 + index * 150
            else:
                x = 90 + index * 250 + (max_group - len(nodes)) * 125
                y = 80 + level * 150
            positions[node_id] = (x + node_w // 2, y + node_h // 2)
            draw.rounded_rectangle(
                (x, y, x + node_w, y + node_h),
                radius=14,
                fill="#eef6ff",
                outline="#0057b8",
                width=3,
            )
            draw_wrapped_text(
                draw,
                (x + node_w // 2, y + node_h // 2),
                labels[node_id],
                font,
                "#1a2e4a",
                node_w - 24,
                25,
                anchor_center=True,
            )

    for start, end, edge_label in edges:
        if start not in positions or end not in positions:
            continue
        sx, sy = positions[start]
        ex, ey = positions[end]
        if left_right:
            start_pt, end_pt = (sx + node_w // 2, sy), (ex - node_w // 2, ey)
        else:
            start_pt, end_pt = (sx, sy + node_h // 2), (ex, ey - node_h // 2)
        draw_arrow(draw, start_pt, end_pt)
        if edge_label:
            mx, my = (start_pt[0] + end_pt[0]) // 2, (start_pt[1] + end_pt[1]) // 2
            draw.text((mx + 6, my - 20), edge_label, font=small_font, fill="#5b6f8b")

    image.save(target, format="PNG")


def render_sequence_local(source: str, target: Path) -> None:
    participant_pattern = re.compile(r"participant\s+(\w+)\s+as\s+(.+)")
    message_pattern = re.compile(r"(\w+)\s*(-->>|->>)\s*(\w+):\s*(.+)")
    participants: list[tuple[str, str]] = []
    messages: list[tuple[str, str, str, bool]] = []

    for line in source.splitlines():
        stripped = line.strip()
        participant_match = participant_pattern.match(stripped)
        if participant_match:
            participants.append(participant_match.groups())
            continue
        message_match = message_pattern.match(stripped)
        if message_match:
            start, arrow, end, label = message_match.groups()
            messages.append((start, end, label, arrow.startswith("--")))

    width = max(1100, 160 + len(participants) * 190)
    height = max(620, 160 + len(messages) * 70)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    bold = load_font(18, bold=True)
    small = load_font(15)

    x_positions = {
        code: 90 + index * ((width - 180) // max(1, len(participants) - 1))
        for index, (code, _) in enumerate(participants)
    }

    for code, label in participants:
        x = x_positions[code]
        draw.rounded_rectangle(
            (x - 70, 34, x + 70, 92),
            radius=12,
            fill="#eef6ff",
            outline="#0057b8",
            width=3,
        )
        draw_wrapped_text(
            draw, (x, 63), label, bold, "#1a2e4a", 126, 20, anchor_center=True
        )
        draw.line((x, 92, x, height - 45), fill="#c8d4e3", width=2)

    y = 130
    for start, end, label, dashed in messages:
        if start not in x_positions or end not in x_positions:
            continue
        sx, ex = x_positions[start], x_positions[end]
        line_fill = "#7d8fa3" if dashed else "#4a6078"
        draw_arrow(draw, (sx, y), (ex, y), fill=line_fill, width=3)
        text_x = min(sx, ex) + 12
        draw_wrapped_text(
            draw, (text_x, y - 30), label, small, "#1a2e4a", abs(ex - sx) - 24, 18
        )
        y += 70

    image.save(target, format="PNG")


def render_mermaid_local(source: str, target: Path) -> None:
    stripped = source.lstrip()
    if stripped.startswith("sequenceDiagram"):
        render_sequence_local(source, target)
    elif stripped.startswith("flowchart"):
        render_flowchart_local(source, target)
    else:
        raise RuntimeError(
            "Unsupported Mermaid diagram type for local fallback renderer"
        )


def render_mermaid_to_png(source: str) -> MermaidImage:
    # 20 hex chars (80 bits) keep filenames compact; this document has only a handful of diagrams,
    # far below the scale where birthday-bound collision risk is relevant.
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
    out_file = MERMAID_CACHE / f"{digest}.png"
    if out_file.exists() and out_file.stat().st_size > PLACEHOLDER_SIZE_LIMIT:
        validate_png(out_file)
        return MermaidImage(
            hash_id=digest, relative_path=image_path(f"_mermaid_cache/{out_file.name}")
        )

    encoded = (
        base64.urlsafe_b64encode(source.encode("utf-8")).decode("ascii").rstrip("=")
    )
    url = f"https://mermaid.ink/img/{encoded}?type=png&bgColor=ffffff&width=900"
    try:
        response = requests.get(url, timeout=MERMAID_TIMEOUT)
    except requests.RequestException as exc:
        print(
            f"Warning: mermaid.ink unavailable for diagram {digest}; using local renderer ({exc})",
            file=sys.stderr,
        )
        render_mermaid_local(source, out_file)
        validate_png(out_file)
        return MermaidImage(
            hash_id=digest, relative_path=image_path(f"_mermaid_cache/{out_file.name}")
        )

    if response.status_code != 200:
        print(
            f"Warning: mermaid.ink returned HTTP {response.status_code} for diagram {digest}; using local renderer",
            file=sys.stderr,
        )
        render_mermaid_local(source, out_file)
        validate_png(out_file)
        return MermaidImage(
            hash_id=digest, relative_path=image_path(f"_mermaid_cache/{out_file.name}")
        )

    content_type = response.headers.get("Content-Type", "")
    if "image/png" not in content_type:
        print(
            f"Warning: mermaid.ink returned {content_type!r} for diagram {digest}; using local renderer",
            file=sys.stderr,
        )
        render_mermaid_local(source, out_file)
        validate_png(out_file)
        return MermaidImage(
            hash_id=digest, relative_path=image_path(f"_mermaid_cache/{out_file.name}")
        )

    out_file.write_bytes(response.content)
    validate_png(out_file)
    return MermaidImage(
        hash_id=digest, relative_path=image_path(f"_mermaid_cache/{out_file.name}")
    )


def replace_mermaid_blocks(md_text: str) -> str:
    pattern = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL)

    def replacer(match: re.Match[str]) -> str:
        diagram_source = match.group(1).strip()
        rendered = render_mermaid_to_png(diagram_source)
        return (
            "\n"
            f'<figure class="mermaid-diagram"><img src="{rendered.relative_path}" '
            'alt="Mermaid diagram"/></figure>\n'
        )

    return pattern.sub(replacer, md_text)


def convert_github_callouts(md_text: str) -> str:
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        callout_match = re.match(r"^>\s*\[!(NOTE|WARNING|IMPORTANT)\]\s*$", line)
        if not callout_match:
            out.append(line)
            i += 1
            continue

        kind = callout_match.group(1).lower()
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].startswith(">"):
            body_line = re.sub(r"^>\s?", "", lines[i])
            body.append(body_line)
            i += 1

        out.append(f"!!! {kind}")
        if not body:
            out.append("    ")
        else:
            for row in body:
                out.append(f"    {row}")
        out.append("")

    return "\n".join(out)


def create_hmi_placeholder(target: Path, title: str, accent: str) -> None:
    image = Image.new("RGB", (640, 390), color="#f3f7fb")
    draw = ImageDraw.Draw(image)
    title_font = load_font(24, bold=True)
    font = load_font(17)
    small = load_font(13)

    draw.rounded_rectangle((18, 18, 622, 372), radius=26, fill="#1a2e4a")
    draw.rounded_rectangle((38, 42, 602, 332), radius=18, fill="#f8fbff")
    draw.rounded_rectangle((58, 62, 582, 112), radius=12, fill=accent)
    draw.text((78, 75), title, fill="white", font=title_font)
    draw.text((78, 123), "Self-service HMI flow preview", fill="#1a2e4a", font=font)

    cards = [
        ("01", "Select locker / cell"),
        ("02", "Authorize operation"),
        ("03", "Open and confirm by event"),
    ]
    for index, (number, label) in enumerate(cards):
        y = 165 + index * 48
        draw.rounded_rectangle((78, y, 562, y + 36), radius=10, fill="#eef6ff")
        draw.ellipse((92, y + 8, 112, y + 28), fill=accent)
        draw.text((96, y + 8), number[-1], fill="white", font=small)
        draw.text((128, y + 8), label, fill="#1a2e4a", font=font)

    draw.rounded_rectangle((190, 292, 450, 322), radius=15, fill=accent)
    button_text = "Event-confirmed result"
    text_w, text_h = text_size(draw, button_text, font)
    draw.text(
        (320 - text_w // 2, 307 - text_h // 2), button_text, fill="white", font=font
    )
    image.save(target, format="JPEG", quality=94)


def cache_hmi_images() -> dict[str, str]:
    local_paths: dict[str, str] = {}
    accents = ["#0057b8", "#18a058"]
    for index, (filename, url) in enumerate(HMI_IMAGES.items()):
        target = IMG_CACHE / filename
        if not target.exists() or target.stat().st_size <= PLACEHOLDER_SIZE_LIMIT:
            try:
                download_binary(url, target)
            except (RuntimeError, requests.RequestException, OSError) as exc:
                print(
                    f"Warning: failed to download {url}, using placeholder image ({exc})",
                    file=sys.stderr,
                )
                create_hmi_placeholder(target, f"L4-HMI #{index + 1}", accents[index])
        local_paths[filename] = image_path(f"_img_cache/{filename}")
    return local_paths


def replace_hmi_block(md_text: str, local_paths: dict[str, str]) -> str:
    md_text = md_text.replace(
        "https://github.com/OlegLebedevRU/l4-hmi/blob/main/docs/l4-hmi-1-640.jpg",
        local_paths["l4-hmi-1-640.jpg"],
    )
    md_text = md_text.replace(
        "https://github.com/OlegLebedevRU/l4-hmi/blob/main/docs/l4-hmi-2-640.jpg",
        local_paths["l4-hmi-2-640.jpg"],
    )

    block_pattern = re.compile(
        r"!\[L4-HMI interface example 1\]\([^)]*l4-hmi-1-640\.jpg\)\s*\n\s*"
        r"!\[L4-HMI interface example 2\]\([^)]*l4-hmi-2-640\.jpg\)",
        re.DOTALL,
    )
    replacement = (
        '<table class="hmi-table"><tr>'
        f'<td><img src="{local_paths["l4-hmi-1-640.jpg"]}" alt="L4-HMI interface example 1"/></td>'
        f'<td><img src="{local_paths["l4-hmi-2-640.jpg"]}" alt="L4-HMI interface example 2"/></td>'
        "</tr></table>"
    )
    return block_pattern.sub(replacement, md_text)


def add_heading_icons(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")

    for header in soup.select("h2, h3"):
        text = header.get_text(strip=True)
        for keyword, icon in HEADING_ICONS:
            if text.lower().startswith(keyword.lower()):
                icon_span = soup.new_tag("span", attrs={"class": "icon"})
                icon_span.string = icon
                header.insert(0, icon_span)
                break

    for table in soup.find_all("table"):
        header_text = " ".join(
            th.get_text(" ", strip=True) for th in table.select("thead th")
        )
        if (
            "Где исполняется orchestration" in header_text
            and "Offline-возможности" in header_text
        ):
            table["class"] = [*table.get("class", []), "comparison-table"]
            wrapper = soup.new_tag("div", attrs={"class": "comparison-table-wrap"})
            table.wrap(wrapper)

    return str(soup)


def markdown_to_html(md_text: str) -> str:
    html_body = markdown.markdown(
        md_text,
        extensions=[
            "extra",
            "admonition",
            "tables",
            "fenced_code",
            "pymdownx.superfences",
        ],
        output_format="html5",
    )
    html_body = add_heading_icons(html_body)
    return html_body


def build_html(content_html: str) -> str:
    today = date.today().isoformat()
    cover = f"""
<section class=\"cover\">
  <h1>LEO4 как vendor execution layer</h1>
  <h2>Три архитектурных режима — Presale Document</h2>
  <div class=\"cover-date\">{today}</div>
  <div class=\"cover-watermark\">Version 1.0</div>
</section>
"""

    return f"""<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <style>
    /* CSS braces are doubled because this stylesheet is embedded in a Python f-string. */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    @page {{
      size: A4;
      margin: 20mm 22mm;
    }}

    @page wide {{
      size: A4 landscape;
      margin: 14mm 12mm;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      font-family: 'Inter', sans-serif;
      color: #162030;
      line-height: 1.55;
      font-size: 11pt;
    }}

    .cover {{
      min-height: 240mm;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      text-align: center;
      page-break-after: always;
      position: relative;
      border: 2px solid #0057b8;
      border-radius: 10px;
      padding: 24mm 10mm;
    }}

    .cover h1 {{ color: #1a2e4a; font-size: 30pt; margin: 0 0 6mm 0; }}
    .cover h2 {{ color: #0057b8; font-weight: 600; font-size: 16pt; margin: 0 0 8mm 0; }}
    .cover-date {{ font-size: 12pt; color: #1a2e4a; }}
    .cover-watermark {{
      position: absolute;
      bottom: 8mm;
      left: 0;
      right: 0;
      text-align: center;
      color: #5b6f8b;
      font-size: 9pt;
      letter-spacing: 0.08em;
    }}

    h1, h2, h3, h4 {{ color: #1a2e4a; }}
    h1 {{ font-size: 22pt; margin-top: 0; }}
    h2 {{ font-size: 16pt; margin-top: 9mm; border-bottom: 2px solid #0057b8; padding-bottom: 2mm; }}
    h3 {{ font-size: 13pt; margin-top: 6mm; }}
    .icon {{ font-size: 1.2em; margin-right: 0.35em; vertical-align: -0.08em; }}

    hr {{ border: 0; border-top: 2px solid #0057b8; margin: 5mm 0; }}

    p code, li code {{
      font-family: 'JetBrains Mono', monospace;
      background: #f4f6f8;
      padding: 0.1em 0.35em;
      border-radius: 4px;
      font-size: 0.92em;
    }}

    pre {{
      font-family: 'JetBrains Mono', monospace;
      background: #f4f6f8;
      border-radius: 6px;
      padding: 10px 12px;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}

    pre code {{ background: transparent; padding: 0; }}

    .mermaid-diagram {{ margin: 5mm 0; text-align: center; }}
    .mermaid-diagram img {{ max-width: 100%; height: auto; border: 1px solid #d8dee8; border-radius: 6px; }}

    table {{ width: 100%; border-collapse: collapse; margin: 4mm 0 6mm 0; font-size: 9.5pt; table-layout: fixed; overflow-wrap: anywhere; }}
    thead th {{ background: #0057b8; color: #fff; padding: 7px; text-align: left; }}
    tbody td {{ border: 1px solid #d7dbe2; padding: 7px; vertical-align: top; }}
    tbody tr:nth-child(even) {{ background: #f7f9fc; }}

    .comparison-table-wrap {{
      page: wide;
      break-before: page;
      break-after: page;
      page-break-inside: avoid;
    }}
    .comparison-table {{
      font-size: 8pt;
      line-height: 1.28;
      table-layout: fixed;
      margin-top: 0;
    }}
    .comparison-table th,
    .comparison-table td {{
      padding: 5px 6px;
      hyphens: auto;
      overflow-wrap: anywhere;
    }}
    .comparison-table th:nth-child(1),
    .comparison-table td:nth-child(1) {{ width: 10%; }}
    .comparison-table th:nth-child(2),
    .comparison-table td:nth-child(2) {{ width: 13%; }}
    .comparison-table th:nth-child(3),
    .comparison-table td:nth-child(3) {{ width: 9%; }}
    .comparison-table th:nth-child(4),
    .comparison-table td:nth-child(4) {{ width: 18%; }}
    .comparison-table th:nth-child(5),
    .comparison-table td:nth-child(5) {{ width: 13%; }}
    .comparison-table th:nth-child(6),
    .comparison-table td:nth-child(6) {{ width: 15%; }}
    .comparison-table th:nth-child(7),
    .comparison-table td:nth-child(7) {{ width: 10%; }}
    .comparison-table th:nth-child(8),
    .comparison-table td:nth-child(8) {{ width: 12%; }}

    .admonition {{ border-radius: 8px; padding: 8px 10px; margin: 4mm 0; border: 1px solid; }}
    .admonition-title {{ margin: 0 0 4px 0; font-weight: 700; }}
    .admonition.note {{ background: #fffbe6; border-color: #f5a623; }}
    .admonition.warning {{ background: #fff0f0; border-color: #e53935; }}
    .admonition.important {{ background: #e8f4fd; border-color: #0057b8; }}

    .hmi-table {{
      table-layout: fixed;
      border-collapse: separate;
      border-spacing: 12px 0;
      margin: 4mm 0 5mm 0;
      page-break-inside: avoid;
    }}
    .hmi-table td {{
      width: 50%;
      border: 0;
      padding: 0;
      background: transparent;
    }}
    .hmi-table img {{
      width: 100%;
      max-width: 100%;
      height: auto;
      border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      border: 1px solid #d8dee8;
    }}

    img {{ max-width: 100%; }}
    blockquote {{ margin: 0; padding-left: 10px; border-left: 3px solid #c7d3e0; color: #324559; }}
    ul, ol {{ padding-left: 22px; }}
  </style>
</head>
<body>
{cover}
{content_html}
</body>
</html>
"""


def build_pdf() -> None:
    ensure_dirs()

    md_text = SOURCE_MD.read_text(encoding="utf-8")
    local_paths = cache_hmi_images()
    md_text = replace_hmi_block(md_text, local_paths)
    md_text = replace_mermaid_blocks(md_text)
    md_text = convert_github_callouts(md_text)

    html_body = markdown_to_html(md_text)
    html_document = build_html(html_body)
    HTML(string=html_document, base_url=ROOT.as_uri()).write_pdf(str(OUTPUT_PDF))

    print(f"Generated PDF: {OUTPUT_PDF}")


if __name__ == "__main__":
    build_pdf()
