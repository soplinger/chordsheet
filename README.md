# 🎸 Chordsheet

**An offline chord-chart toolkit for plain-text song files.**

Chordsheet reads a simple text chart and gives you back transpositions, capo options, key guesses, Nashville or Roman numbers, bar counts and song length. It runs on Python 3's standard library, makes no network calls, and keeps everything in one readable file.

## Features

- **Lint** a chart and get `file:line` errors for bad chords, bad meta fields and malformed lines (`lint`, `--strict` for CI)
- **Show** a chart in a clean layout, optionally transposed on the way out (`show`)
- **Transpose** by a target tonic (`--to Bb`) or by a number of semitones (`--semitones -3`)
- **Spelling control** for transposed chords: `--spelling auto|sharp|flat`, with `auto` picking flats for flat keys
- **Capo finder** that ranks capo positions by how many chords become easy open shapes (`capo --max-fret 7`)
- **Key detection** that scores all 24 major and minor keys against the chords used (`detect`)
- **Nashville or Roman numerals** for each chord, including chromatic degrees such as `b7` or `bIII` (`numbers --style roman`)
- **Chord inventory** with usage counts and a distinct/total summary (`chords`)
- **Length estimate**: bars per section, total bars and a `m:ss` duration from the time signature and tempo (`length --bpm 100`)
- **JSON export** of the parsed chart for other tools (`export`)
- **Glued and slash chords** are understood: `C#m7`, `Bbmaj7/Ab`, `G7sus4`, `Bm7b5`
- **Bar lines are optional**: `|G|Em|` and `G Em` both parse
- **Comments and sections**: `# comments`, `[Verse]`, `[Chorus]` and an untitled intro
- **Exit codes** for scripts: `0` ok, `1` the chart has problems, `2` the file can't be read

## Chart format

```text
# comments start with #
title: Night Ferry
artist: Practice Tune
key: G
capo: 2
tempo: 96
time: 4/4

[Verse]
G | Em | C | D |
G | Em | C | D |

[Chorus]
C | G | Em | D |
```

Meta fields are `title`, `artist`, `key` (for example `G`, `Bbm` or `F#m`), `capo` (0 to 11), `tempo` (20 to 300 BPM) and `time` (such as `4/4` or `6/8`). Chord lines hold chords and bar lines (`|`, `||`) or the repeat sign `%`. Each bar line segment counts as one bar. Lyrics aren't supported yet.

## Quick start

```bash
python3 chordsheet.py lint examples/night-ferry.chords
# examples/night-ferry.chords: ok (20 chords)

python3 chordsheet.py show examples/night-ferry.chords --to A
python3 chordsheet.py capo examples/night-ferry.chords --max-fret 4
python3 chordsheet.py numbers examples/night-ferry.chords --style roman
python3 chordsheet.py length examples/night-ferry.chords
# Total   20  (4/4 at 96 bpm)
# Duration: 0:50
python3 chordsheet.py transpose examples/night-ferry.chords --semitones -2 > night-ferry-f.chords
```

A broken chart reports exact lines. Errors go to stderr first, then warnings, and `lint` exits with `1`:

```text
$ python3 chordsheet.py lint examples/broken.chords
examples/broken.chords:1: error: invalid key 'H' (try G, Bbm or F#m)
examples/broken.chords:3: error: 'H7' is not a chord
examples/broken.chords: warning: no 'key:' set (needed by numbers and transpose --to)
examples/broken.chords:2: warning: section [Verse] has no chords
examples/broken.chords: warning: no chords in file
```

## Requirements

- Python 3.10 or newer (the code uses `str | None` annotations, so 3.10+ is needed)
- Nothing to install for the tool itself
- `pytest` only if you want to run the test suite

## How to run

```bash
python3 chordsheet.py <command> <file> [options]
python3 chordsheet.py --help
python3 chordsheet.py <command> --help
```

Commands: `lint`, `show`, `transpose`, `capo`, `detect`, `numbers`, `chords`, `length`, `export`.

## How to test

```bash
pip install pytest
python3 -m pytest -q
```

The tests cover chord parsing, line-numbered errors, meta validation, transposition (including identity checks at 0 and 12 semitones), capo shape mapping, key detection, Nashville and Roman labels, bar counting, duration, lint exit codes and the JSON export.

## Project layout

```text
chordsheet.py          the whole tool (one file, standard library only)
examples/night-ferry.chords   a sample chart
examples/broken.chords        a deliberately broken chart for lint
tests/test_chordsheet.py      pytest suite
conftest.py           empty file that puts this folder on the import path
```

## Limits

- Key detection is a heuristic over chord roots. Modal and borrowed chords can point at the wrong key, so check the top few results.
- Capo shapes use a fixed list of open chords and look only at the chord root and quality. Slash-chord bass notes aren't checked for playability.
- `transpose` writes a clean chart, so `#` comments in the source file aren't kept in the output.
