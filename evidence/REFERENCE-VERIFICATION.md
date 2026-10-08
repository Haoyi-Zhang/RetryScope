# Reference verification ledger

68 unique bibliography keys.

## `boto-retries`
- Basis: Official language guide
- Metadata: AWS corporate documentation; no invented publication year; accessed 2026-09-30; live guide 1.43.105, not executed 1.43.18.
- Supported claim / limit: Config max excludes first; total includes it. Live documentation cross-checked against installed args.py.
- Identifier: https://docs.aws.amazon.com/boto3/latest/guide/retries.html
- Checked: 2026-09-30; rechecked: 2026-10-03

## `aws-cross-sdk`
- Basis: Official SDK reference
- Metadata: AWS corporate documentation; accessed 2026-09-30.
- Supported claim / limit: New retry behavior is conditional on opt-in; not an unconditional current Python default.
- Identifier: https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html
- Checked: 2026-09-30; rechecked: 2026-10-03

## `aws-announcement`
- Basis: Official repository announcement
- Metadata: millems, 2026-05-20; exact discussion title and number 4789 checked.
- Supported claim / limit: Opt-in available from botocore 1.43.3; rollout no sooner than Nov 2026. Does not establish actual installed state.
- Identifier: https://github.com/boto/boto3/discussions/4789
- Checked: 2026-09-30; rechecked: not separately recorded

## `boto-source`
- Basis: Installed source
- Metadata: botocore 1.43.18 distribution attribution and metadata; descriptive software-source title, not a research article.
- Supported claim / limit: Four files, exact bytes/hash in environment.json; config-provider constant evaluated at import.
- Identifier: evidence/environment.json and evidence/source-snapshots/
- Checked: 2026-09-30; rechecked: not separately recorded

## `requests-doc`
- Basis: Official Requests documentation
- Metadata: Requests project authorship; accessed 2026-09-30; live page not a historical release pin.
- Supported claim / limit: Timeout is not the entire-response download limit.
- Identifier: https://requests.readthedocs.io/en/latest/user/quickstart/
- Checked: 2026-09-30; rechecked: not separately recorded

## `requests-source`
- Basis: Installed source
- Metadata: Requests 2.32.5 package metadata and unmodified adapters.py/models.py.
- Supported claim / limit: Descriptive title identifies retained files; source-backed response/adapter control flow.
- Identifier: evidence/environment.json and evidence/source-snapshots/
- Checked: 2026-09-30; rechecked: not separately recorded

## `urllib-old`
- Basis: Installed vendored source
- Metadata: urllib3 1.26.20 and Requests 2.32.3 inside pip 25.1.1; exact module identities captured at execution.
- Supported claim / limit: Not standalone historical wheels; release-tagged licenses checked separately. No assertion about all pip patches.
- Identifier: evidence/environment.json and evidence/source-snapshots/
- Checked: 2026-09-30; rechecked: not separately recorded

## `urllib-new`
- Basis: Installed source
- Metadata: urllib3 2.7.0 package metadata and retained response/retry/timeout source.
- Supported claim / limit: Public enforcement option, retry and timeout mechanics; title is descriptive source inventory.
- Identifier: evidence/environment.json and evidence/source-snapshots/
- Checked: 2026-09-30; rechecked: not separately recorded

## `smart551`
- Basis: Public issue body + API metadata
- Metadata: mpenkov; 2020-10-24; smart_open does not recover from connection errors when reading from S3; issue 551.
- Supported claim / limit: S3 body-read failure stack; exact affected release missing. Historical problem, not a new defect.
- Identifier: https://github.com/piskvorky/smart_open/issues/551
- Checked: 2026-09-30; rechecked: not separately recorded

