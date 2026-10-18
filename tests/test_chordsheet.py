import json
from pathlib import Path

import pytest

from chordsheet import (
    Chord,
    _bars_in_row,
    _numbers_label,
    _shift,
    detect_keys,
    main,
    parse,
    parse_chord,
    serialize,
    shape_name,
    transpose_chord,
)

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "night-ferry.chords"


def _chords_of(sheet):
    return [t.text() for s in sheet.sections for r in s.rows for t in r.tokens if isinstance(t, Chord)]


def test_parses_glued_and_slash_chords():
    assert parse_chord("C#m7").root == "C#"
    assert parse_chord("C#m7").quality == "m7"
    assert parse_chord("Bbmaj7/Ab").bass == "Ab"
    assert parse_chord("Gsus4").quality == "sus4"
    assert parse_chord("Bm7b5").quality == "m7b5"
    assert parse_chord("D7#9").quality == "7#9"


def test_rejects_non_chords():
    for word in ["H7", "Cxyz", "g", "Cbbb", "Em9z"]:
        assert parse_chord(word) is None, word


def test_parse_reports_line_numbers_for_bad_chords_and_keys():
    sheet = parse("key: H\n[Verse]\nC G H7 |\n")
    assert [line for line, _ in sheet.errors] == [1, 3]
    assert "invalid key" in sheet.errors[0][1]
    assert "'H7' is not a chord" in sheet.errors[1][1]


def test_comments_and_blank_lines_keep_true_line_numbers():
    sheet = parse("# note\n\n\nC G\n")
    assert sheet.sections[0].name is None
    assert sheet.sections[0].rows[0].line == 4


def test_glued_bar_lines_split_into_tokens():
    sheet = parse("|C|G|\n")
    tokens = sheet.sections[0].rows[0].tokens
    assert [t if isinstance(t, str) else t.text() for t in tokens] == ["|", "C", "|", "G", "|"]


def test_bar_counting_ignores_empty_segments():
    tokens = parse("G | Em | C | D |\n").sections[0].rows[0].tokens
    assert _bars_in_row(tokens) == 4
    assert _bars_in_row(parse("C G Am F\n").sections[0].rows[0].tokens) == 1


def test_meta_validation_reports_each_bad_field():
    sheet = parse("capo: 12\ntempo: 5\ntime: 5/3\nkey: Hm\nfoo: bar\ntitle: One\ntitle: Two\n")
    messages = [message for _, message in sheet.errors]
    assert len(messages) == 6
    assert any("capo must" in m for m in messages)
    assert any("tempo must" in m for m in messages)
    assert any("time must" in m for m in messages)
    assert any("unknown field 'foo'" in m for m in messages)
    assert any("duplicate field 'title'" in m for m in messages)


def test_transpose_chord_sharps_and_flats():
    assert transpose_chord(Chord("G", "m"), 2, flats=False).text() == "Am"
    assert transpose_chord(Chord("C", "", None), 10, flats=True).text() == "Bb"
    assert transpose_chord(Chord("E", "", "B"), 1, flats=False).text() == "F/C"


def test_transposing_by_zero_or_twelve_changes_nothing():
    sheet = parse(EXAMPLE.read_text(encoding="utf-8"))
    original = serialize(sheet)
    zero, _ = _shift(sheet, None, 0, "auto")
    twelve, _ = _shift(sheet, None, 12, "auto")
    assert serialize(zero) == original
    assert serialize(twelve) == original


def test_transpose_to_key_moves_tonic_and_key_line():
    sheet = parse(EXAMPLE.read_text(encoding="utf-8"))
    shifted, error = _shift(sheet, "Bb", None, "auto")
    assert error is None
    assert shifted.meta["key"] == "Bb"
    first_row = shifted.sections[0].rows[0].tokens
    assert first_row[0].text() == "Bb"
    assert _chords_of(shifted)[1] == "Gm"


def test_semitone_shift_spells_new_key_for_flat_keys():
    shifted, error = _shift(parse("key: G\nG\n"), None, 3, "auto")
    assert error is None
    assert shifted.meta["key"] == "Bb"
    assert shifted.sections[0].rows[0].tokens[0].text() == "Bb"


def test_transpose_requires_a_key_for_to():
    sheet = parse("C G\n")
    shifted, error = _shift(sheet, "D", None, "auto")
    assert shifted is None
    assert "needs a valid 'key:'" in error


