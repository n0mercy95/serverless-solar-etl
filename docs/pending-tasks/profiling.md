# Implementation Plan - Solar ETL Data Profiling (Observability)

Implement a `DataProfiler` service in the Application layer of the serverless solar ETL pipeline. This component performs fast, vectorized data profiling computations using Polars and outputs a structured ASCII table suitable for Cloud Logging.

## Proposed Architecture Layer

In **Clean Architecture**, this component should reside in the **Application Layer** as an Application Service:
- **Domain Layer (`domain/`)**: Must remain free of external frameworks like Polars and focus purely on core business rules and constants.
- **Infrastructure Layer (`infrastructure/`)**: Handles external details like BigQuery, GCS, and the actual Cloud Logging destination.
- **Application Layer (`application/`)**: Perfect for `DataProfiler` because it orchestrates and processes data structures (Polars DataFrames) to calculate metrics and produce the reporting string without depending on I/O mechanisms.

We will place the file at [data_profiler.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/data_profiler.py).

## Proposed Changes

### 1. Application Layer

#### [NEW] [data_profiler.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/data_profiler.py)
Create `DataProfiler` which calculates all required metrics in a single vectorized Polars selection.

Key computations:
- Accept `pl.DataFrame` or `pl.LazyFrame` (collecting lazy frames dynamically).
- Compute solar declination and elevation to define astronomical nighttime for each station.
- Calculate:
  - **Null values** (`is_null()`)
  - **Negative values** (`col < 0`)
  - **Nighttime Power > 0** (`(power > 0) & ((lmd_totalirrad == 0) | (solar_elevation <= 0))`)
  - **Descriptive stats** (`mean()`, `std()`, `min()`, `max()`)
- Formulate an **Overall Quality Score** representing the percentage of clean, valid data points across the 4 columns:
  $$\text{Quality Score} = \left(1 - \frac{\text{total\_issues}}{\text{total\_records} \times 4}\right) \times 100$$
- Format the results into the exact ASCII table requested, timing the profiling process internally.

#### [MODIFY] [pipeline.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/pipeline.py)
Integrate `DataProfiler` inside the `execute` orchestrator:
- **Pre-Cleaning Profile**: Run `DataProfiler` immediately after `load_and_align` (Fase 2.1).
- **Post-Cleaning Profile**: Run `DataProfiler` immediately after the cleaning strategies are applied (Fase 2.2).
- Output both reports to Cloud Logging via `logger.info()`.

---

## Verification Plan

### Automated Tests
- Create a new unit test suite [test_data_profiler.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/tests/test_data_profiler.py) to:
  - Verify that both `pl.DataFrame` and `pl.LazyFrame` are correctly handled.
  - Verify that the metrics (Nulls, Negatives, Nighttime Power > 0, Mean, Std, Min, Max) are computed accurately.
  - Verify the formatting matches the exact ASCII schema requested.
- Run all tests via:
  ```bash
  .venv/bin/pytest tests/test_data_profiler.py
  .venv/bin/pytest
  ```

### Manual Verification
- Review the formatted ASCII string output to ensure character alignments and headings match the specification.
