#!/usr/bin/env python3
"""Chordsheet: an offline chord-chart toolkit for plain-text song files."""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
NATURAL_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Dm", "Gm", "Cm", "Fm", "Bbm", "Ebm"}
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
NASHVILLE = ["1", "b2", "2", "b3", "3", "4", "#4", "5", "b6", "6", "b7", "7"]
ROMAN = ["I", "bII", "II", "bIII", "III", "IV", "#IV", "V", "bVI", "VI", "bVII", "VII"]
EASY_SHAPES = {
    "C", "C7", "Cmaj7", "Cadd9", "D", "D7", "Dm", "Dm7", "Dsus2", "Dsus4",
    "E", "E7", "Em", "Em7", "G", "G7", "Gmaj7", "A", "A7", "Am", "Am7",
    "Asus2", "Asus4",
}
BAR_TOKENS = {"|", "||", "%"}
META_FIELDS = ("title", "artist", "key", "capo", "tempo", "time")

NOTE = r"[A-G](?:#|b)?"
KEY_RE = re.compile(rf"^({NOTE})(m|min|minor|maj|major)?$")
CHORD_RE = re.compile(
    rf"^(?P<root>{NOTE})"
    r"(?P<quality>(?:maj|min|m|M|dim|o|aug|\+|-|sus|add)?\d*(?:(?:b|#|\+|-)\d+)*(?:sus|add)?\d*)"
    rf"(?:/(?P<bass>{NOTE}))?$"
)
HEADER_RE = re.compile(r"^\[(.+)\]$")
META_RE = re.compile(r"^([A-Za-z]+)\s*:\s*(.*)$")
TIME_RE = re.compile(r"^(\d+)/(\d+)$")
BAR_SPLIT_RE = re.compile(r"\|\|?")


def note_pc(name):
    pc = NATURAL_PC[name[0]]
    if len(name) > 1:
        pc += 1 if name[1] == "#" else -1
    return pc % 12


@dataclass(frozen=True)
class Chord:
    root: str
    quality: str
    bass: str | None = None

    def text(self):
        return self.root + self.quality + (f"/{self.bass}" if self.bass else "")

    @property
    def root_pc(self):
        return note_pc(self.root)


@dataclass
class Row:
    line: int
    tokens: list


@dataclass
class Section:
    name: str | None
    line: int
    rows: list = field(default_factory=list)


@dataclass
class Sheet:
    meta: dict = field(default_factory=dict)
    meta_lines: dict = field(default_factory=dict)
    sections: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def parse_key(text):
    """Return (name, tonic_pc, is_minor) for a key like G, Bbm or F#minor, else None."""
    match = KEY_RE.match(text.strip())
    if not match:
        return None
    name, mode = match.group(1), match.group(2)
    return name, note_pc(name), mode in ("m", "min", "minor")


def parse_chord(word):
    match = CHORD_RE.match(word)
    if not match:
        return None
    return Chord(match.group("root"), match.group("quality"), match.group("bass"))


def normalize_quality(quality):
    if quality == "sus":
        return "sus4"
    for old, new in (("min", "m"), ("M", "maj"), ("o", "dim"), ("-", "m"), ("+", "aug")):
        if quality.startswith(old):
            return new + quality[len(old):]
    return quality


def quality_kind(quality):
    """Split a normalized quality into (kind, remainder): major, minor, dim or aug."""
    if quality.startswith("m") and not quality.startswith("maj"):
        return "minor", quality[1:]
    if quality.startswith("dim"):
        return "dim", quality[3:]
    if quality.startswith("aug"):
        return "aug", quality[3:]
    return "major", quality


def transpose_chord(chord, semitones, flats):
    names = FLAT_NAMES if flats else SHARP_NAMES

    def move(name):
        return names[(note_pc(name) + semitones) % 12]

    bass = move(chord.bass) if chord.bass else None
    return Chord(move(chord.root), chord.quality, bass)


def _meta_problem(key, value):
    if not value:
        return f"'{key}' has no value"
    if key == "key":
        return None if parse_key(value) else f"invalid key '{value}' (try G, Bbm or F#m)"
    if key == "capo":
        ok = value.isdigit() and int(value) <= 11
        return None if ok else "capo must be a whole number from 0 to 11"
    if key == "tempo":
        ok = value.isdigit() and 20 <= int(value) <= 300
        return None if ok else "tempo must be a whole number of BPM from 20 to 300"
    if key == "time":
        match = TIME_RE.match(value)
        if match and 1 <= int(match.group(1)) <= 16 and int(match.group(2)) in (1, 2, 4, 8, 16):
            return None
        return "time must look like 4/4 or 6/8"
    return None


