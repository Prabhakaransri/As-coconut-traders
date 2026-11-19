# AS Coconut Traders

This repository currently contains CI configuration and `.gitignore`, **not the application source code**. The V77/V78 application source must be uploaded before GitHub Actions can execute the application workflow tests. Do not interpret a green syntax-only workflow as a successful application test.

## Local testing

From the extracted software folder, run `python RUN_AUTOMATED_TESTS.py` with Python, Pillow, ReportLab, Tkinter, Xvfb and poppler-utils available. Tests create a temporary database; never commit production `billing.db`, backups, invoices, or customer data.

## Status

Local Linux/Xvfb sample workflow checks have passed, but Windows printing, actual WhatsApp integration, Windows installer and comprehensive UI interactions remain unverified.