## `smart552`
- Basis: Public PR body + merge metadata
- Metadata: mpenkov; opened 2020-10-25, merged 2021-01-15; Improve robustness of S3 reading; PR 552.
- Supported claim / limit: Merge 4f301d62aabf7b9fd15d6ef4118a776eba932522; multiple retries/backoff. Bibliography year denotes opening, note gives merge.
- Identifier: https://github.com/piskvorky/smart_open/pull/552
- Checked: 2026-09-30; rechecked: not separately recorded

## `smart784`
- Basis: Public issue body + API metadata
- Metadata: mweinelt; 2023-09-20; Test failures with urllib3 2.0.4; issue 784.
- Supported claim / limit: Reported 1.26.16 to 2.0.4. Intro says smart_open 0.4.0 while version section says 6.4.0; inconsistency not silently corrected.
- Identifier: https://github.com/piskvorky/smart_open/issues/784
- Checked: 2026-09-30; rechecked: not separately recorded

## `smart-source`
- Basis: Installed source
- Metadata: smart_open 7.6.1; S3 reader file and distribution metadata.
- Supported claim / limit: Current read retry/reopen mechanism executed; not original 2020 binary.
- Identifier: evidence/environment.json and evidence/source-snapshots/
- Checked: 2026-09-30; rechecked: not separately recorded

## `requests1855`
- Basis: Public issue body + API metadata
- Metadata: patricklaw; 2014-01-10; exact long title and issue 1855 checked.
- Supported claim / limit: Complete-body requirement motivation, no exact Requests version supplied in the original body.
- Identifier: https://github.com/psf/requests/issues/1855
- Checked: 2026-09-30; rechecked: not separately recorded

## `hf-source`
- Basis: Installed source
- Metadata: huggingface_hub 1.16.1; utils/_http.py and hf_api.py with package metadata.
- Supported claim / limit: Actual helper and metadata calls; not a replay of a later authentication/DNS report.
- Identifier: evidence/environment.json and evidence/source-snapshots/
- Checked: 2026-09-30; rechecked: not separately recorded

## `retrying-source`
- Basis: Installed source
- Metadata: retrying 1.4.2; actual retrying.py plus metadata.
- Supported claim / limit: Actual outer wrapper used; name/version/source, not substituted Tenacity results.
- Identifier: evidence/environment.json and evidence/source-snapshots/
- Checked: 2026-09-30; rechecked: not separately recorded

## `tenacity`
- Basis: Project README
- Metadata: Tenacity project attribution; accessed 2026-09-30; no invented fixed release year.
- Supported claim / limit: stop_after_attempt, stop_after_delay and stop_before_delay context inspected. Dependency not installed or executed.
- Identifier: https://github.com/jd/tenacity
- Checked: 2026-09-30; rechecked: not separately recorded

## `futures`
- Basis: Official Python documentation
- Metadata: Python Software Foundation; current docs inspected, executions CPython 3.13.5.
- Supported claim / limit: Future timeout, cancellation and context-manager shutdown semantics. Current docs not represented as version-pinned old docs.
- Identifier: https://docs.python.org/3/library/concurrent.futures.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `rfc9112`
- Basis: Original IETF standard
- Metadata: Roy T. Fielding, Mark Nottingham, Julian Reschke; HTTP/1.1; June 2022; RFC9112; DOI 10.17487/RFC9112.
- Supported claim / limit: Length-delimited incomplete-response framing; does not itself mandate a particular Python retry predicate.
- Identifier: https://datatracker.ietf.org/doc/html/rfc9112
- Checked: 2026-09-30; rechecked: not separately recorded

## `amplification`
- Basis: Original preprint abstract + full HTML
- Metadata: Rishabh Mehan and Jasmit Kaur Saluja; full title checked; 2026; arXiv:2608.25403v1; DOI 10.48550/arXiv.2608.25403.
- Supported claim / limit: Census/simulation/adaptive budgeting distinct from this local version/intent study. Preprint, not asserted peer-reviewed.
- Identifier: https://arxiv.org/abs/2608.25403
- Checked: 2026-09-30; rechecked: not separately recorded

