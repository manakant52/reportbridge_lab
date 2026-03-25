from pathlib import Path


PAGE_WIDTH = 595
PAGE_HEIGHT = 842


def esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_block(lines, x, y, font="F1", size=12, leading=16):
    parts = ["BT", f"/{font} {size} Tf", f"{x} {y} Td", f"{leading} TL"]
    for index, line in enumerate(lines):
        if index:
            parts.append("T*")
        parts.append(f"({esc(line)}) Tj")
    parts.append("ET")
    return "\n".join(parts)


def page_stream(commands):
    return "\n".join(commands) + "\n"


def build_pdf(streams):
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{idx} 0 R' for idx in range(3, 3 + len(streams) * 2, 2))}] /Count {len(streams)} >>",
    ]

    next_object_id = 3
    for stream in streams:
        content_id = next_object_id + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {3 + len(streams) * 2} 0 R /F2 {4 + len(streams) * 2} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}endstream")
        next_object_id += 2

    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    objects.append(
        "<< /Title (DevOps Migration Exercise) /Author (ReportBridge Platform Team) "
        "/Subject (Edge migration review pack) "
        "/Keywords (status.reportbridge.test, edge-01, migration, reverse proxy, diagnostics) >>"
    )

    header = "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = ""
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len((header + body).encode("utf-8")))
        body += f"{idx} 0 obj\n{obj}\nendobj\n"
    xref_offset = len((header + body).encode("utf-8"))
    xref = [f"xref\n0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n")
    trailer = (
        "trailer\n"
        f"<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )
    return (header + body + "".join(xref) + trailer).encode("utf-8")


def make_streams():
    accent = "0.48 0.93 0.82 rg"
    muted = "0.68 0.78 0.82 rg"
    dark = "0.10 0.18 0.24 rg"
    stroke = "0.18 0.34 0.42 RG"

    page1 = [
        dark,
        "36 760 523 54 re f",
        accent,
        "36 744 523 4 re f",
        "1 1 1 rg",
        text_block(["DevOps Migration Exercise"], 52, 790, font="F2", size=24, leading=24),
        muted,
        text_block(["ReportBridge platform migration review workbook"], 52, 768, font="F1", size=11, leading=14),
        "0.80 0.90 0.94 rg",
        text_block(
            [
                "Context",
                "ReportBridge is moving parts of its public edge stack into a refreshed cloud environment.",
                "The platform team wants candidates to review the migration plan and identify the riskiest",
                "operational gaps before final cutover.",
            ],
            52,
            700,
            font="F2",
            size=13,
            leading=18,
        ),
        "0.86 0.92 0.95 rg",
        text_block(
            [
                "Scope for review",
                "- reverse proxy cutover and upstream health visibility",
                "- migration aliases and temporary artifact exposure",
                "- service status communication for external customers",
                "- post-change validation and rollback signals",
            ],
            52,
            640,
            font="F1",
            size=12,
            leading=18,
        ),
        stroke,
        "52 520 491 118 re S",
        accent,
        text_block(["Migration notes"], 66, 622, font="F2", size=14, leading=18),
        "0.90 0.94 0.96 rg",
        text_block(
            [
                "1. Confirm that the public status page reflects the new edge routing before cleanup.",
                "2. Remove temporary aliases only after validating customer-facing checks.",
                "3. Archive diagnostic outputs and migration artifacts after sign-off.",
                "",
                "Reference host: status.reportbridge.test",
                "Reference edge node: edge-01",
            ],
            66,
            596,
            font="F1",
            size=11,
            leading=16,
        ),
        "0.70 0.79 0.83 rg",
        text_block(
            [
                "Hiring signal",
                "Candidates should submit a short note describing what they would verify first",
                "on the external edge before declaring the migration complete.",
            ],
            52,
            470,
            font="F1",
            size=11,
            leading=16,
        ),
        "0.48 0.93 0.82 rg",
        text_block(["ReportBridge Platform Team"], 52, 96, font="F2", size=13, leading=16),
        "0.72 0.81 0.85 rg",
        text_block(["Prepared for technical screening, March 2026"], 52, 76, font="F1", size=10, leading=14),
    ]

    page2 = [
        dark,
        "36 760 523 54 re f",
        accent,
        "36 744 523 4 re f",
        "1 1 1 rg",
        text_block(["Reviewer prompts"], 52, 790, font="F2", size=24, leading=24),
        muted,
        text_block(["Use these questions to structure your response."], 52, 768, font="F1", size=11, leading=14),
        "0.88 0.93 0.96 rg",
        text_block(
            [
                "Operational prompts",
                "1. Which public endpoint should be checked first after the cutover?",
                "2. Which temporary migration materials must be removed from the edge?",
                "3. What would you log during the first 24 hours after deployment?",
                "4. Which customer-facing signal should remain available during rollout?",
            ],
            52,
            700,
            font="F1",
            size=12,
            leading=18,
        ),
        stroke,
        "52 486 491 154 re S",
        accent,
        text_block(["Expected reviewer conclusion"], 66, 622, font="F2", size=14, leading=18),
        "0.90 0.94 0.96 rg",
        text_block(
            [
                "The external status service must be validated first, because it exposes the",
                "customer-visible signal path during migration. Temporary artifact aliases and",
                "diagnostic endpoints should be considered high-risk leftovers until explicitly removed.",
                "",
                "Suggested review target: status.reportbridge.test",
                "Associated edge context: edge-01 reverse proxy cutover",
            ],
            66,
            596,
            font="F1",
            size=11,
            leading=16,
        ),
        "0.72 0.81 0.85 rg",
        text_block(["Confidentiality: internal hiring pack for technical assessment only."], 52, 90, font="F1", size=10, leading=14),
    ]

    return [page_stream(page1), page_stream(page2)]


if __name__ == "__main__":
    pdf_path = Path("/home/manakant/reportbridge_site/assets/DevOps_Migration_Exercise.pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(build_pdf(make_streams()))
