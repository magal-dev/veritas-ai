from io import BytesIO
from uuid import uuid4

import fitz
from fastapi.testclient import TestClient

from main import app
from pipeline.extractor import LocalDocumentExtractor
from schemas.extraction import ExtractionResult
from pipeline.validator import SchemaExtractionValidator


def _pdf_bytes(pages: int = 3) -> bytes:
    document = fitz.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"Pagina {index + 1}")
    payload = document.tobytes()
    document.close()
    return payload


def test_health_reports_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_job_flow_counts_pages_and_returns_empty_extraction(tmp_path):
    pdf_path = tmp_path / "processo.pdf"
    pdf_path.write_bytes(_pdf_bytes(4))
    signals = LocalDocumentExtractor().extract(pdf_path)
    assert signals.pdf_page_count == 4
    assert signals.candidate_pages == []

    client = TestClient(app)
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("processo.pdf", BytesIO(_pdf_bytes(4)), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    assert response.json()["pdf_page_count"] == 4

    preview = client.get(f"/api/v1/jobs/{job_id}/preview")
    assert preview.status_code == 200
    extraction = preview.json()["extraction"]
    assert extraction["time_cards"] == []
    assert extraction["payslips"] == []
    assert extraction["gemini_call_count"] == 0

    excel = client.get(f"/api/v1/jobs/{job_id}/excel")
    assert excel.status_code == 200
    assert excel.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    discarded = client.delete(f"/api/v1/jobs/{job_id}")
    assert discarded.status_code == 204
    missing = client.get(f"/api/v1/jobs/{job_id}")
    assert missing.status_code == 404


def test_rejects_non_pdf():
    client = TestClient(app)
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("notas.txt", b"nao e pdf", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "INVALID_FILE_TYPE"


def test_empty_result_schema_roundtrip():
    result = ExtractionResult(job_id=uuid4())
    validated = SchemaExtractionValidator().validate(result)
    assert validated.schema_version == "extraction-schema-0.1"
