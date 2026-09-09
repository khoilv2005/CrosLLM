from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
harness_dir = ROOT / 'dataset' / 'harness'

DEV_LINEAGES = ['celer_cbridge', 'chainbridge', 'hop', 'layerzero_v2']

for lid in DEV_LINEAGES:
    p = harness_dir / lid / 'normal_workflow_test.py'
    text = p.read_text(encoding='utf-8')
    # Fix the broken multiline assert
    lines = text.splitlines()
    new_lines = []
    skip = False
    for line in lines:
        if 'assert ret == 0, f"Foundry EVM harness execution failed for' in line:
            new_lines.append(f'    if ret != 0:')
            new_lines.append(f'        print(stderr, file=sys.stderr)')
            new_lines.append(f'        print(stdout, file=sys.stderr)')
            new_lines.append(f'        raise AssertionError(f"Foundry EVM harness execution failed for {lid}")')
            skip = True
        elif skip and ('{stdout}"' in line or '{stderr}' in line):
            if '{stdout}"' in line:
                skip = False
        else:
            if not skip:
                new_lines.append(line)
    p.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    print(f'Cleaned {lid}')
