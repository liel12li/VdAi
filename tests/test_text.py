"""Tests for RTL text rendering helpers."""

import numpy as np

from vdai.video import text as textmod
from vdai.video.fonts import find_font_path, load_font


def test_font_is_available():
    assert find_font_path()


def test_is_rtl():
    assert textmod.is_rtl("שלום עולם")
    assert not textmod.is_rtl("hello world")
    assert textmod.is_rtl("מבצע 50% off")


def test_to_display_reverses_hebrew():
    logical = "שלום"
    display = textmod.to_display(logical)
    assert display == logical[::-1]


def test_to_display_keeps_english():
    assert textmod.to_display("hello") == "hello"


def test_wrap_text_splits_long_lines():
    font = load_font(60)
    text = "זהו משפט ארוך מאוד שחייב להתחלק לכמה שורות כדי להיכנס למסך"
    lines = textmod.wrap_text(text, font, max_width=400)
    assert len(lines) > 1
    # No content lost
    assert " ".join(lines).split() == text.split()


def test_render_text_image_hebrew_pill():
    img = textmod.render_text_image("בואו לבקר אותנו", font_size=48, pill=True)
    arr = np.array(img)
    assert arr.shape[2] == 4
    assert arr[..., 3].max() > 0  # something was drawn


def test_text_array_multiline():
    arr = textmod.text_array(
        "שלוש סיבות טובות לבחור דווקא בנו ולא באחרים",
        font_size=40,
        max_width=300,
    )
    assert arr.ndim == 3 and arr.shape[2] == 4
    assert arr.shape[0] > 80  # wrapped into multiple lines
