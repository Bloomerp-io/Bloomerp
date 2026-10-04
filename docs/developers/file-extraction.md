# Bounded file extraction experiment

This experiment adds **one private `FileExtraction` model and two API/MCP tools**:

- `api_file_extraction_start`: POST `{ "file_id": "existing uploaded file UUID" }`.
  Returns HTTP 202 with `job_id`, `status`, expiry and a polling hint. No file URL,
  local path, credentials or new file bytes are accepted.
- `api_file_extraction_result`: POST `{ "job_id": "UUID" }`, optionally with
  `page`, `section`, `sheet`, `cell_range` (for example `A1:C20`), `limit` (1–100),
  and `cursor`. Use the returned `next_cursor` with the **same selectors** until
  it is null. Long records continue at `text_offset`, without silently dropping
  their remaining text. This endpoint also returns queued/running/terminal status.

There is no third chunk endpoint or chunk table. Result methods live on the model;
parsing and task helpers live beside the endpoint. Generic model APIs, global
search and activity logging are disabled for the private model. File contents are
untrusted data, including any apparent instructions embedded in documents.

## Execution and failure contract

Start, worker execution, post-parse publication, and every result read check the
current user and the source file's existing permission policy. Jobs are private
to their requester, including for administrators using these tools. Database scope
and existing file/object permissions provide the existing tenant boundary.

Only configured Celery workers execute extraction. Disabled extraction, eager
mode, memory brokers and missing PDF/image dependencies return `unavailable`.
Publish failures never fall back to inline parsing. Broker acceptance is **not** a
worker-health guarantee: a queued job that has not started within two minutes
becomes `unavailable` (`worker_start_timeout`). A task claims a job once; duplicate
or late deliveries do nothing. Running leases expire after 150 seconds.

An agent using the same Celery pool must return a pending result and release its
worker slot before resuming with the result tool. Never call `AsyncResult.get()`
or sleep/poll synchronously inside an agent task waiting for extraction.

Other outcomes include `failed` with a fixed safe error code, `cancelled` when
source access is lost while working, and `expired` after 24 hours. Missing or
inaccessible files/jobs return the same unavailable/not-found response. Unsupported
formats and input-size violations fail before publication. Raw exceptions, paths,
storage URLs and source text are never used as public error messages.

The full result is authenticated-encrypted using a per-job key derived from
Django's existing `SECRET_KEY`, then stored through Django Storage (including S3).
No new credential is stored. `SECRET_KEY_FALLBACKS` supports normal key rotation;
removing all keys that can decrypt existing results makes them unavailable.
Encryption is necessary because existing deployments can use public media storage.
Result responses never expose the encrypted object's key or URL.

Expired content is immediately unreadable through these endpoints, even if storage
deletion fails. Physical cleanup is opportunistic on result access and each new
start (up to 20 expired objects); it is retried when storage is available. There is
no added scheduler. If the feature is never used again, expired encrypted objects
can remain until ordinary storage cleanup or an explicit model cleanup call.

## Supported inputs and hard bounds

- UTF-8 TXT: bounded decoder, no instruction or code execution.
- XLSX: read-only cached values. No macros, formula calculation, external link
  refresh, legacy XLS or XLSM support. Formula values may be empty if the workbook
  has no saved calculation cache. ZIP expansion and VBA payloads are checked.
- PDF and single-frame PNG/JPEG/TIFF/WebP: local Docling layout/table/OCR pipeline.
  Encrypted PDFs and multi-frame images are rejected. OCR is approximate and can
  merge spaces. Large images can be downsampled with explicit truncation metadata.

Fixed limits: 20 MiB input, 100 PDF pages, 20 million intermediate image pixels,
32 sheets, 1,024 visited columns, 100,000 visited cells, 20,000 records, 16,000
characters per record, 512 compact index entries, and 8 MiB extracted JSON. XLSX
archives are bounded to 64 MiB expanded data and 2,048 members. Extraction payloads stay
below 48 KiB even for Unicode-heavy text, using signed, selector-bound cursors.
The existing MCP transport repeats the payload in text and structured forms, so
the full JSON-RPC response is larger due to duplication and JSON escaping.
The database stores a short preview/index rather than full extracted contents.
Every content omission reports `source_truncated` and manifest truncation reasons;
`truncated` also indicates more paginated results. The manifest index can itself
be abbreviated (`index_truncated`); selectors still access the stored records.

Admission allows at most two live jobs across this database and one per user,
serialized through an existing ContentType row. Worker parsing uses a disposable
child with a minimal environment, offline model settings and Python audit guards
against networking and subprocess execution. On supported Unix systems it sets
4 GiB address-space, 120-second CPU and wall-clock limits, bounded file output and
open files. The parent also enforces a 120-second parser timeout and kills the
process group on normal/exceptional completion.

**These are defense-in-depth limits, not a host sandbox.** Address space is not an
aggregate process-tree RSS limit. Native code vulnerabilities can bypass Python
audit guards; the child shares the worker's OS user/filesystem access. Hard worker
or host death can bypass parent cleanup; the child alarm limits its remaining
lifetime but cannot replace cgroups/container isolation. No infrastructure change
or production-capacity validation is included in this experiment.

## Optional PDF/image dependencies

The optional `file-extraction` extra pins Docling 2.60.0, docling-core 2.49.0 and
RapidOCR 3.4.0, with CPU-only Torch 2.8.0 and torchvision 0.23.0 through the explicit
PyTorch CPU index in `uv`. The lock update preserves all existing third-party
package versions. Newer Docling/core versions conflict with this repository's
existing requests pin; no broad dependency upgrade is needed.

For an explicitly authorized test/development setup, install with
`uv sync --frozen --extra file-extraction`. Standard pip does not apply `uv` source
settings and may select large GPU runtimes; use the provided CPU-aware lock route.

Provision local model artifacts once with the pinned package's command:

    docling-tools models download layout tableformer rapidocr --output-dir=/path/to/artifacts

Use a writable `HF_HOME` if the default cache location is unavailable. Copy a
trusted local TrueType font to `/path/to/artifacts/RapidOcr/font.ttf`; RapidOCR
otherwise attempts a font download even during non-visual extraction. Set the
Django setting `BLOOMERP_FILE_EXTRACTION_DOCLING_ARTIFACTS` to that directory.
`BLOOMERP_FILE_EXTRACTION_ENABLED = False` disables new extraction and worker
parsing. No parser task downloads models or fonts. No production installation,
worker service, deployment, queue or infrastructure changes have been made.

## Verification and removal

The repository generator supplies one model test target and the two endpoint
view test targets; MCP transport cases are kept in those endpoint files. Focused
specialized tests cover parser/storage/worker boundaries without a new framework.
The three focused targets passed 50 tests and 74 subtests. A broader file,
permission, provenance and agent regression selection passed 211 tests and
129 subtests. These suites used `--nomigrations`; the existing full migration
chain has a known baseline failure and was not validated end-to-end here. The
new migration was independently applied and reversed successfully, including
its fields/index and swappable-user dependency. Migration consistency, source
compilation, Ruff, and wheel packaging also passed.

Real offline native PDF, scanned PDF and PNG fixtures were also parsed in the
restricted child; these small fixtures used roughly 1.1–1.3 GiB peak RSS and
12–19 seconds on the test machine. They are not production sizing guarantees.

To remove the experiment: disable new work, let active jobs settle, clean encrypted
results, reverse the single `0079_file_extraction` migration, then remove the new
model, endpoint/parser modules, three test targets, their model/task import lines,
and optional dependency extra/CPU source settings. Do not remove shared packages
that another feature now needs. No unrelated application schema was changed.