## `filibuster`
- Basis: Original author preprint PDF and metadata
- Metadata: Michael Assad, Christopher S. Meiklejohn, Heather Miller, Stephan Krusche; exact title; ICSE Companion 2024; DOI 10.1145/3639478.3640021; arXiv:2404.01886.
- Supported claim / limit: Full PDF inspected including figures; fault injection/visualization comparison, not an executed baseline. PDF not redistributed.
- Identifier: https://arxiv.org/abs/2404.01886
- Checked: 2026-09-30; rechecked: not separately recorded

## `tfix`
- Basis: Original arXiv metadata and abstract
- Metadata: Jingzhu He, Ting Dai, Xiaohui Gu; TFix+: Self-configuring Hybrid Timeout Bug Fixing for Cloud Systems; 2021; arXiv:2110.04101; DOI 10.48550/arXiv.2110.04101.
- Supported claim / limit: Only abstract-level methodology comparison supported; full paper not retrieved. No unverified evaluation claims imported.
- Identifier: https://arxiv.org/abs/2110.04101
- Checked: 2026-09-30; rechecked: not separately recorded

## `intramorphic`
- Basis: Official ACM Digital Library DOI record, SPLASH 2022 program record, and linked arXiv metadata
- Metadata: Manuel Rigger and Zhendong Su; Intramorphic Testing: A New Approach to the Test Oracle Problem; Onward! 2022; pages 62--76; DOI 10.1145/3563835.3567662. The arXiv record identifies this DOI as the related published version.
- Supported claim / limit: Methodological oracle comparison only; no claim to reproduce their implementation or empirical results.
- Identifier: https://doi.org/10.1145/3563835.3567662
- Checked: 2026-10-03; rechecked: not separately recorded

## `tang`
- Basis: Springer publisher article record
- Metadata: Xunzhu Tang, Haoye Tian, Pingfan Kong, Saad Ezzini, Kui Liu, Xin Xia, Jacques Klein, and Tegawendé F. Bissyandé; App review driven collaborative bug finding; Empirical Software Engineering 29, article 124; 2024; DOI 10.1007/s10664-024-10489-x.
- Supported claim / limit: Methodological report-to-validation connection only; not an extension of their algorithm, evidence of private data, or assertion of work by a named collaborator.
- Identifier: https://doi.org/10.1007/s10664-024-10489-x
- Checked: 2026-10-03; rechecked: not separately recorded

## `pooch-paper`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: All eight authors, exact title, 2020, 5(45):1943, DOI checked against JOSS and project citing page.
- Supported claim / limit: Scientific-data fetching and hash registry, not a production validation of RetryScope.
- Identifier: https://joss.theoj.org/papers/10.21105/joss.01943
- Checked: 2026-09-30; rechecked: not separately recorded

