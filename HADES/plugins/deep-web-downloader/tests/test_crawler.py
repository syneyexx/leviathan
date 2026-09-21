from deep_utils import extract_links, parse_bool, sanitize_filename

def run():
    links = extract_links(
        '<a href="/a"><iframe src="https://cdn.example/x.pdf"></iframe><div data-url="/b"></div>',
        "https://example.org/start",
    )
    assert "https://example.org/a" in links
    assert "https://cdn.example/x.pdf" in links
    assert "https://example.org/b" in links
    assert parse_bool("true") is True
    assert parse_bool("False") is False
    assert sanitize_filename('a:b?.pdf') == "a_b_.pdf"
    print("ok")

if __name__ == "__main__":
    run()
