"""Logging operacional: nunca incluir texto de PDF, JSON extraído ou identificadores de partes."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("tcc_pjecalc")
