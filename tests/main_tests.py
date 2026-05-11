#!/usr/bin/env python3
"""
main_tests.py — Ejecutor Central de Validaciones por Fase del ETL Solar
=========================================================================
Ejecuta toda la suite de tests organizados por fases del PRD.

Uso:
    python tests/main_tests.py               # Ejecutar todos los tests unitarios
    python tests/main_tests.py --integration  # Incluir tests de integración (requiere Internet)
    python tests/main_tests.py --verbose      # Output detallado con nombres de test
    python tests/main_tests.py --phase 1.2    # Solo una fase específica

Fases validadas:
    1.2 — Ingesta: Patrón Factory con fallback (ExtractionFactory)
    2.1 — Transformación: Carga lazy, alineamiento temporal, tipado estricto
    2.2 — Limpieza: Patrón Strategy (Nighttime, Hampel, MissingValue)
    2.3 — Exportación: Enforcement de tipos, serialización Parquet a GCS
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# ── Rutas ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"

# ── Mapeo de fases a módulos de test ──────────────────────────────────
PHASE_MAP: dict[str, dict[str, str]] = {
    "1.2": {
        "label": "Fase 1.2 — Ingesta con Patrón Factory",
        "module": "tests/test_phase_1_2_extraction.py",
    },
    "2.1": {
        "label": "Fase 2.1 — Carga Lazy y Alineamiento Temporal",
        "module": "tests/test_phase_2_1_transformation.py",
    },
    "2.2": {
        "label": "Fase 2.2 — Patrón Strategy de Limpieza",
        "module": "tests/test_phase_2_2_cleaning.py",
    },
    "2.3": {
        "label": "Fase 2.3 — Data Types y Export Parquet a GCS",
        "module": "tests/test_phase_2_3_export.py",
    },
}


def _build_pytest_args(
    *,
    module_path: str | None = None,
    verbose: bool = False,
    include_integration: bool = False,
) -> list[str]:
    """Construye los argumentos para invocar pytest.

    Parameters
    ----------
    module_path : str | None
        Ruta relativa al módulo de test (None = todos).
    verbose : bool
        Si True, agrega -v para output detallado.
    include_integration : bool
        Si True, incluye tests marcados con @pytest.mark.integration.

    Returns
    -------
    list[str]
        Lista de argumentos para subprocess.
    """
    args = [
        sys.executable, "-m", "pytest",
        "--tb=short",
        "--no-header",
        "-q" if not verbose else "-v",
    ]

    if not include_integration:
        args.extend(["-m", "not integration and not slow"])

    if module_path:
        args.append(module_path)
    else:
        args.append(str(TESTS_DIR))

    return args


def _print_banner(title: str) -> None:
    """Imprime un banner visual para separar fases."""
    width = 70
    print()
    print("═" * width)
    print(f"  {title}")
    print("═" * width)


def _print_summary(results: dict[str, dict]) -> None:
    """Imprime el resumen final de todas las fases."""
    width = 70
    print()
    print("═" * width)
    print("  📊 RESUMEN FINAL — Validación por Fases del ETL Solar")
    print("═" * width)

    all_passed = True
    total_time = 0.0

    for phase_id, result in results.items():
        status = "✅ PASSED" if result["passed"] else "❌ FAILED"
        elapsed = result.get("elapsed", 0.0)
        total_time += elapsed

        label = PHASE_MAP[phase_id]["label"]
        print(f"  {status}  {label}  ({elapsed:.1f}s)")

        if not result["passed"]:
            all_passed = False

    print("─" * width)
    print(f"  ⏱  Tiempo total: {total_time:.1f}s")

    if all_passed:
        print()
        print("  🎉 TODAS LAS FASES IMPLEMENTADAS PASARON LA VALIDACIÓN")
    else:
        print()
        print("  ⚠️  ALGUNAS FASES FALLARON — Revisar output arriba")

    print("═" * width)
    print()


def run_phase(
    phase_id: str,
    *,
    verbose: bool = False,
    include_integration: bool = False,
) -> dict:
    """Ejecuta los tests de una fase específica.

    Parameters
    ----------
    phase_id : str
        Identificador de fase (ej. "1.2", "2.1").
    verbose : bool
        Output detallado.
    include_integration : bool
        Incluir tests de integración.

    Returns
    -------
    dict
        Resultado con claves: passed (bool), elapsed (float), returncode (int).
    """
    phase_info = PHASE_MAP[phase_id]
    _print_banner(f"🔬 {phase_info['label']}")

    args = _build_pytest_args(
        module_path=phase_info["module"],
        verbose=verbose,
        include_integration=include_integration,
    )

    start = time.monotonic()
    proc = subprocess.run(args, cwd=str(PROJECT_ROOT))
    elapsed = time.monotonic() - start

    return {
        "passed": proc.returncode == 0,
        "elapsed": round(elapsed, 1),
        "returncode": proc.returncode,
    }


def main() -> int:
    """Punto de entrada principal.

    Returns
    -------
    int
        0 si todos los tests pasaron, 1 si hubo fallos.
    """
    parser = argparse.ArgumentParser(
        description="Ejecutor de validaciones por fase del ETL Solar PVOD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python tests/main_tests.py                    # Todos los tests unitarios
  python tests/main_tests.py --verbose          # Output detallado
  python tests/main_tests.py --phase 2.1        # Solo Fase 2.1
  python tests/main_tests.py --integration      # Incluir tests de integración
  python tests/main_tests.py --phase 1.2 --integration  # Fase 1.2 con integración
        """,
    )

    parser.add_argument(
        "--phase",
        choices=list(PHASE_MAP.keys()),
        help="Ejecutar solo una fase específica (ej. 1.2, 2.1, 2.2, 2.3)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Output detallado con nombres de test",
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Incluir tests de integración (requieren conexión a Internet)",
    )

    args = parser.parse_args()

    # ── Header ────────────────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║     🔆 ETL SOLAR PVOD — Suite de Validación por Fases          ║")
    print("║     Photovoltaic Power Output Dataset                          ║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    if args.integration:
        print("  ℹ️  Modo: Incluye tests de integración (requiere Internet)")
    else:
        print("  ℹ️  Modo: Solo tests unitarios (sin conexión HTTP)")

    # ── Seleccionar fases a ejecutar ──────────────────────────────────
    phases_to_run = [args.phase] if args.phase else list(PHASE_MAP.keys())

    results: dict[str, dict] = {}

    for phase_id in phases_to_run:
        results[phase_id] = run_phase(
            phase_id,
            verbose=args.verbose,
            include_integration=args.integration,
        )

    # ── Resumen ───────────────────────────────────────────────────────
    _print_summary(results)

    all_passed = all(r["passed"] for r in results.values())
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