## `pooch-create`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: retry_if_failed counts retries after the first; native Pooch retry and hash settings. Executed 1.9.0.
- Identifier: https://www.fatiando.org/pooch/latest/api/generated/pooch.create.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `pooch-hashes`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Known registry digest versus explicit None bypass; unchecked corruption is not a Pooch bug.
- Identifier: https://www.fatiando.org/pooch/latest/hashes.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `pooch-downloaders`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Supported downloader callback is the integration point; no private source patch.
- Identifier: https://www.fatiando.org/pooch/latest/downloaders.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `fsspec-api`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: HTTPFileSystem and file interfaces; live docs newer than installed 2026.4.0, installed source retained.
- Identifier: https://filesystem-spec.readthedocs.io/en/latest/api.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `fsspec-features`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Random access, buffering and cache_type=none; extra healthy ranged requests are not necessarily retries.
- Identifier: https://filesystem-spec.readthedocs.io/en/latest/features.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `aiohttp-ref`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: ClientTimeout total versus sock_read; documentation contrast, not an aiohttp deadline experiment. Installed 3.13.3; live 3.14.3.
- Identifier: https://docs.aiohttp.org/en/stable/client_reference.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `urllib-migration`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Release migration context; actual available comparison is 1.26.20 vendored versus 2.7.0, not original report wheels.
- Identifier: https://urllib3.readthedocs.io/en/stable/v2-migration-guide.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `urllib-changelog`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Content length enforcement and version history; release notes are not proof of local behavior.
- Identifier: https://urllib3.readthedocs.io/en/stable/changelog.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `urllib-util`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Retry/Timeout argument semantics; numeric total does not alone establish operation-wide deadline.
- Identifier: https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `urllib-response`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: HTTPResponse length enforcement and incremental consumption; do not conflate framing with object identity.
- Identifier: https://urllib3.readthedocs.io/en/stable/reference/urllib3.response.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `requests-advanced`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Response hooks, streaming response consumption and connection reuse; instrumentation through supported hooks.
- Identifier: https://requests.readthedocs.io/en/latest/user/advanced/
- Checked: 2026-09-30; rechecked: not separately recorded

## `httpx-timeouts`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Connect/read/write/pool timeouts; actual async experiment uses HTTPX 0.28.1.
- Identifier: https://www.python-httpx.org/advanced/timeouts/
- Checked: 2026-09-30; rechecked: not separately recorded

## `httpx-transports`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Built-in retry applies to connect error/timeout; transport retries explicitly zero in actual async comparison.
- Identifier: https://www.python-httpx.org/advanced/transports/
- Checked: 2026-09-30; rechecked: not separately recorded

## `httpx-exceptions`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Different transport, protocol, HTTP-status exception classes; matching timeout names does not imply matching predicates.
- Identifier: https://www.python-httpx.org/exceptions/
- Checked: 2026-09-30; rechecked: not separately recorded

## `google-retry`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Retry timeout checked before starting an attempt; docs-only semantic contrast, not executed here.
- Identifier: https://googleapis.dev/python/google-api-core/latest/retry.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `storage-retry`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Language-specific retry and conditional-idempotency policies; no Google Cloud execution or claim of universal settings.
- Identifier: https://docs.cloud.google.com/storage/docs/retry-strategy
- Checked: 2026-09-30; rechecked: not separately recorded

## `grpc-deadlines`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: RPC deadline and server application responsibility for work after cancellation; not evaluated with gRPC.
- Identifier: https://grpc.io/docs/guides/deadlines/
- Checked: 2026-09-30; rechecked: not separately recorded

## `grpc-retry`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Retry policy, backoff and RPC commitment; documentation contrast, not another experimental stack.
- Identifier: https://grpc.io/docs/guides/retry/
- Checked: 2026-09-30; rechecked: not separately recorded

## `aws-builders`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Author Marc Brooker, exact title, original 2015-03-04 and explicit 2023 update verified; not confused with 2026 Builder Center republication.
- Supported claim / limit: Established backoff/jitter practice, not a new policy introduced here.
- Identifier: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- Checked: 2026-09-30; rechecked: not separately recorded

## `aws-idempotent`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Read-only study cannot establish safe replay of side-effecting calls; no original publication year invented.
- Identifier: https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/
- Checked: 2026-09-30; rechecked: not separately recorded

## `sre-overload`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: SRE chapter 21 gives production overload context; local call counts do not measure overload protection.
- Identifier: https://sre.google/sre-book/handling-overload/
- Checked: 2026-09-30; rechecked: not separately recorded

## `sre-cascading`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: SRE chapter 22 context; no inference of outage reduction from local experiments.
- Identifier: https://sre.google/sre-book/addressing-cascading-failures/
- Checked: 2026-09-30; rechecked: not separately recorded

