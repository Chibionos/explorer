from explorer.core.dedup import normalize_title, DedupIndex


def test_normalize_lowercases_and_strips_punctuation():
    assert normalize_title("Modal Close (X) misses 4px!") == "modal close x misses 4px"


def test_normalize_drops_stopwords():
    assert normalize_title("The save button on the page is broken") == "save button page broken"


def test_normalize_collapses_whitespace():
    assert normalize_title("  too    many   spaces  ") == "too many spaces"


def test_index_seeds_from_existing():
    idx = DedupIndex.from_pairs([("Save button broken", "ABC-1")])
    assert idx.lookup("Save Button Broken!") == "ABC-1"


def test_index_miss_returns_none():
    idx = DedupIndex.from_pairs([("Save button broken", "ABC-1")])
    assert idx.lookup("Totally different bug") is None


def test_index_record_updates():
    idx = DedupIndex.from_pairs([])
    idx.record("New bug found", "ABC-99")
    assert idx.lookup("new bug found") == "ABC-99"


def test_index_titles_for_prompt_returns_jira_pairs():
    idx = DedupIndex.from_pairs([("A bug", "ABC-1"), ("Another bug", "ABC-2")])
    pairs = idx.titles_for_prompt()
    assert ("ABC-1", "A bug") in pairs
    assert ("ABC-2", "Another bug") in pairs
