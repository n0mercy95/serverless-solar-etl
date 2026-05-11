"""
test_phase_1_2_extraction.py — Validación de Fase 1.2: Ingesta con Patrón Factory
====================================================================================
Valida la implementación del Patrón Factory para la extracción del dataset PVOD:

✅ Contratos ABC correctamente definidos (PVODExtractionPipeline)
✅ Implementaciones concretas (GitHubRawExtractor, ScienceDBHttpExtractor)
✅ ExtractionFactory con cadena de fallback automático
✅ Descarga real desde GitHub Raw (test de integración)
✅ Manejo de errores con jerarquía de excepciones del dominio

Referencia PRD §3 — Patrón Factory (Ingesta) y §6 — Tarea 1.2.
"""

from __future__ import annotations

import io
import sys
from abc import ABC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Resolver imports ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.application.extraction_factory import ExtractionFactory
from app.application.ports import PVODExtractionPipeline
from app.domain.exceptions import (
    DataExtractionError,
    DataSourceUnavailableError,
    DataValidationError,
    SolarETLError,
)
from app.infrastructure.github_extractor import GitHubRawExtractor
from app.infrastructure.sciencedb_extractor import ScienceDBHttpExtractor


# ══════════════════════════════════════════════════════════════════════
# 1. CONTRATOS ABC — Puerto de Extracción
# ══════════════════════════════════════════════════════════════════════

class TestExtractionPort:
    """Verifica que el contrato PVODExtractionPipeline cumple el PRD."""

    def test_is_abstract_class(self):
        """PVODExtractionPipeline debe ser una clase abstracta (ABC)."""
        assert issubclass(PVODExtractionPipeline, ABC)

    def test_cannot_instantiate_directly(self):
        """No se puede instanciar el puerto abstracto directamente."""
        with pytest.raises(TypeError):
            PVODExtractionPipeline()

    def test_has_extract_data_to_buffer_method(self):
        """El contrato debe definir el método extract_data_to_buffer."""
        assert hasattr(PVODExtractionPipeline, "extract_data_to_buffer")

    def test_extract_returns_bytes_io_annotation(self):
        """El tipo de retorno anotado debe ser io.BytesIO."""
        import inspect
        sig = inspect.signature(PVODExtractionPipeline.extract_data_to_buffer)
        # Con `from __future__ import annotations`, la anotación es un string
        annotation = sig.return_annotation
        assert annotation == io.BytesIO or annotation == "io.BytesIO"


# ══════════════════════════════════════════════════════════════════════
# 2. IMPLEMENTACIONES CONCRETAS — Extractores
# ══════════════════════════════════════════════════════════════════════

class TestGitHubRawExtractor:
    """Verifica la implementación GitHubRawExtractor."""

    def test_implements_abc_contract(self):
        """GitHubRawExtractor debe implementar PVODExtractionPipeline."""
        assert issubclass(GitHubRawExtractor, PVODExtractionPipeline)

    def test_can_instantiate_with_url(self):
        """Se puede instanciar con una URL fuente."""
        extractor = GitHubRawExtractor(source_url="https://example.com/data.csv")
        assert extractor is not None

    def test_stores_source_url(self):
        """El extractor almacena la URL correctamente."""
        url = "https://raw.githubusercontent.com/test/data.csv"
        extractor = GitHubRawExtractor(source_url=url)
        assert extractor._source_url == url

    def test_raises_on_invalid_url(self):
        """Debe lanzar DataSourceUnavailableError si la URL no responde."""
        extractor = GitHubRawExtractor(
            source_url="https://invalid-url-that-does-not-exist.example.com/data.csv",
            timeout=5,
        )
        with pytest.raises(DataSourceUnavailableError):
            extractor.extract_data_to_buffer()


class TestScienceDBHttpExtractor:
    """Verifica la implementación ScienceDBHttpExtractor."""

    def test_implements_abc_contract(self):
        """ScienceDBHttpExtractor debe implementar PVODExtractionPipeline."""
        assert issubclass(ScienceDBHttpExtractor, PVODExtractionPipeline)

    def test_can_instantiate_with_url(self):
        """Se puede instanciar con una URL fuente."""
        extractor = ScienceDBHttpExtractor(source_url="https://scidb.cn/api/data.csv")
        assert extractor is not None

    def test_higher_default_timeout(self):
        """ScienceDB debe tener un timeout mayor (fuente más lenta)."""
        extractor = ScienceDBHttpExtractor(source_url="https://example.com")
        assert extractor._timeout >= 180


# ══════════════════════════════════════════════════════════════════════
# 3. EXTRACTION FACTORY — Patrón Factory con Fallback
# ══════════════════════════════════════════════════════════════════════

