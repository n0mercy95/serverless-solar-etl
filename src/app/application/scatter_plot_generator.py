"""
application/scatter_plot_generator.py — Generador de Scatter Plots NWP vs LMD
==============================================================================
Genera gráficos de dispersión (scatter plots) comparando la irradiancia
predicha por el modelo meteorológico (NWP) contra la medición local (LMD),
tanto antes como después del pipeline de limpieza.

Los gráficos se guardan localmente en un directorio temporal y luego se
suben al bucket GCS en el prefijo ``plots/``.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Backend sin GUI para entornos serverless

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402
from google.cloud import storage  # noqa: E402

logger = logging.getLogger(__name__)

# ── Prefijo GCS para los plots ────────────────────────────────────────
GCS_PLOTS_PREFIX: str = "plots/"


class ScatterPlotGenerator:
    """Genera y sube scatter plots de irradiancia NWP vs LMD a GCS.

    Parameters
    ----------
    bucket_name : str
        Nombre del bucket GCS (sin prefijo ``gs://``).
    credentials_path : str | None, optional
        Ruta al archivo JSON de credenciales de servicio.
        Si es ``None``, usa Application Default Credentials (ADC).
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        credentials_path: str | None = None,
    ) -> None:
        self._bucket_name = bucket_name
        self._credentials_path = credentials_path

    def generate_and_upload(
        self,
        df_pre: pl.DataFrame,
        df_post: pl.DataFrame,
        *,
        content_hash: str | None = None,
    ) -> list[str]:
        """Genera los scatter plots pre/post-cleaning y los sube a GCS.

        Limpia automáticamente gráficos anteriores en el prefijo configurado
        antes de subir los nuevos, para evitar acumular un historial infinito.

        Parameters
        ----------
        df_pre : pl.DataFrame
            DataFrame antes de la limpieza.
        df_post : pl.DataFrame
            DataFrame después de la limpieza (Gold).
        content_hash : str | None, optional
            Hash de contenido para nombres únicos de archivos.

        Returns
        -------
        list[str]
            Lista de URIs GCS de los plots subidos.
        """
        self._cleanup_old_plots()

        uploaded_uris: list[str] = []
        timestamp_suffix = self._build_suffix(content_hash)

        # ── Generar ambos plots ───────────────────────────────────────
        plots_config = [
            ("Pre-Cleaning", df_pre, f"scatter_pre_cleaning_{timestamp_suffix}.png"),
            ("Post-Cleaning (Gold)", df_post, f"scatter_post_cleaning_{timestamp_suffix}.png"),
        ]

        for title, df, filename in plots_config:
            try:
                local_path = self._create_scatter_plot(df, title)
                gcs_uri = self._upload_to_gcs(local_path, f"{GCS_PLOTS_PREFIX}{filename}")
                uploaded_uris.append(gcs_uri)

                logger.info(
                    f"Scatter plot '{title}' subido a GCS",
                    extra={
                        "attributes": {
                            "gcs_uri": gcs_uri,
                            "phase": title,
                        },
                    },
                )
            except Exception as exc:
                # Los plots son observabilidad, no deben romper el pipeline
                logger.warning(
                    f"No se pudo generar/subir scatter plot '{title}': {exc}",
                    exc_info=exc,
                )
            finally:
                plt.close("all")

        # ── Generar plots de perfil diurno ─────────────
        for title, df, prefix in [
            ("Pre-Cleaning", df_pre, "diurnal_power_profile_pre"),
            ("Post-Cleaning (Gold)", df_post, "diurnal_power_profile_post"),
        ]:
            try:
                diurnal_filename = f"{prefix}_{timestamp_suffix}.png"
                local_path = self._create_diurnal_power_plot(df, title)
                gcs_uri = self._upload_to_gcs(local_path, f"{GCS_PLOTS_PREFIX}{diurnal_filename}")
                uploaded_uris.append(gcs_uri)

                logger.info(
                    f"Diurnal power plot '{title}' subido a GCS",
                    extra={
                        "attributes": {
                            "gcs_uri": gcs_uri,
                            "phase": title,
                        },
                    },
                )
            except Exception as exc:
                logger.warning(
                    f"No se pudo generar/subir diurnal power plot '{title}': {exc}",
                    exc_info=exc,
                )
            finally:
                plt.close("all")

        return uploaded_uris

    # ── Métodos Internos ──────────────────────────────────────────────

    def _cleanup_old_plots(self) -> None:
        """Borra todos los archivos existentes en el prefijo `plots/` de GCS."""
        try:
            client = (
                storage.Client.from_service_account_json(self._credentials_path)
                if self._credentials_path
                else storage.Client()
            )
            bucket = client.bucket(self._bucket_name)
            blobs = list(bucket.list_blobs(prefix=GCS_PLOTS_PREFIX))
            
            if blobs:
                bucket.delete_blobs(blobs)
                logger.info(
                    f"Limpieza GCS: se borraron {len(blobs)} plots anteriores en '{GCS_PLOTS_PREFIX}'",
                    extra={
                        "attributes": {
                            "deleted_count": len(blobs),
                            "prefix": GCS_PLOTS_PREFIX,
                        },
                    },
                )
        except Exception as exc:
            logger.warning(
                f"No se pudieron limpiar los plots antiguos en GCS: {exc}",
                exc_info=exc,
            )

    @staticmethod
    def _create_scatter_plot(df: pl.DataFrame, phase_title: str) -> Path:
        """Crea un scatter plot NWP GHI vs LMD GHI y lo guarda como PNG.

        Parameters
        ----------
        df : pl.DataFrame
            DataFrame con columnas ``nwp_globalirrad`` y ``lmd_totalirrad``.
        phase_title : str
            Título de la fase para el gráfico ("Pre-Cleaning" o "Post-Cleaning (Gold)").

        Returns
        -------
        Path
            Ruta al archivo PNG temporal generado.
        """
        nwp_values = df["nwp_globalirrad"].to_numpy()
        lmd_values = df["lmd_totalirrad"].to_numpy()

        fig, ax = plt.subplots(figsize=(8, 7))

        ax.scatter(
            nwp_values,
            lmd_values,
            alpha=0.15,
            s=4,
            c="#4A90D9",
            edgecolors="none",
            rasterized=True,
        )

        # ── Línea de referencia 1:1 (predicción perfecta) ─────────
        max_val = max(nwp_values.max(), lmd_values.max())
        ax.plot(
            [0, max_val],
            [0, max_val],
            color="#E74C3C",
            linestyle="--",
            linewidth=1.2,
            alpha=0.8,
            label="Línea 1:1 (referencia)",
        )

        # ── Estilo del gráfico ─────────────────────────────────────
        ax.set_title(
            f"Irradiancia NWP vs LMD — {phase_title}",
            fontsize=14,
            fontweight="bold",
            pad=12,
        )
        ax.set_xlabel("NWP Global Irradiance (W/m²)", fontsize=11)
        ax.set_ylabel("LMD Total Irradiance (W/m²)", fontsize=11)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3, linestyle=":")

        # Estadísticas en una caja de texto
        n_points = len(nwp_values)
        stats_text = f"n = {n_points:,}"
        ax.text(
            0.97, 0.03,
            stats_text,
            transform=ax.transAxes,
            fontsize=9,
            verticalalignment="bottom",
            horizontalalignment="right",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
        )

        fig.tight_layout()

        # ── Guardar en archivo temporal ────────────────────────────
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png",
            prefix="scatter_irradiance_",
            delete=False,
        )
        tmp.close()
        output_path = Path(tmp.name)
        fig.savefig(output_path, dpi=150, bbox_inches="tight")

        logger.info(
            f"Scatter plot generado: {phase_title}",
            extra={
                "attributes": {
                    "path": str(output_path),
                    "size_kb": round(output_path.stat().st_size / 1024, 1),
                    "data_points": n_points,
                },
            },
        )

        return output_path

    @staticmethod
    def _create_diurnal_power_plot(df: pl.DataFrame, phase_title: str) -> Path:
        """Crea un gráfico de dispersión de potencia vs hora del día por estación.

        Usa escala logarítmica en el eje Y para hacer visibles los valores
        de ruido nocturno (del orden de 0.03-0.13 MW) que de otro modo
        serían invisibles frente al pico diurno (~30 MW).

        Parameters
        ----------
        df : pl.DataFrame
            DataFrame con columnas ``date_time``, ``station_id`` y ``power``.
        phase_title : str
            Título de la fase para el gráfico ("Pre-Cleaning" o "Post-Cleaning (Gold)").

        Returns
        -------
        Path
            Ruta al archivo PNG temporal generado.
        """
        import numpy as np

        # Calcular hora decimal para el eje X (ej. 14:30 -> 14.5)
        df_plot = df.with_columns(
            (pl.col("date_time").dt.hour() + pl.col("date_time").dt.minute() / 60.0).alias("hour_decimal")
        ).select(["hour_decimal", "power", "station_id"])

        fig, ax = plt.subplots(figsize=(10, 6))

        # Paleta de 10 colores distintivos para las 10 estaciones
        colors = plt.cm.tab10.colors

        # Agrupar por estación y graficar cada una
        for station_id in range(10):
            station_data = df_plot.filter(pl.col("station_id") == station_id)
            if station_data.height > 0:
                power_vals = station_data["power"].to_numpy()
                hour_vals = station_data["hour_decimal"].to_numpy()

                # Reemplazar 0.0 con NaN para que no aparezcan en escala log
                power_plot = np.where(power_vals > 0, power_vals, np.nan)

                ax.scatter(
                    hour_vals,
                    power_plot,
                    alpha=0.15,
                    s=3,
                    color=colors[station_id],
                    label=f"Station {station_id}",
                    rasterized=True,
                )

        # ── Escala logarítmica para revelar ruido nocturno ──────────
        ax.set_yscale("log")
        ax.set_ylim(0.001, 100)

        ax.set_title(
            f"Perfil Diurno de Potencia ({phase_title}) — Escala Log",
            fontsize=14,
            fontweight="bold",
            pad=12,
        )
        ax.set_xlabel("Hora del Día (0-24h)", fontsize=11)
        ax.set_ylabel("Power (MW) — Escala Logarítmica", fontsize=11)

        # Ajustar eje X para representar las 24 horas completas
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 2))

        # ── Anotación: contar registros con power > 0 de noche ─────
        # Definir "noche" como horas 0-5 y 19-24 (hora local)
        night_mask = (pl.col("hour_decimal") < 5.5) | (pl.col("hour_decimal") > 18.5)
        night_power_gt0 = df_plot.filter(night_mask & (pl.col("power") > 0.0)).height
        total_night = df_plot.filter(night_mask).height

        annotation = (
            f"Registros nocturnos con Power > 0:\n"
            f"  {night_power_gt0:,} de {total_night:,} ({night_power_gt0/max(total_night,1)*100:.1f}%)"
        )
        ax.text(
            0.02, 0.97,
            annotation,
            transform=ax.transAxes,
            fontsize=8,
            verticalalignment="top",
            horizontalalignment="left",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="lightyellow", edgecolor="orange", alpha=0.9),
        )

        # Usar marcadores con opacidad total en la leyenda
        leg = ax.legend(loc="upper right", markerscale=5, fontsize=8, ncol=2)
        for lh in leg.legend_handles:
            lh.set_alpha(1.0)

        ax.grid(True, alpha=0.3, linestyle=":")

        fig.tight_layout()

        tmp = tempfile.NamedTemporaryFile(
            suffix=".png",
            prefix="diurnal_power_profile_",
            delete=False,
        )
        tmp.close()
        output_path = Path(tmp.name)
        fig.savefig(output_path, dpi=150, bbox_inches="tight")

        logger.info(
            "Diurnal power plot generado",
            extra={
                "attributes": {
                    "path": str(output_path),
                    "size_kb": round(output_path.stat().st_size / 1024, 1),
                    "night_power_gt0": night_power_gt0,
                },
            },
        )

        return output_path

    @staticmethod
    def _build_suffix(content_hash: str | None) -> str:
        """Genera un sufijo único para el nombre del archivo."""
        if content_hash:
            return content_hash[:12]
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def _upload_to_gcs(self, local_path: Path, blob_name: str) -> str:
        """Sube un archivo PNG al bucket GCS configurado.

        Parameters
        ----------
        local_path : Path
            Ruta al archivo PNG local.
        blob_name : str
            Nombre del blob destino en GCS.

        Returns
        -------
        str
            URI GCS completa: ``gs://bucket/blob_name``
        """
        client = (
            storage.Client.from_service_account_json(self._credentials_path)
            if self._credentials_path
            else storage.Client()
        )

        bucket = client.bucket(self._bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(
            str(local_path),
            content_type="image/png",
        )

        gcs_uri = f"gs://{self._bucket_name}/{blob_name}"
        return gcs_uri
