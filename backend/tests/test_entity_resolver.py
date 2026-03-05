"""Tests for the Entity Resolution service."""

from app.entity_resolution.resolver import EntityResolver


def make_resolver() -> EntityResolver:
    return EntityResolver()


class TestStaticMatching:
    """Test exact matches from the static mapping tables."""

    def test_canonical_name_returns_itself(self):
        resolver = make_resolver()
        assert resolver.resolve("New York Yankees", "baseball_mlb", "team") == "New York Yankees"

    def test_variant_maps_to_canonical(self):
        resolver = make_resolver()
        assert resolver.resolve("Yankees", "baseball_mlb", "team") == "New York Yankees"
        assert resolver.resolve("NYY", "baseball_mlb", "team") == "New York Yankees"

    def test_case_insensitive(self):
        resolver = make_resolver()
        assert resolver.resolve("yankees", "baseball_mlb", "team") == "New York Yankees"
        assert resolver.resolve("YANKEES", "baseball_mlb", "team") == "New York Yankees"

    def test_blue_jays_variants(self):
        resolver = make_resolver()
        assert resolver.resolve("Blue Jays", "baseball_mlb", "team") == "Toronto Blue Jays"
        assert resolver.resolve("TOR", "baseball_mlb", "team") == "Toronto Blue Jays"
        assert resolver.resolve("Jays", "baseball_mlb", "team") == "Toronto Blue Jays"

    def test_ufc_fighter_static(self):
        resolver = make_resolver()
        assert resolver.resolve("Bones Jones", "mma_mixed_martial_arts", "fighter") == "Jon Jones"
        assert resolver.resolve("Do Bronx", "mma_mixed_martial_arts", "fighter") == "Charles Oliveira"


class TestFuzzyMatching:
    """Test fuzzy matching for names not in the static table."""

    def test_close_spelling(self):
        resolver = make_resolver()
        # "New York Yankee" is close enough to "New York Yankees"
        result = resolver.resolve("New York Yankee", "baseball_mlb", "team")
        assert result == "New York Yankees"

    def test_misspelling(self):
        resolver = make_resolver()
        result = resolver.resolve("Tronoto Blue Jays", "baseball_mlb", "team")
        assert result == "Toronto Blue Jays"

    def test_ufc_fuzzy(self):
        resolver = make_resolver()
        result = resolver.resolve("Islam Makachev", "mma_mixed_martial_arts", "fighter")
        assert result == "Islam Makhachev"


class TestCachingAndDynamic:
    """Test caching behavior and dynamic mapping additions."""

    def test_cache_hit(self):
        resolver = make_resolver()
        # First call populates cache
        resolver.resolve("Yankees", "baseball_mlb", "team")
        # Second call should hit cache (same result)
        result = resolver.resolve("Yankees", "baseball_mlb", "team")
        assert result == "New York Yankees"

    def test_add_mapping_dynamically(self):
        resolver = make_resolver()
        # Unknown name
        result = resolver.resolve("The Bronx Bombers", "baseball_mlb", "team")
        # Might not match — now add it dynamically
        resolver.add_mapping("baseball_mlb", "team", "The Bronx Bombers", "New York Yankees")
        result = resolver.resolve("The Bronx Bombers", "baseball_mlb", "team")
        assert result == "New York Yankees"

    def test_unknown_returns_original(self):
        resolver = make_resolver()
        result = resolver.resolve("Nonexistent Team XYZ", "baseball_mlb", "team")
        assert result == "Nonexistent Team XYZ"
