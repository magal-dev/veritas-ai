from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from api.deps import get_job_service
from schemas.jobs import (
    ExtractionUpdateRequest,
    JobCreated,
    JobPreviewResponse,
    JobStatus,
    JobStatusResponse,
)
from services.job_service import JobError, JobService
from services.session_store import JobSession

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

ERROR_MESSAGES = {
    "INVALID_FILE_TYPE": "Envie um arquivo PDF.",
    "FILE_TOO_LARGE": "O PDF excede o tamanho máximo permitido.",
    "EMPTY_FILE": "O arquivo enviado está vazio.",
    "PIPELINE_ERROR": "Falha ao processar o PDF. Tente outro arquivo.",
    "SESSION_LIMIT": "Há sessões demais em memória. Encerre uma revisão ou aguarde o prazo sem uso.",
}


def _require_session(session: JobSession | None) -> JobSession:
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": "Sessão inexistente, expirada ou já descartada. Envie o PDF novamente.",
            },
        )
    return session


def _http_from_job(exc: JobError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error_code": exc.error_code,
            "message": ERROR_MESSAGES.get(exc.error_code, "Falha ao processar."),
        },
    )


@router.post("", response_model=JobCreated)
async def create_job(
    file: UploadFile = File(..., description="PDF do processo — não é armazenado"),
    service: JobService = Depends(get_job_service),
) -> JobCreated:
    try:
        session = await service.create_from_upload(file)
    except JobError as exc:
        raise _http_from_job(exc) from exc

    page_count = session.extraction.pdf_page_count if session.extraction else 0
    return JobCreated(
        job_id=session.job_id,
        status=session.status,
        pdf_page_count=page_count,
        message=(
            "PDF processado e descartado do servidor. "
            "Revise os dados extraídos antes de baixar os arquivos do PJe-Calc."
        ),
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: UUID,
    service: JobService = Depends(get_job_service),
) -> JobStatusResponse:
    session = _require_session(service.get(job_id))
    extraction = session.extraction
    return JobStatusResponse(
        job_id=session.job_id,
        status=session.status,
        pdf_page_count=extraction.pdf_page_count if extraction else 0,
        candidate_page_count=extraction.candidate_page_count if extraction else 0,
        gemini_call_count=extraction.gemini_call_count if extraction else 0,
        created_at=session.created_at,
        error_code=session.error_code,
        pipeline_note=session.pipeline_note,
    )


@router.get("/{job_id}/preview", response_model=JobPreviewResponse)
async def preview_job(
    job_id: UUID,
    service: JobService = Depends(get_job_service),
) -> JobPreviewResponse:
    session = _require_session(service.get(job_id))
    if session.extraction is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "EXTRACTION_MISSING",
                "message": "A sessão não possui JSON extraído.",
            },
        )
    return JobPreviewResponse(
        job_id=session.job_id,
        status=session.status,
        extraction=session.extraction,
    )


@router.patch("/{job_id}/extraction", response_model=JobPreviewResponse)
async def update_job_extraction(
    job_id: UUID,
    body: ExtractionUpdateRequest,
    service: JobService = Depends(get_job_service),
) -> JobPreviewResponse:
    session = _require_session(service.get(job_id))
    if session.extraction is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "EXTRACTION_MISSING",
                "message": "A sessão não possui JSON extraído.",
            },
        )
    updated = service.update_extraction(job_id, body.time_cards, body.payslips, body.conflicts)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": "Sessão inexistente, expirada ou já descartada. Envie o PDF novamente.",
            },
        )
    return JobPreviewResponse(job_id=session.job_id, status=session.status, extraction=updated)


@router.get("/{job_id}/export")
async def download_export(
    job_id: UUID,
    service: JobService = Depends(get_job_service),
) -> Response:
    session = _require_session(service.get(job_id))
    if session.status != JobStatus.COMPLETED or session.extraction is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "NOT_READY",
                "message": "Os arquivos só são gerados após o processamento da sessão.",
            },
        )
    if session.extraction.conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "CONFLICTS_UNRESOLVED",
                "message": "Resolva os conflitos na revisão antes de gerar os arquivos.",
            },
        )
    payload = service.build_export(session)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="veritas-pjecalc.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{job_id}/crops/{crop_id}")
async def get_review_crop(
    job_id: UUID,
    crop_id: str,
    service: JobService = Depends(get_job_service),
) -> Response:
    """Recorte de uma célula do cartão para a revisão; vive só na sessão."""
    payload = service.review_crop(job_id, crop_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "CROP_NOT_FOUND",
                "message": "Recorte inexistente ou sessão expirada.",
            },
        )
    return Response(content=payload, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.delete("/{job_id}", status_code=204)
async def discard_job(
    job_id: UUID,
    service: JobService = Depends(get_job_service),
) -> None:
    removed = await service.discard(job_id)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": "Sessão inexistente ou já descartada.",
            },
        )
