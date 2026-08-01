# DUHS checksum mismatch investigation

Verdict: **FIXED**

## Root cause

The Windows download store opened staging, commit, and final artifact file
descriptors without `O_BINARY`. Windows CRT text translation therefore changed
the byte stream seen by DingDongDitch hashing. Both pre-commit and post-commit
verification used the same translated stream and agreed with each other, while
the completed file contained different raw bytes. The original receipt
therefore reported a logical/text-translated SHA-256 rather than the SHA-256 of
the physical committed PDF.

The investigation also reproduced an integrity alias: hard-linking the
producer-owned staging inode into completed storage allowed a retained writable
producer handle to mutate a completed artifact after receipt issuance.

## Correction

All download-store descriptors now explicitly use binary mode on Windows.
Commit copies verified staging bytes into a new runtime-owned inode, checks the
source identity and copied SHA-256, atomically publishes that inode, and
re-verifies the completed artifact before issuing the receipt.

## Verification

- Download contract: 36 passed, 1 platform-conditional symlink skip
- Full unit suite: 195 passed, 1 platform-conditional skip
- Real download integration tests: 3 passed
- Selected cross-engine compatibility group: 36 passed, 3 pre-existing
  standalone-fill failures
- The three compatibility failures reproduce in isolation across Chromium,
  Firefox, and WebKit and do not execute download storage.

Fresh DUHS headed rerun:

- Plan verdict: VERIFIED
- Download state: completed
- Size: 208,820 bytes
- MIME: application/pdf (content signature)
- Receipt SHA-256:
  `77148cda1582384be5fa29f751460625e991af36cf0e94971a9081bdaa6d3bbe`
- Independent committed-file SHA-256:
  `77148cda1582384be5fa29f751460625e991af36cf0e94971a9081bdaa6d3bbe`
- Completed PDFs: 1
- Staging files: 0
- Cleanup errors: 0
- DingDongDitch-owned processes after stop: 0
