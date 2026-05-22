#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import markdown
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, UnidentifiedImageError
from weasyprint import HTML

ROOT: Final[Path] = Path(__file__).resolve().parent
SOURCE_MD: Final[Path] = ROOT / "leo4-vendor-execution-layer-response.md"
OUTPUT_PDF: Final[Path] = ROOT / "leo4-vendor-execution-layer-response.pdf"
MERMAID_CACHE: Final[Path] = ROOT / "_mermaid_cache"
IMG_CACHE: Final[Path] = ROOT / "_img_cache"
DOWNLOAD_TIMEOUT: Final[int] = 45
MERMAID_TIMEOUT: Final[int] = 60

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
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
    except (OSError, ValueError, UnidentifiedImageError) as exc:  # pragma: no cover
        raise RuntimeError(f"Invalid PNG generated at {path}: {exc}") from exc

    if width < 50 or height < 50:
        raise RuntimeError(
            f"Mermaid PNG at {path} looks like an error image ({width}x{height})."
        )


def render_mermaid_to_png(source: str) -> MermaidImage:
    # 20 hex chars (80 bits) keep cache filenames compact while keeping collision risk negligible for this document scale.
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
    out_file = MERMAID_CACHE / f"{digest}.png"
    if out_file.exists():
        validate_png(out_file)
        return MermaidImage(
            hash_id=digest, relative_path=f"_mermaid_cache/{out_file.name}"
        )

    encoded = (
        base64.urlsafe_b64encode(source.encode("utf-8")).decode("ascii").rstrip("=")
    )
    url = f"https://mermaid.ink/img/{encoded}?type=png&bgColor=ffffff&width=900"
    try:
        response = requests.get(url, timeout=MERMAID_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Mermaid rendering failed for diagram {digest}: unable to reach mermaid.ink ({exc})"
        ) from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Mermaid rendering failed for diagram {digest}: HTTP {response.status_code}"
        )

    content_type = response.headers.get("Content-Type", "")
    if "image/png" not in content_type:
        raise RuntimeError(
            f"Mermaid rendering failed for diagram {digest}: expected image/png, got {content_type!r}"
        )

    out_file.write_bytes(response.content)
    validate_png(out_file)
    return MermaidImage(hash_id=digest, relative_path=f"_mermaid_cache/{out_file.name}")


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


def cache_hmi_images() -> dict[str, str]:
    local_paths: dict[str, str] = {}
    for filename, url in HMI_IMAGES.items():
        target = IMG_CACHE / filename
        if not target.exists():
            try:
                download_binary(url, target)
            except (requests.RequestException, OSError) as exc:
                print(
                    f"Warning: failed to download {url}, using placeholder image ({exc})",
                    file=sys.stderr,
                )
                image = Image.new("RGB", (640, 400), color="#eef3fa")
                draw = ImageDraw.Draw(image)
                draw.text((28, 170), "L4-HMI image unavailable", fill="#1a2e4a")
                draw.text(
                    (28, 200), "Source image temporarily unreachable", fill="#0057b8"
                )
                image.save(target, format="JPEG", quality=92)
        local_paths[filename] = f"_img_cache/{filename}"
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
        '<div class="hmi-row">'
        f"<img src=\"{local_paths['l4-hmi-1-640.jpg']}\" alt=\"L4-HMI interface example 1\"/>"
        f"<img src=\"{local_paths['l4-hmi-2-640.jpg']}\" alt=\"L4-HMI interface example 2\"/>"
        "</div>"
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
  <div class=\"cover-icon\">🏗️</div>
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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    @page {{
      size: A4;
      margin: 20mm 22mm;
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

    .cover-icon {{ font-size: 56pt; margin-bottom: 8mm; }}
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

    table {{ width: 100%; border-collapse: collapse; margin: 4mm 0 6mm 0; font-size: 10pt; table-layout: fixed; }}
    thead th {{ background: #0057b8; color: #fff; padding: 7px; text-align: left; }}
    tbody td {{ border: 1px solid #d7dbe2; padding: 7px; vertical-align: top; }}
    tbody tr:nth-child(even) {{ background: #f7f9fc; }}

    .admonition {{ border-radius: 8px; padding: 8px 10px; margin: 4mm 0; border: 1px solid; }}
    .admonition-title {{ margin: 0 0 4px 0; font-weight: 700; }}
    .admonition.note {{ background: #fffbe6; border-color: #f5a623; }}
    .admonition.warning {{ background: #fff0f0; border-color: #e53935; }}
    .admonition.important {{ background: #e8f4fd; border-color: #0057b8; }}

    .hmi-row {{
      display: flex;
      gap: 12px;
      flex-wrap: nowrap;
      align-items: flex-start;
      width: 100%;
      margin: 4mm 0 5mm 0;
      page-break-inside: avoid;
    }}
    .hmi-row img {{
      width: 48%;
      max-width: 48%;
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
    HTML(string=html_document, base_url=str(ROOT)).write_pdf(str(OUTPUT_PDF))

    print(f"Generated PDF: {OUTPUT_PDF}")


if __name__ == "__main__":
    build_pdf()
