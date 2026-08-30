"""Validação do JSON extraído contra o schema e regras mínimas de negócio."""

from __future__ import annotations

from schemas.extraction import ExtractionResult


class ExtractionValidator:
    def validate(self, result: ExtractionResult) -> ExtractionResult:
        raise NotImplementedError


class SchemaExtractionValidator(ExtractionValidator):
    """Revalida o modelo Pydantic. Regras de jornada/verbas entram em iterações futuras."""

    def validate(self, result: ExtractionResult) -> ExtractionResult:
        return ExtractionResult.model_validate(result.model_dump())
