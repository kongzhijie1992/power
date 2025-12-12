import sys
import subprocess
from pathlib import Path


def make_sample_csv(path: Path):
    # small sample with two MTUs (00:00-00:15, 00:15-00:30) across one hour
    rows = [
        ['MTU (UTC)', 'Area', 'Sequence', 'Day-ahead Price (EUR/MWh)', 'Intraday Period (UTC)', 'Intraday Price (EUR/MWh)'],
    ]
    mtu_base = ['01/01/2025 00:00:00 - 01/01/2025 00:15:00', '01/01/2025 00:15:00 - 01/01/2025 00:30:00', '01/01/2025 00:30:00 - 01/01/2025 00:45:00', '01/01/2025 00:45:00 - 01/01/2025 01:00:00']
    for mtu in mtu_base:
        rows.append([mtu, 'BZN|DE-LU', 'Sequence Sequence 1', '10.0', '', ''])
        rows.append([mtu, 'BZN|DE-LU', 'Sequence Sequence 2', '20.0', '', ''])

    with path.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(','.join(f'"{c}"' for c in r) + '\n')


def test_converter_both_sequences(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    script = repo / 'scripts' / 'convert_entsoe.py'
    assert script.exists(), "converter script missing"

    src = tmp_path / 'gui_sample.csv'
    make_sample_csv(src)

    out_base = tmp_path / 'day_ahead.csv'

    cmd = [sys.executable, str(script), '--input', str(src), '--output', str(out_base), '--both', '--resample', 'H', '--tz', 'UTC']
    subprocess.run(cmd, check=True)

    out1 = out_base.parent / (out_base.stem + '_seq1.csv')
    out2 = out_base.parent / (out_base.stem + '_seq2.csv')
    assert out1.exists() and out2.exists()

    s1 = out1.read_text(encoding='utf-8')
    s2 = out2.read_text(encoding='utf-8')
    # check UTC offset present and values aggregated (hour -> single row)
    assert '+00:00' in s1.splitlines()[1]
    assert '+00:00' in s2.splitlines()[1]
    # sequence 1 mean should be 10.0, sequence 2 mean 20.0
    assert ',10.0' in s1
    assert ',20.0' in s2
