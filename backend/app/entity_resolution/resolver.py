"""Entity Resolution: fuzzy matching + static override table.

Maps variant team/fighter names from different bookmakers to a single
canonical name for consistent data storage and model input.
"""

import json
import logging
from pathlib import Path

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

MAPPINGS_DIR = Path(__file__).parent / "mappings"

# Minimum fuzzy score to accept an auto-match (0-100)
FUZZY_THRESHOLD = 85


class EntityResolver:
    """Resolves bookmaker-specific names to canonical names.

    Resolution order:
    1. Exact match in static override table → instant return
    2. Fuzzy match against known canonical names → accept if score >= threshold
    3. No match → return original name and log for manual review
    """

    def __init__(self):
        # {sport: {variant_lower: canonical_name}}
        self._static_map: dict[str, dict[str, str]] = {}
        # {sport: [canonical_names]} for fuzzy matching
        self._canonical_names: dict[str, list[str]] = {}
        # Cache resolved names to avoid repeated fuzzy lookups
        self._cache: dict[str, str] = {}

        self._load_static_mappings()

    def _load_static_mappings(self):
        """Load all JSON mapping files from the mappings directory."""
        if not MAPPINGS_DIR.exists():
            logger.warning("Mappings directory not found: %s", MAPPINGS_DIR)
            return

        for path in MAPPINGS_DIR.glob("*.json"):
            sport = path.stem  # e.g., "mlb_teams" → key by filename
            try:
                with open(path) as f:
                    data = json.load(f)

                sport_map = {}
                canonical_list = []

                for entry in data:
                    canonical = entry["canonical"]
                    canonical_list.append(canonical)
                    # Map all variants (including canonical itself) to canonical
                    sport_map[canonical.lower()] = canonical
                    for variant in entry.get("variants", []):
                        sport_map[variant.lower()] = canonical

                self._static_map[sport] = sport_map
                self._canonical_names[sport] = canonical_list
                logger.info(
                    "Loaded %d entities from %s", len(canonical_list), path.name
                )

            except (json.JSONDecodeError, KeyError):
                logger.exception("Failed to load mapping file: %s", path)

    def resolve(
        self, name: str, sport: str, entity_type: str = "team"
    ) -> str:
        """Resolve a name to its canonical form.

        Args:
            name: The raw name from a bookmaker.
            sport: Sport key (used to select the right mapping file).
            entity_type: "team" or "fighter" (for logging context).

        Returns:
            The canonical name, or the original if no match found.
        """
        cache_key = f"{sport}:{name.lower()}"

        # Check cache first
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Determine which mapping file to use
        mapping_key = self._mapping_key(sport, entity_type)

        # 1. Static exact match
        static = self._static_map.get(mapping_key, {})
        canonical = static.get(name.lower())
        if canonical:
            self._cache[cache_key] = canonical
            return canonical

        # 2. Fuzzy match against canonical names
        candidates = self._canonical_names.get(mapping_key, [])
        if candidates:
            result = process.extractOne(
                name,
                candidates,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=FUZZY_THRESHOLD,
            )
            if result:
                matched_name, score, _ = result
                logger.debug(
                    "Fuzzy matched '%s' → '%s' (score: %.1f)", name, matched_name, score
                )
                self._cache[cache_key] = matched_name
                return matched_name

        # 3. No match — return original, log for review
        logger.warning(
            "Unresolved %s: '%s' (sport: %s) — add to mapping file",
            entity_type,
            name,
            sport,
        )
        self._cache[cache_key] = name
        return name

    def _mapping_key(self, sport: str, entity_type: str) -> str:
        """Map sport + entity_type to the correct mapping file stem."""
        mapping = {
            ("baseball_mlb", "team"): "mlb_teams",
            ("mma_mixed_martial_arts", "team"): "ufc_fighters",
            ("mma_mixed_martial_arts", "fighter"): "ufc_fighters",
        }
        return mapping.get((sport, entity_type), f"{sport}_{entity_type}")

    def add_mapping(
        self, sport: str, entity_type: str, variant: str, canonical: str
    ):
        """Dynamically add a mapping (useful for runtime corrections)."""
        mapping_key = self._mapping_key(sport, entity_type)
        if mapping_key not in self._static_map:
            self._static_map[mapping_key] = {}
        self._static_map[mapping_key][variant.lower()] = canonical
        # Invalidate cache for this variant
        cache_key = f"{sport}:{variant.lower()}"
        self._cache.pop(cache_key, None)