def _add_meta(sheet, number, key, value):
    if key not in META_FIELDS:
        sheet.errors.append((number, f"unknown field '{key}'"))
        return
    if key in sheet.meta:
        first = sheet.meta_lines[key]
        sheet.errors.append((number, f"duplicate field '{key}' (first set on line {first})"))
        return
    problem = _meta_problem(key, value)
    if problem:
        sheet.errors.append((number, problem))
        return
    sheet.meta[key] = value
    sheet.meta_lines[key] = number


def _tokenize(line, number, sheet):
    spaced = BAR_SPLIT_RE.sub(lambda m: f" {m.group()} ", line)
    tokens = []
    ok = True
    for word in spaced.split():
        if word in BAR_TOKENS:
            tokens.append(word)
            continue
        chord = parse_chord(word)
        if chord is None:
            sheet.errors.append((number, f"'{word}' is not a chord"))
            ok = False
        else:
            tokens.append(chord)
    return tokens if ok else None


def parse(text):
    sheet = Sheet()
    current = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        header = HEADER_RE.match(line)
        if header:
            current = Section(header.group(1).strip(), number)
            sheet.sections.append(current)
            continue
        meta = META_RE.match(line)
        if meta:
            _add_meta(sheet, number, meta.group(1).lower(), meta.group(2).strip())
            continue
        tokens = _tokenize(line, number, sheet)
        if tokens is None:
            continue
        if current is None:
            current = Section(None, number)
            sheet.sections.append(current)
        current.rows.append(Row(number, tokens))
    return sheet


def _chords(sheet):
    for section in sheet.sections:
        for row in section.rows:
            for token in row.tokens:
                if isinstance(token, Chord):
                    yield token


def _bars_in_row(tokens):
    segments = [[]]
    for token in tokens:
        if token in ("|", "||"):
            segments.append([])
        else:
            segments[-1].append(token)
    return sum(1 for segment in segments if segment)


def _shift(sheet, to, semitones, spelling):
    """Return (new_sheet, error). Shifts every chord by a tonic move or a semitone count."""
    source = parse_key(sheet.meta["key"]) if "key" in sheet.meta else None
    if to is not None:
        target = parse_key(to)
        if target is None:
            return None, f"invalid target key '{to}'"
        if source is None:
            return None, "transposing with --to needs a valid 'key:' line in the file"
        shift = (target[1] - source[1]) % 12
        key_text = target[0] + ("m" if target[2] else "")
    else:
        shift = semitones % 12
        key_text = None
        if source is not None:
            key_text = _spell_key((source[1] + shift) % 12, source[2], spelling)
    flats = _use_flats(spelling, key_text)
    shifted = Sheet(meta=dict(sheet.meta), meta_lines=dict(sheet.meta_lines))
    if key_text is not None:
        shifted.meta["key"] = key_text
    for section in sheet.sections:
        rows = [
            Row(row.line, [transpose_chord(t, shift, flats) if isinstance(t, Chord) else t
                           for t in row.tokens])
            for row in section.rows
        ]
        shifted.sections.append(Section(section.name, section.line, rows))
    return shifted, None


def _spell_key(pc, minor, spelling):
    suffix = "m" if minor else ""
    flat_name = FLAT_NAMES[pc] + suffix
    use_flat = spelling == "flat" or (spelling == "auto" and flat_name in FLAT_KEYS)
    return (FLAT_NAMES[pc] if use_flat else SHARP_NAMES[pc]) + suffix


def _use_flats(spelling, key_text):
    if spelling == "flat":
        return True
    if spelling == "sharp" or key_text is None:
        return False
    return key_text in FLAT_KEYS


def render(sheet, text_of=lambda chord: chord.text()):
    out = []
    title = sheet.meta.get("title")
    if title:
        artist = sheet.meta.get("artist")
        out.append(f"{title} — {artist}" if artist else title)
    info = []
    for key, label in (("key", "Key"), ("capo", "Capo"), ("tempo", "Tempo"), ("time", "Time")):
        if key in sheet.meta:
            value = sheet.meta[key]
            info.append(f"{label}: {value}{' bpm' if key == 'tempo' else ''}")
    if info:
        out.append("   ".join(info))
    for section in sheet.sections:
        out.append("")
        if section.name is not None:
            out.append(f"[{section.name}]")
        for row in section.rows:
            out.append("  " + " ".join(_token_text(t, text_of) for t in row.tokens))
    return "\n".join(out) + "\n"


def _token_text(token, text_of):
    return text_of(token) if isinstance(token, Chord) else token


def serialize(sheet):
    out = [f"{key}: {value}" for key, value in sheet.meta.items()]
    for section in sheet.sections:
        out.append("")
        if section.name is not None:
            out.append(f"[{section.name}]")
        for row in section.rows:
            out.append(" ".join(_token_text(t, lambda c: c.text()) for t in row.tokens))
    return "\n".join(out) + "\n"


