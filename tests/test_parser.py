# tests/test_parser.py
from scripts import parser
def test_sample():
    txt = open("tests/sample_page.txt", encoding="utf-8").read()
    days = parser.parse_text_blocks(txt)
    assert len(days) >= 5
