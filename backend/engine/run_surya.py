"""Surya sandwich PDF builder — standalone script for subprocess invocation.
Usage: python run_surya.py <input_pdf> <output_pdf> [dpi]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from surya_embed import build_sandwich_surya


def main():
    if len(sys.argv) < 3:
        print("Usage: python run_surya.py <input_pdf> <output_pdf> [dpi]", file=sys.stderr)
        sys.exit(1)

    input_pdf = sys.argv[1]
    output_pdf = sys.argv[2]
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    if not os.path.exists(input_pdf):
        print(f"Input PDF not found: {input_pdf}", file=sys.stderr)
        sys.exit(1)

    ok = build_sandwich_surya(input_pdf, output_pdf, dpi=dpi)
    if ok:
        print("OK")
    else:
        print("FAIL", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