def _degree_label(interval, style):
    return (NASHVILLE if style == "nashville" else ROMAN)[interval % 12]


def _numbers_label(chord, tonic, style):
    kind, rest = quality_kind(normalize_quality(chord.quality))
    base = _degree_label(chord.root_pc - tonic, style)
    if style == "nashville":
        suffix = {"major": "", "minor": "m", "dim": "dim", "aug": "aug"}[kind]
        label = base + suffix + rest
    else:
        pre = base[0] if base[0] in "b#" else ""
        numeral = base[len(pre):]
        if kind in ("minor", "dim"):
            numeral = numeral.lower()
        suffix = {"major": "", "minor": "", "dim": "°", "aug": "+"}[kind]
        label = pre + numeral + suffix + rest
    if chord.bass:
        label += "/" + _degree_label(note_pc(chord.bass) - tonic, style)
    return label


def _is_tonic_chord(chord, tonic, minor):
    """True when the chord is the tonic in the same mode (Am counts for A minor, not A major)."""
    kind = quality_kind(normalize_quality(chord.quality))[0]
    return chord.root_pc == tonic and kind == ("minor" if minor else "major")


def detect_keys(sheet):
    chords = list(_chords(sheet))
    if not chords:
        return []
    results = []
    for tonic in range(12):
        for minor in (False, True):
            scale = {(tonic + i) % 12 for i in (MINOR_SCALE if minor else MAJOR_SCALE)}
            fit = sum(c.root_pc in scale for c in chords) / len(chords)
            bonus = 0.05 * _is_tonic_chord(chords[0], tonic, minor) + 0.05 * _is_tonic_chord(chords[-1], tonic, minor)
            name = SHARP_NAMES[tonic] + (" minor" if minor else " major")
            results.append((fit + bonus, fit, name))
    results.sort(key=lambda r: -r[0])
    return results[:3]


def shape_name(chord, capo):
    pc = (chord.root_pc - capo) % 12
    names = FLAT_NAMES if chord.root[1:] == "b" else SHARP_NAMES
    return names[pc] + normalize_quality(chord.quality)


def _print_errors(path, errors):
    for number, message in errors:
        print(f"{path}:{number}: error: {message}", file=sys.stderr)


def _lint_warnings(sheet):
    warnings = []
    if "key" not in sheet.meta:
        warnings.append((None, "no 'key:' set (needed by numbers and transpose --to)"))
    names = [s.name for s in sheet.sections if s.name]
    for name in {n for n in names if names.count(n) > 1}:
        warnings.append((None, f"section [{name}] appears more than once"))
    for section in sheet.sections:
        if not section.rows:
            warnings.append((section.line, f"section [{section.name}] has no chords"))
    if not any(True for _ in _chords(sheet)):
        warnings.append((None, "no chords in file"))
    return warnings


def cmd_lint(args, path, sheet):
    warnings = _lint_warnings(sheet)
    _print_errors(path, sheet.errors)
    for number, message in warnings:
        prefix = f"{path}:{number}" if number else path
        print(f"{prefix}: warning: {message}", file=sys.stderr)
    if sheet.errors:
        return 1
    if warnings and args.strict:
        return 1
    if not warnings:
        print(f"{path}: ok ({sum(1 for _ in _chords(sheet))} chords)")
    return 0


def cmd_show(args, path, sheet):
    shifted, error = _shift(sheet, args.to, args.semitones, args.spelling) if _shifting(args) else (sheet, None)
    if error:
        print(f"chordsheet: {error}", file=sys.stderr)
        return 1
    print(render(shifted), end="")
    return 0


def cmd_transpose(args, path, sheet):
    if not _shifting(args):
        print("chordsheet: transpose needs --to KEY or --semitones N", file=sys.stderr)
        return 2
    shifted, error = _shift(sheet, args.to, args.semitones, args.spelling)
    if error:
        print(f"chordsheet: {error}", file=sys.stderr)
        return 1
    print(serialize(shifted), end="")
    return 0


def _shifting(args):
    return args.to is not None or args.semitones is not None


def cmd_capo(args, path, sheet):
    chords = list(_chords(sheet))
    if not chords:
        print("chordsheet: no chords to analyse", file=sys.stderr)
        return 1
    options = []
    for capo in range(args.max_fret + 1):
        shapes = [shape_name(c, capo) for c in chords]
        easy = sum(s in EASY_SHAPES for s in shapes) / len(chords)
        options.append((capo, easy, list(dict.fromkeys(shapes))))
    ranked = sorted(options, key=lambda o: (-o[1], o[0]))
    print(f"{'Capo':>4}  {'Easy':>5}  Shape chords (what you finger after the capo)")
    for index, (capo, easy, shapes) in enumerate(ranked):
        mark = "  <- best" if index == 0 else ""
        print(f"{capo:>4}  {easy * 100:4.0f}%  {' '.join(shapes)}{mark}")
    return 0