## `asyncio`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: asyncio.timeout cooperative cancellation and wait_for cleanup semantics. CPython 3.13.5 actually executed, docs later 3.13 patch.
- Identifier: https://docs.python.org/3.13/library/asyncio-task.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `socket`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Socket timeout phase is not universal DNS/connect/read/cleanup cancellation; no DNS/TLS experiment.
- Identifier: https://docs.python.org/3.13/library/socket.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `http-client`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: HTTP response reading is a separate operation; body observation not inferred from headers.
- Identifier: https://docs.python.org/3.13/library/http.client.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `hashlib`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: SHA-256 used as ordinary whole-buffer validation, not a novel digest algorithm.
- Identifier: https://docs.python.org/3.13/library/hashlib.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `tempfile`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Title and attribution checked on the primary source; undated documentation has no invented publication year.
- Supported claim / limit: Temporary staging/cleanup API supports Pooch inspection; no claimed crash durability.
- Identifier: https://docs.python.org/3.13/library/tempfile.html
- Checked: 2026-09-30; rechecked: not separately recorded

## `rfc9110`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Three editors, title, June 2022, RFC and DOI checked on IETF.
- Supported claim / limit: Range, Content-Range and representation identity semantics used by the bounded fixture.
- Identifier: https://datatracker.ietf.org/doc/html/rfc9110
- Checked: 2026-09-30; rechecked: not separately recorded

## `rfc6585`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Authors, title, April 2012, RFC and DOI checked at RFC Editor.
- Supported claim / limit: 429 and Retry-After are outside our 400/503 local fixture; never prescribe universal status lists.
- Identifier: https://www.rfc-editor.org/info/rfc6585/
- Checked: 2026-09-30; rechecked: not separately recorded

## `sfit`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Author PDF first page inspected; all five authors, SoCC 2021, exact DOI verified.
- Supported claim / limit: Fault exploration differs from our manually chosen local replay/oracle scope.
- Identifier: https://christophermeiklejohn.com/publications/filibuster-socc-2021.pdf
- Checked: 2026-09-30; rechecked: not separately recorded

## `yuan`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: All eight authors, title, year and page range checked against USENIX BibTeX.
- Supported claim / limit: Error-handling investigation motivates discriminating local fault tests; no reuse of its industrial prevalence evidence.
- Identifier: https://www.usenix.org/conference/osdi14/technical-sessions/presentation/yuan
- Checked: 2026-09-30; rechecked: not separately recorded

## `bogart`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Four authors, title, FSE 2016, pages and DOI checked against author PDF, SMU record and ACM metadata.
- Supported claim / limit: API ecosystem study differs from our non-interview behavior audit.
- Identifier: https://www.cs.cmu.edu/~ckaestne/pdf/fse16.pdf
- Checked: 2026-09-30; rechecked: not separately recorded

## `oracle`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Exact title (no additional Test prefix), five authors, 2015 volume/issue/pages checked against McMinn official BibTeX; DOI link identified.
- Supported claim / limit: Explicit intent does not infer requirements; observed old behavior is not ground truth.
- Identifier: https://philmcminn.com/publications/
- Checked: 2026-09-30; rechecked: not separately recorded

## `tail`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Names, exact title, 2013, CACM 56 and pages verified at Google Research; omitted unverified issue/DOI fields.
- Supported claim / limit: Production latency motivation only, no transfer of local deadline ratios into tail-latency improvement.
- Identifier: https://research.google/pubs/the-tail-at-scale/
- Checked: 2026-09-30; rechecked: not separately recorded

## `end-to-end`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Primary MIT PDF identifies authors and journal 2(4), 1984, pages 277--288. No unverified DOI field.
- Supported claim / limit: End-to-end checksum and retry is established; ordinary SHA-256 baseline is not our novelty.
- Identifier: https://web.mit.edu/Saltzer/www/publications/endtoend/endtoend.pdf
- Checked: 2026-09-30; rechecked: not separately recorded

