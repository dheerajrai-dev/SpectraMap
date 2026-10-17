"""
data_service.py — OpenCellID data fetching, normalization, and cache

Responsibilities:
- Builds a bounding box around a given center + radius.
- Tiles the bounding box into sub-areas within the OpenCellID limit (4,000,000 m²).
- Requests cell records from the OpenCellID area API (GET /cell/getInArea).
- Checks both HTTP status and response body for errors.
- Normalizes raw records into the project's internal data model.
- Deduplicates records from overlapping tiles.
- Filters records to the intended radius using a correct geodesic distance.
- Writes accepted records to a local cache; never overwrites a valid cache on failure.
- Returns records and a partial-data warning flag to the caller.

Implementation: Phase 3 (OpenCellID integration).
"""
