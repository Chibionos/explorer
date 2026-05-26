from explorer.runner.tabs import _parse_tabs_output, ChromeTab


def test_parse_picks_last_json_line():
    out = """some preamble
[{"title": "Tab A", "url": "https://a.example.com"}]
"""
    tabs = _parse_tabs_output(out)
    assert tabs == [ChromeTab(title="Tab A", url="https://a.example.com")]


def test_parse_ignores_garbage_before_json():
    out = """oh no a warning
[2026-05-26] starting up
[{"title":"X","url":"u"},{"title":"Y","url":"v"}]
"""
    tabs = _parse_tabs_output(out)
    assert len(tabs) == 2
    assert tabs[0].url == "u"
    assert tabs[1].url == "v"


def test_parse_returns_empty_on_no_json():
    assert _parse_tabs_output("nothing here\nnothing there\n") == []


def test_parse_returns_empty_on_empty_string():
    assert _parse_tabs_output("") == []


def test_parse_skips_non_list_json():
    out = '{"not": "a list"}\n[{"title":"X","url":"u"}]\n'
    tabs = _parse_tabs_output(out)
    assert tabs == [ChromeTab(title="X", url="u")]