def test_capo_shape_mapping_and_best_capo():
    sounding = ["Bb", "F", "Gm", "Eb"]
    chords = [parse_chord(name) for name in sounding]
    assert [shape_name(c, 0) for c in chords] == ["Bb", "F", "Gm", "Eb"]
    shapes_at_three = [shape_name(c, 3) for c in chords]
    assert shapes_at_three == ["G", "D", "Em", "C"]
    assert all(shape in {"G", "D", "Em", "C"} for shape in shapes_at_three)


def test_detect_finds_major_and_minor_keys():
    major = parse("G Em C D G\n")
    assert detect_keys(major)[0][2] == "G major"
    minor = parse("Am Dm E Am\n")
    assert detect_keys(minor)[0][2] == "A minor"


def test_nashville_and_roman_labels_including_chromatic_degrees():
    g_tonic = 7
    assert _numbers_label(Chord("G", ""), g_tonic, "nashville") == "1"
    assert _numbers_label(Chord("E", "m"), g_tonic, "nashville") == "6m"
    assert _numbers_label(Chord("A", "m7"), g_tonic, "nashville") == "2m7"
    assert _numbers_label(Chord("F", ""), g_tonic, "nashville") == "b7"
    assert _numbers_label(Chord("E", "m"), g_tonic, "roman") == "vi"
    assert _numbers_label(Chord("D", "7"), g_tonic, "roman") == "V7"
    assert _numbers_label(Chord("Bb", ""), g_tonic, "roman") == "bIII"
    assert _numbers_label(Chord("B", "dim"), g_tonic, "roman") == "iii°"


def test_example_length_is_twenty_bars_at_96_bpm(capsys):
    assert main(["length", str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "Total" in out and "20" in out
    assert "Duration: 0:50" in out


def test_length_needs_a_tempo(tmp_path, capsys):
    chart = tmp_path / "no-tempo.chords"
    chart.write_text("C G\n", encoding="utf-8")
    assert main(["length", str(chart)]) == 1
    assert "needs 'tempo:'" in capsys.readouterr().err


def test_lint_exit_codes_and_line_numbered_output(tmp_path, capsys):
    assert main(["lint", str(EXAMPLE)]) == 0
    assert "ok (" in capsys.readouterr().out
    bad = tmp_path / "bad.chords"
    bad.write_text("capo: 12\n[Verse]\nC H7\n", encoding="utf-8")
    assert main(["lint", str(bad)]) == 1
    err = capsys.readouterr().err
    assert f"{bad}:1: error:" in err
    assert f"{bad}:3: error:" in err


def test_broken_example_reports_errors_then_warnings(capsys):
    broken = EXAMPLE.parent / "broken.chords"
    assert main(["lint", str(broken)]) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].startswith(f"{broken}:1: error: invalid key 'H'")
    assert lines[1] == f"{broken}:3: error: 'H7' is not a chord"
    assert "no 'key:' set" in lines[2]
    assert lines[3] == f"{broken}:2: warning: section [Verse] has no chords"
    assert lines[4].endswith("warning: no chords in file")


def test_lint_strict_fails_on_warnings(tmp_path):
    chart = tmp_path / "warn.chords"
    chart.write_text("[Empty]\n", encoding="utf-8")
    assert main(["lint", str(chart)]) == 0
    assert main(["lint", "--strict", str(chart)]) == 1


def test_transpose_command_prints_round_trippable_chart(capsys):
    assert main(["transpose", str(EXAMPLE), "--semitones", "2"]) == 0
    printed = capsys.readouterr().out
    assert "key: A" in printed
    assert _chords_of(parse(printed))[0] == "A"


def test_show_and_numbers_commands_run_on_example(capsys):
    assert main(["show", str(EXAMPLE), "--to", "A"]) == 0
    assert "Night Ferry" in capsys.readouterr().out
    assert main(["numbers", str(EXAMPLE), "--style", "roman"]) == 0
    assert "I" in capsys.readouterr().out


def test_export_emits_json_with_sections(capsys):
    assert main(["export", str(EXAMPLE)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["meta"]["title"] == "Night Ferry"
    assert [s["name"] for s in data["sections"]] == ["Verse", "Chorus"]


def test_capo_command_ranks_best_position_first(capsys):
    chart = Path(EXAMPLE)
    assert main(["capo", str(chart), "--max-fret", "4"]) == 0
    first_data_line = capsys.readouterr().out.splitlines()[1]
    assert first_data_line.startswith("   0")
    assert "<- best" in first_data_line


def test_chords_command_counts_usage(capsys):
    assert main(["chords", str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "G " in out and "distinct" in out


def test_missing_file_returns_usage_error(tmp_path, capsys):
    assert main(["lint", str(tmp_path / "nope.chords")]) == 2
    assert "nope.chords" in capsys.readouterr().err
