"""Phase 10 release-engineering layer: integrity validation, dependency
license inventory, SBOM generation, and the deterministic release
manifest + readiness decision behind `credlens release
validate/licenses/sbom/manifest/status`.

Every check here is LOCAL ONLY - no network access, no external service
(no secret scanner that uploads content, no license-database API call).
License data comes from already-installed packages' own metadata
(`importlib.metadata`), never a remote lookup.
"""

from __future__ import annotations
