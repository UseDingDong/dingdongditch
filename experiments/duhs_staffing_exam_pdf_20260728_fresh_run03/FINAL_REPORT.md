# Production download benchmark

Verdict: **FAIL**

Source: Dow University of Health Sciences, “ENTRY TEST RECRUITMENT TEST FOR
SENIOR REGISTRAR EXAM – 2026”.

The fresh headed bundled-Chromium session navigated to the public DUHS
examination page, resolved the dedicated visible Download anchor, and triggered
exactly one DingDongDitch DOWNLOAD operation. DingDongDitch returned a VERIFIED
plan receipt with terminal download state `completed`.

Artifact:

- Final filename: `duhs-senior-registrar-recruitment-exam.pdf`
- Final byte size: 208,820
- MIME: `application/pdf`
- MIME source: `content_signature`
- Portable location:
  `completed\duhs-senior-registrar-recruitment-exam.pdf`
- Preserved host location:
  `artifacts\downloads\7a88abe8-1bca-451b-a972-55949287e725\completed\duhs-senior-registrar-recruitment-exam.pdf`
- Receipt SHA-256:
  `6f6d436e675d5b4accb71b5f3f8105dc0862d0be41eb93db25e468c910108480`
- Actual completed-file SHA-256:
  `77148cda1582384be5fa29f751460625e991af36cf0e94971a9081bdaa6d3bbe`

The verdict is FAIL because the receipt checksum does not describe the
completed artifact bytes. The file itself has a `%PDF-` signature, its actual
size agrees with the receipt, and it remains preserved for diagnosis.

Cleanup:

- Completed PDFs: exactly 1
- Staging/partial files: 0
- Browser lifecycle: stopped
- Browser cleanup errors: none
- DingDongDitch-owned Playwright/bundled-browser processes after cleanup: 0

No sign-in, JavaScript injection, direct Playwright action, manual interaction,
or production-code modification was used.
