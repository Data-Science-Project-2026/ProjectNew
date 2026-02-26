"""Compatibility stub forwarding to the package implementation.

Prior to the refactor there was a standalone ``src/analyzer.py`` that used
SQLite for ad-hoc experimentation.  That file has been slimmed down to a
wrapper that simply delegates to ``models.BioClip.analyzer``; the heavy
lifting now lives in the BioClip package so the container image can import
it directly and run without any SQLite dependency.
"""

from models.BioClip.analyzer import main


if __name__ == "__main__":
    main()
