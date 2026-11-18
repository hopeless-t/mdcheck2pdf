#!/usr/bin/env python3
# mdcheck2pdf — Markdownチェックリストを「押せる欄」を持つPDFに変換する
# Copyright (C) 2026 TONEGAWA Kiyotaka (CAT NOOD LAB)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""mdcheck2pdf — Markdownのチェックリストを「押せる欄」を持つPDFに変換する。

Markdown の `- [ ]` / `- [x]` を、PDF のフォーム（AcroForm）チェックボックス
として埋め込む。PDF を開いたままクリックでチェックを付け外しでき、
印刷すれば紙のチェック欄としても使える。

2段構成:
  1段目 (fpdf2): 本文をレイアウトしながら、各チェック項目の
                 ページ番号と位置を記録する。
  2段目 (PyMuPDF): 記録した位置に本物のチェックボックス欄を差し込む。

使い方:
  python3 mdcheck2pdf.py input.md output.pdf [--font REGULAR.ttc] [--font-bold BOLD.ttc]

依存: fpdf2, PyMuPDF (pip install fpdf2 pymupdf)
フォント: 日本語フォント (TTC/TTF) が必要。既定は Noto Sans CJK のパス。
"""
import argparse
import json
import os
import re
import sys
import tempfile

from fpdf import FPDF
from fpdf.fonts import FontFace

DEFAULT_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
DEFAULT_FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

PAGE_W_MM = 210.0
MARGIN_MM = 20.0
CONTENT_W_MM = PAGE_W_MM - MARGIN_MM * 2  # 170mm
CHECK_INDENT_MM = 7.0
BOX_SIZE_MM = 4.4


def layout(src_path, tmp_pdf, font, font_bold):
    """1段目: レイアウトし、チェック欄の位置リストを返す。"""
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)
    pdf.set_auto_page_break(auto=True, margin=MARGIN_MM)
    pdf.add_font("doc", "", font)
    pdf.add_font("doc", "B", font_bold)
    pdf.add_page()
    boxes = []

    def rich(text, indent_mm=0):
        pdf.set_x(pdf.l_margin + indent_mm)
        pdf.multi_cell(CONTENT_W_MM - indent_mm, 7, text, markdown=True, align="L")

    lines = open(src_path, encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1
        if not line:
            pdf.ln(3)
            continue
        # 表（次の行が区切り行のときだけ表として扱う）
        if line.startswith("|") and i < len(lines) and re.match(r"^\|[\s\-\|:]+\|$", lines[i]):
            rows = [[c.strip() for c in line.strip().strip("|").split("|")]]
            i += 1
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            pdf.set_font("doc", "", 10.5)
            with pdf.table(text_align="LEFT") as table:
                for r, row in enumerate(rows):
                    tr = table.row()
                    for c in row:
                        tr.cell(c, style=FontFace(emphasis="BOLD") if r == 0 else None)
            pdf.ln(4)
            continue
        if line.startswith("### "):
            pdf.ln(2)
            pdf.set_font("doc", "B", 12)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 7.5, line[4:], align="L")
            pdf.ln(1)
        elif line.startswith("## "):
            pdf.ln(4)
            pdf.set_font("doc", "B", 13)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 8, line[3:], align="L")
            pdf.ln(1.5)
        elif line.startswith("# "):
            pdf.set_font("doc", "B", 16)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 10, line[2:], align="L")
            pdf.ln(3)
        elif re.match(r"^- \[[ x]\]\s", line):
            if pdf.get_y() > 268:  # 欄だけ前ページに残らないよう改ページ
                pdf.add_page()
            boxes.append({
                "page": pdf.page,
                "x_mm": MARGIN_MM,
                "y_mm": pdf.get_y() + 0.8,
                "checked": line[3] == "x",
            })
            pdf.set_font("doc", "", 11)
            rich(line[6:], indent_mm=CHECK_INDENT_MM)
        elif line.startswith("- "):
            pdf.set_font("doc", "", 11)
            rich("・" + line[2:])
        else:
            pdf.set_font("doc", "", 11)
            rich(line)

    pdf.output(tmp_pdf)
    return boxes


def embed_checkboxes(tmp_pdf, boxes, out_path):
    """2段目: 記録した位置に AcroForm チェックボックスを差し込む。"""
    import fitz

    mm = 72 / 25.4
    doc = fitz.open(tmp_pdf)
    for n, b in enumerate(boxes, 1):
        page = doc[b["page"] - 1]
        x, y, s = b["x_mm"] * mm, b["y_mm"] * mm, BOX_SIZE_MM * mm
        w = fitz.Widget()
        w.field_name = f"task{n}"
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w.rect = fitz.Rect(x, y, x + s, y + s)
        w.field_value = b["checked"]
        w.border_width = 1.0
        w.border_color = (0, 0, 0)   # これと fill_color を欠くと枠が描画されない
        w.fill_color = (1, 1, 1)
        w.text_color = (0, 0, 0)
        page.add_widget(w)
        w.update()
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()


def main():
    ap = argparse.ArgumentParser(description="Markdownチェックリスト → 押せる欄つきPDF")
    ap.add_argument("input", help="入力 Markdown")
    ap.add_argument("output", help="出力 PDF")
    ap.add_argument("--font", default=DEFAULT_FONT, help="本文フォント (TTC/TTF)")
    ap.add_argument("--font-bold", default=DEFAULT_FONT_BOLD, help="太字フォント (TTC/TTF)")
    args = ap.parse_args()

    for p in (args.font, args.font_bold):
        if not os.path.exists(p):
            sys.exit(f"フォントが見つかりません: {p} (--font / --font-bold で指定してください)")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_pdf = tmp.name
    try:
        boxes = layout(args.input, tmp_pdf, args.font, args.font_bold)
        embed_checkboxes(tmp_pdf, boxes, args.output)
    finally:
        os.unlink(tmp_pdf)
    print(f"OK: {args.output} ({len(boxes)} checkboxes)")


if __name__ == "__main__":
    main()
