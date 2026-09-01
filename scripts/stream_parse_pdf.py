import sys
import json
from pathlib import Path
import importlib.util

if len(sys.argv) < 2:
    print('Usage: python scripts/stream_parse_pdf.py /path/to/file.pdf')
    sys.exit(2)

pdf_path = sys.argv[1]

# Load pdf_timetable_parser as a standalone module to avoid Django app imports
parser_path = Path('apps/timetable/services/pdf_timetable_parser.py')
if not parser_path.exists():
    print('Could not find parser at', parser_path)
    sys.exit(1)

spec = importlib.util.spec_from_file_location('pdf_timetable_parser', str(parser_path))
mod = importlib.util.module_from_spec(spec)
import sys as _sys
# ensure module name is available during dataclass processing
_sys.modules['pdf_timetable_parser'] = mod
spec.loader.exec_module(mod)

parse_pdf_streaming = getattr(mod, 'parse_pdf_streaming')
normalise_unit_code = getattr(mod, 'normalise_unit_code')

out_path = Path('parsed_slots.jsonl')
count = 0
with out_path.open('w', encoding='utf-8') as out:
    for batch, page, table in parse_pdf_streaming(pdf_path, chunk_size=100):
        if page == -1:
            break
        for s in batch:
            d = {
                'cohort_label': s.cohort_label,
                'day': s.day,
                'start_time': f"{s.start_time}:00",
                'end_time': f"{s.end_time}:00",
                'unit_code': normalise_unit_code(s.unit_code_raw),
                'venue': f"{s.venue} {s.room}" if s.venue else None,
                'source_page': s.page,
                'raw': s.raw_cell_text,
            }
            out.write(json.dumps(d, ensure_ascii=False) + '\n')
            count += 1
print(f"Wrote {count} slots to {out_path}")