def cmd_detect(args, path, sheet):
    results = detect_keys(sheet)
    if not results:
        print("chordsheet: no chords to analyse", file=sys.stderr)
        return 1
    for _, fit, name in results:
        print(f"{name:<12} fit {fit * 100:5.1f}%")
    return 0


def cmd_numbers(args, path, sheet):
    if "key" not in sheet.meta:
        print("chordsheet: numbers needs a 'key:' line in the file", file=sys.stderr)
        return 1
    tonic = parse_key(sheet.meta["key"])[1]
    print(render(sheet, lambda c: _numbers_label(c, tonic, args.style)), end="")
    return 0


def cmd_chords(args, path, sheet):
    counts = Counter(c.text() for c in _chords(sheet))
    if not counts:
        print("chordsheet: no chords in file", file=sys.stderr)
        return 1
    print(f"{'Chord':<12} Count")
    for name, count in counts.most_common():
        print(f"{name:<12} {count:5d}")
    print(f"\n{len(counts)} distinct, {sum(counts.values())} total")
    return 0


def cmd_length(args, path, sheet):
    bpm = args.bpm if args.bpm is not None else (int(sheet.meta["tempo"]) if "tempo" in sheet.meta else None)
    if bpm is None:
        print("chordsheet: length needs 'tempo:' in the file or --bpm", file=sys.stderr)
        return 1
    time_text = sheet.meta.get("time", "4/4")
    beats = int(TIME_RE.match(time_text).group(1))
    total = 0
    print(f"{'Section':<16} {'Bars':>4}")
    for section in sheet.sections:
        bars = sum(_bars_in_row(row.tokens) for row in section.rows)
        total += bars
        print(f"{section.name or '(intro)':<16} {bars:>4}")
    seconds = round(total * beats * 60 / bpm)
    minutes, secs = divmod(seconds, 60)
    print(f"{'Total':<16} {total:>4}  ({time_text} at {bpm} bpm)")
    print(f"Duration: {minutes}:{secs:02d}")
    return 0


def cmd_export(args, path, sheet):
    data = {
        "meta": sheet.meta,
        "sections": [
            {
                "name": section.name,
                "line": section.line,
                "rows": [
                    {"line": row.line, "tokens": [_token_text(t, lambda c: c.text()) for t in row.tokens]}
                    for row in section.rows
                ],
            }
            for section in sheet.sections
        ],
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


COMMANDS = {
    "show": cmd_show,
    "transpose": cmd_transpose,
    "capo": cmd_capo,
    "detect": cmd_detect,
    "numbers": cmd_numbers,
    "chords": cmd_chords,
    "length": cmd_length,
    "export": cmd_export,
}


def build_parser():
    parser = argparse.ArgumentParser(prog="chordsheet", description="Offline chord-chart toolkit.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("file", help="plain-text chord chart")
        return p

    def add_shift(p):
        p.add_argument("--to", metavar="KEY", help="transpose so the tonic becomes KEY (e.g. Bb, Em)")
        p.add_argument("--semitones", type=int, metavar="N", help="transpose by N semitones")
        p.add_argument("--spelling", choices=["auto", "sharp", "flat"], default="auto")

    p = add("lint", "check the file and report line-numbered errors")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures")
    p = add("show", "print the chart, optionally transposed")
    add_shift(p)
    p = add("transpose", "print the transposed chart in chart-file format")
    add_shift(p)
    p = add("capo", "compare capo positions by how many chords are easy shapes")
    p.add_argument("--max-fret", type=int, default=7)
    add("detect", "estimate the most likely key")
    p = add("numbers", "show chords as Nashville or Roman numerals")
    p.add_argument("--style", choices=["nashville", "roman"], default="nashville")
    add("chords", "count how often each chord is used")
    p = add("length", "count bars per section and estimate duration")
    p.add_argument("--bpm", type=int, help="override the file's tempo")
    add("export", "dump the parsed chart as JSON")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"chordsheet: {exc}", file=sys.stderr)
        return 2
    sheet = parse(text)
    if args.command == "lint":
        return cmd_lint(args, args.file, sheet)
    if sheet.errors:
        _print_errors(args.file, sheet.errors)
        print("chordsheet: fix the errors above (run `lint` for a full report)", file=sys.stderr)
        return 1
    return COMMANDS[args.command](args, args.file, sheet)


if __name__ == "__main__":
    sys.exit(main())
