# Weather Alert Watch

Terminal National Weather Service alert and conditions viewer for the ZIP-derived local area.

Run `python3 weather_ui.py`. The first interactive launch asks for a five-digit United States ZIP code. Change it later with `python3 weather_ui.py --set-zip [ZIP_CODE]`.

Run `python3 collect.py` to fetch current conditions and alerts. This project uses only the Python standard library.

Generated SQLite history, logs, and local location settings are excluded from source control.
