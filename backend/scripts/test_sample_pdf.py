"""Envia o PDF de exemplo para a API local e imprime o resultado."""

import json
import sys
from pathlib import Path

import httpx

PDF = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "processo_exemplo.pdf"
API = "http://127.0.0.1:8765"


def main() -> int:
    if not PDF.exists():
        print(f"PDF não encontrado: {PDF}")
        return 1

    with PDF.open("rb") as handle:
        response = httpx.post(
            f"{API}/api/v1/jobs",
            files={"file": ("processo_exemplo.pdf", handle, "application/pdf")},
            timeout=600.0,
        )

    print("POST /jobs status:", response.status_code)
    if response.status_code != 200:
        print(response.text)
        return 1

    created = response.json()
    print("message:", created.get("message"))
    job_id = created["job_id"]

    preview = httpx.get(f"{API}/api/v1/jobs/{job_id}/preview", timeout=30.0)
    print("GET /preview status:", preview.status_code)
    if preview.status_code != 200:
        print(preview.text)
        return 1

    extraction = preview.json()["extraction"]
    summary = {
        "pdf_page_count": extraction["pdf_page_count"],
        "candidate_page_count": extraction["candidate_page_count"],
        "gemini_call_count": extraction["gemini_call_count"],
        "classifications": extraction["classifications"],
        "time_cards_count": len(extraction["time_cards"]),
        "payslips_count": len(extraction["payslips"]),
        "unclassified_candidate_pages": extraction["unclassified_candidate_pages"],
        "missing_fields": extraction["missing_fields"][:5],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if extraction["time_cards"]:
        print("\nPrimeiro cartão de ponto:")
        print(json.dumps(extraction["time_cards"][0], indent=2, ensure_ascii=False))
    if extraction["payslips"]:
        print("\nPrimeiro holerite:")
        print(json.dumps(extraction["payslips"][0], indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
