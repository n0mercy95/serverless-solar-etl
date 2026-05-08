"""
consolidate_pvod.py — Pre-procesamiento Off-line del Dataset PVOD
=================================================================
Consolida los 10 archivos CSV originales (station00..station09) en un
único archivo maestro ``data/pvod.csv``, añadiendo la columna
``station_id`` requerida para el clustering en BigQuery según el PRD.

Uso:
    python scripts/consolidate_pvod.py [--source-dir RUTA]

Por defecto lee desde ~/Downloads (donde se descomprime el ZIP).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

# ─── Constantes ───────────────────────────────────────────────────────
EXPECTED_RECORDS = 271_968
NUM_STATIONS = 10
OUTPUT_FILENAME = "pvod.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Consolida station00..09.csv en un único pvod.csv maestro.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path.home() / "Downloads",
        help="Directorio donde residen los station0X.csv (default: ~/Downloads)",
    )
    return parser


def consolidate(source_dir: Path, output_path: Path) -> pl.DataFrame:
    """Lee los 10 CSV, añade ``station_id`` y retorna el DataFrame unificado."""
    frames: list[pl.DataFrame] = []

    for station_id in range(NUM_STATIONS):
        csv_path = source_dir / f"station{station_id:02d}.csv"
        if not csv_path.exists():
            print(f"❌  Archivo no encontrado: {csv_path}")
            sys.exit(1)

        df = pl.read_csv(csv_path)
        # Homogeneizar tipos: promover Int64 → Float64 para evitar
        # SchemaError al concatenar estaciones con tipos dispares.
        int_cols = [c for c, t in zip(df.columns, df.dtypes) if t == pl.Int64]
        if int_cols:
            df = df.with_columns([pl.col(c).cast(pl.Float64) for c in int_cols])
        df = df.with_columns(
            pl.lit(station_id).cast(pl.UInt8).alias("station_id"),
        )
        print(f"  ✔ station{station_id:02d}.csv  →  {df.height:>6,} registros")
        frames.append(df)

    master = pl.concat(frames)
    return master


def validate(df: pl.DataFrame) -> None:
    """Aborta si la cantidad de registros no coincide con lo estipulado en el PRD."""
    actual = df.height
    if actual != EXPECTED_RECORDS:
        print(
            f"\n❌  Validación fallida: se esperaban {EXPECTED_RECORDS:,} registros, "
            f"pero se encontraron {actual:,}.",
        )
        sys.exit(1)
    print(f"\n✅  Validación exitosa: {actual:,} registros (OK)")


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(__file__).resolve().parent.parent
    output_path = project_root / "data" / OUTPUT_FILENAME

    print("=" * 60)
    print("  PVOD Dataset — Consolidación Off-line")
    print("=" * 60)
    print(f"  Fuente  : {args.source_dir}")
    print(f"  Destino : {output_path}\n")

    master = consolidate(args.source_dir, output_path)
    validate(master)

    # ─── Exportar ─────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    master.write_csv(output_path)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"📦  Archivo maestro exportado: {output_path}  ({size_mb:.1f} MB)")

    # ─── Resumen rápido ──────────────────────────────────────────
    print("\n── Vista previa (primeras 5 filas) ──")
    print(master.head())
    print("\n── Distribución por estación ──")
    print(
        master.group_by("station_id")
        .agg(pl.len().alias("registros"))
        .sort("station_id"),
    )
    print("\n🏁  Consolidación completada exitosamente.")


if __name__ == "__main__":
    main()