## `case-study`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Two authors, exact title, 2009 issue (2008 online), pages, DOI verified publisher and Lund record.
- Supported claim / limit: Case context and generalization limits; repetitions are not independent industrial case studies.
- Identifier: https://link.springer.com/article/10.1007/s10664-008-9102-8
- Checked: 2026-09-30; rechecked: not separately recorded

## `runtime-verification`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Three authors, title, TOSEM 20(4), article 14, 2011 and DOI checked at author institution.
- Supported claim / limit: Three-valued runtime monitoring precedes this work; our field-specific completeness is an engineering application, not new temporal logic.
- Identifier: https://research.uni-luebeck.de/de/publications/runtime-verification-for-ltl-and-tltl/
- Checked: 2026-09-30; rechecked: not separately recorded

## `chaos`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Author-submitted paper verifies four names/title; venue/year/pages/DOI cross-checked against proceedings metadata.
- Supported claim / limit: Netflix production experience is distinct evidence; ours not production rollout or field evaluation.
- Identifier: https://arxiv.org/abs/1905.04648
- Checked: 2026-09-30; rechecked: not separately recorded

## `ldfi`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Primary author PDF first page rendered: all three authors, title, SIGMOD 2015 and DOI checked.
- Supported claim / limit: Automated fault selection/lineage is different from manual local fixtures and explicit user-provided ownership.
- Identifier: https://people.ucsc.edu/~palvaro/molly.pdf
- Checked: 2026-09-30; rechecked: not separately recorded

## `rfc9530`
- Basis: Primary publisher, author, standards, or official project source
- Metadata: Two names, exact title, February 2024, RFC and DOI checked at RFC Editor.
- Supported claim / limit: Representation/content digests distinguish identity from framing; not claiming this artifact implements the RFC fields.
- Identifier: https://www.rfc-editor.org/info/rfc9530/
- Checked: 2026-09-30; rechecked: not separately recorded

## `multiprocessing`
- Basis: Official Python 3.13 library documentation
- Metadata: Python Software Foundation documentation; process start, join, terminate, and start-method semantics; accessed 2026-10-04.
- Supported claim / limit: A Process can be joined with a timeout and explicitly terminated; termination skips exit handlers and can corrupt shared IPC or leave descendants, so it is an isolation mechanism with operational costs rather than universal cancellation.
- Identifier: https://docs.python.org/3.13/library/multiprocessing.html
- Checked: 2026-10-04; rechecked: 2026-10-04

## `dapper`
- Basis: Original Google technical report landing page and report PDF
- Metadata: Title, eight authors, report number dapper-2010-1, and April 2010 date checked against the report front page.
- Supported claim / limit: Establishes distributed tracing as prior infrastructure for propagating and joining causal context; it does not provide RetryScope's application-intent audit or finite migration verdicts.
- Identifier: https://research.google/pubs/dapper-a-large-scale-distributed-systems-tracing-infrastructure/
- Checked: 2026-10-07; rechecked: 2026-10-07

## `w3c-trace-context`
- Basis: W3C Recommendation
- Metadata: Recommendation title and publication date 23 November 2021 checked on the W3C specification.
- Supported claim / limit: Defines traceparent/tracestate propagation and identifier syntax. RetryScope uses a standards-shaped traceparent in its bounded fixture but does not claim a complete Trace Context or tracing implementation.
- Identifier: https://www.w3.org/TR/trace-context/
- Checked: 2026-10-07; rechecked: 2026-10-07

## `otel-http`
- Basis: Official OpenTelemetry semantic-conventions specification
- Metadata: HTTP span document and resend-count guidance checked on the official specification page; accessed 2026-10-07.
- Supported claim / limit: Supports one client span per wire attempt and resend-count conventions. It is prior observability infrastructure, not an operation-intent migration oracle.
- Identifier: https://opentelemetry.io/docs/specs/semconv/http/http-spans/
- Checked: 2026-10-07; rechecked: 2026-10-07