class TestExtractionFactory:
    """Valida el Patrón Factory (PRD §3) y su cadena de fallback."""

    def test_build_extractor_chain_returns_sequence(self, mock_settings):
        """La cadena debe contener exactamente 2 extractores."""
        factory = ExtractionFactory(settings=mock_settings)
        chain = factory._build_extractor_chain()
        assert len(chain) == 2

    def test_chain_priority_order(self, mock_settings):
        """GitHub debe ser el primer extractor (prioridad), ScienceDB segundo."""
        factory = ExtractionFactory(settings=mock_settings)
        chain = factory._build_extractor_chain()
        assert isinstance(chain[0], GitHubRawExtractor)
        assert isinstance(chain[1], ScienceDBHttpExtractor)

    def test_create_extractor_returns_primary(self, mock_settings):
        """create_extractor() debe retornar el extractor primario (GitHub)."""
        factory = ExtractionFactory(settings=mock_settings)
        extractor = factory.create_extractor()
        assert isinstance(extractor, GitHubRawExtractor)

    def test_fallback_on_primary_failure(self, mock_settings):
        """Si GitHub falla, el factory debe caer al ScienceDB extractor."""
        factory = ExtractionFactory(settings=mock_settings)

        # Mock: GitHub falla, ScienceDB retorna un buffer
        fake_buffer = io.BytesIO(b"date_time,station_id\n2018-07-01 00:00,0\n")
        fake_buffer.seek(0)

        with patch.object(
            GitHubRawExtractor,
            "extract_data_to_buffer",
            side_effect=DataExtractionError("GitHub down"),
        ), patch.object(
            ScienceDBHttpExtractor,
            "extract_data_to_buffer",
            return_value=fake_buffer,
        ):
            buffer = factory.extract_with_fallback()
            assert isinstance(buffer, io.BytesIO)
            assert buffer.read() == b"date_time,station_id\n2018-07-01 00:00,0\n"

    def test_raises_when_all_sources_fail(self, mock_settings):
        """Si todas las fuentes fallan, debe propagar DataSourceUnavailableError."""
        factory = ExtractionFactory(settings=mock_settings)

        with patch.object(
            GitHubRawExtractor,
            "extract_data_to_buffer",
            side_effect=DataExtractionError("GitHub down"),
        ), patch.object(
            ScienceDBHttpExtractor,
            "extract_data_to_buffer",
            side_effect=DataExtractionError("ScienceDB down"),
        ):
            with pytest.raises(DataSourceUnavailableError):
                factory.extract_with_fallback()


# ══════════════════════════════════════════════════════════════════════
# 4. JERARQUÍA DE EXCEPCIONES — Dominio
# ══════════════════════════════════════════════════════════════════════

class TestExceptionHierarchy:
    """Valida la jerarquía de excepciones exigida por el PRD §5."""

    def test_base_exception_exists(self):
        """SolarETLError es la excepción base del pipeline."""
        assert issubclass(SolarETLError, Exception)

    def test_extraction_error_hierarchy(self):
        """DataExtractionError hereda de SolarETLError."""
        assert issubclass(DataExtractionError, SolarETLError)

    def test_source_unavailable_hierarchy(self):
        """DataSourceUnavailableError hereda de DataExtractionError."""
        assert issubclass(DataSourceUnavailableError, DataExtractionError)

    def test_validation_error_hierarchy(self):
        """DataValidationError hereda de SolarETLError."""
        assert issubclass(DataValidationError, SolarETLError)

    def test_can_catch_all_with_base(self):
        """Todas las excepciones del dominio se pueden atrapar con SolarETLError."""
        for ExcClass in (DataExtractionError, DataSourceUnavailableError, DataValidationError):
            try:
                raise ExcClass("test")
            except SolarETLError:
                pass  # OK: se atrapó correctamente


# ══════════════════════════════════════════════════════════════════════
# 5. TEST DE INTEGRACIÓN — Extracción Real desde GitHub Raw
# ══════════════════════════════════════════════════════════════════════

class TestGitHubRawIntegration:
    """Test de integración: descarga real desde GitHub Raw.

    Este test conecta a Internet y descarga el CSV PVOD real.
    Se marca con @pytest.mark.integration para poder filtrarlo.
    """

    @pytest.mark.integration
    @pytest.mark.slow
    def test_real_extraction_returns_valid_buffer(self):
        """La descarga real desde GitHub Raw produce un buffer válido."""
        url = (
            "https://raw.githubusercontent.com/n0mercy95/serverless-solar-etl/"
            "refs/heads/data/upload-pvod-dataset/data/pvod.csv"
        )
        extractor = GitHubRawExtractor(source_url=url)
        buffer = extractor.extract_data_to_buffer()

        assert isinstance(buffer, io.BytesIO)
        content = buffer.getvalue()
        assert len(content) > 0

        # Verificar que es un CSV con el header esperado
        first_line = content.split(b"\n")[0].decode("utf-8")
        assert "date_time" in first_line
        assert "station_id" in first_line

    @pytest.mark.integration
    @pytest.mark.slow
    def test_real_extraction_with_factory_fallback(self):
        """El ExtractionFactory extrae exitosamente con fallback automático."""
        # Usar mock settings con URL real de GitHub
        settings = MagicMock()
        settings.github_raw_url = (
            "https://raw.githubusercontent.com/n0mercy95/serverless-solar-etl/"
            "refs/heads/data/upload-pvod-dataset/data/pvod.csv"
        )
        settings.scidb_fallback_url = "https://scidb.cn/api/v1/dataset/pvod.csv"

        factory = ExtractionFactory(settings=settings)
        buffer = factory.extract_with_fallback()

        assert isinstance(buffer, io.BytesIO)
        assert buffer.getbuffer().nbytes > 1_000_000  # >1 MB (dataset completo)
