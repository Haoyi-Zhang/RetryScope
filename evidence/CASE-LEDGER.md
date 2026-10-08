# Case-selection and oracle ledger

The predeclared selection procedure is in `study/protocol.md`; each additional
phase has its own protocol in `study/`. This is purposive source-guided sampling,
not a systematic prevalence census. Discovery cases, repeated evaluation, and
explicit stress tests are distinguished. No independent human annotations or
maintainer confirmation of a new defect are claimed.

| Candidate | Public source / version | Disposition and basis |
|---|---|---|
| AWS new retry policy | https://github.com/boto/boto3/discussions/4789 ; botocore >=1.43.3 opt-in | Included: real 1.43.18 policy false/true in fresh processes; same release, not old/new binaries. |
| Boto3 counting | https://docs.aws.amazon.com/boto3/latest/guide/retries.html ; installed 1.43.18 source | Included documented semantic calibration. Local two-wire cap separately labeled researcher-authored. |
| smart_open S3 body recovery | https://github.com/piskvorky/smart_open/issues/551 and /pull/552 | Included reduced mechanism in 7.6.1. Issue lacks exact old release; no claim of exact historical incident replay. |
| smart_open urllib3 upgrade | https://github.com/piskvorky/smart_open/issues/784 | Included mechanism lead; report's 1.26.16/2.0.4 pair unavailable. Executed available 1.26.20 vendored/2.7.0. Intro 0.4.0 versus version section6.4.0 unresolved, retained explicitly. No original Nixpkgs test replay claimed. |
| Requests body length | https://github.com/psf/requests/issues/1855 and RFC9112 | Included complete-response oracle motivation; local ten-byte identity body fixture. |
| Hub retry helper and model metadata | installed huggingface_hub1.16.1 source, retained/hash-checked | Included helper/entry-point controls. model_info503 has no application retry oracle and returns unknown. Not an independent industrial incident. |
| Hub auth DNS report | https://github.com/huggingface/huggingface_hub/issues/4796 ; reported1.29.0 | Excluded exact replay: unavailable version, auth/DNS path outside local read-only scope. Not replaced by claiming model_info is the same case. |
| Hub download crash | https://github.com/huggingface/huggingface_hub/issues/4349 ; reported1.18.0 | Excluded exact replay: version unavailable and large-download setting disproportionate to bounded CPU/local experiment. |
| PyGithub read timeout | https://github.com/PyGithub/PyGithub/issues/984 | Excluded: dependency unavailable and report lacks an exact affected release. |
| Tenacity | https://github.com/jd/tenacity README | Related maintained tool inspected; not installed/executed. Actual independent Requests wrapper is retrying1.4.2. |

## Contract provenance

Documented: Boto setting distinction, opt-in semantics, Requests inactivity
contract, future shutdown semantics and length-delimited response completeness.
Released-source observations: body reader reopens, actual retry helpers/call paths,
old/new enforcement defaults and botocore import-time policy state.
Researcher-authored: exact one/two-wire application caps, 100ms/150ms whole-read
budgets, the selected retryable status list and required recovery outcomes.
The source defines the semantic boundary; it does not supply these numeric
production requirements. The 300 retained mismatches are not 300 newly discovered defects. A strict
server-only counterfactual on the same executions supports 288 mismatches and
leaves 780 aggregate outcomes unknown; the client-witnessed audit supplies the
missing ownership and cause evidence.

## Unavailable routes and scope consequences

Container package-index and direct dependency retrieval failed due to external
DNS/network limitations. Installed packages provide a scientifically useful real
execution route, but not exact missing historical releases. No wheel installation
is asserted. Google API Core/PyGithub/Tenacity were not executed. Full texts for
TFix+ and Intramorphic Testing were not accessible; only original abstract-level
claims are used. The required retry-amplification preprint was read through its
original HTML route, and the Filibuster-related author PDF was inspected.
No source retrieved through a failed request is counted as verified. Exact identifiers and supported claim levels are in
`REFERENCE-VERIFICATION.json`. This ledger describes the evidence corpus retained
in the package.

## Strong baseline and case independence

The ordinary length-check challenge was added after the main observations and
frozen separately, then executed in 80 runs. Its success is not a held-out
industrial validation result. The 32-run public-option ablation uses the same
local framing mechanism. Timing sensitivity and import diagnostics are also
separate. More rows, seeds and policy states do not create independent downstream
applications. No production impact, financial benefit or adoption was measured.

## Additive current-phase contexts

| Context | Contract or source | Inclusion and interpretation |
|---|---|---|
| Pooch 1.9.0 registry fetch | Official paper, pooch.create, hashes and downloader callback documentation | Actual native fetch, known-hash versus explicit unchecked control. Hash contract is source-backed; 503-only/400 exclusion is a separate local policy, not Pooch's promise. |
| Ordinary identity repair | Actual old/new Requests + length/SHA-256 | Existing baseline, not novel validation or a third-party reported defect. 84 expected outcomes; errors remain distinct from recovery. |
| fsspec 2026.4.0 HTTP reads | Installed HTTP source and API/features; aiohttp 3.13.3 | 36 healthy constituent controls, no reported defect. Cache disabled; fixed size versus metadata. Source-guided roles, not automatic causal inference. |
| smart_open nonzero resume | Installed reader, earlier public recovery context, valid local range responses | 54 interrupted plus 18 healthy operations; correct bytes and offsets. Unobserved internal catch means retry classification remains unknown. |
| HTTPX 0.28.1 + Python 3.13.5 async timeout | HTTPX timeout/transport docs and asyncio contract | 144 actual calls; 48 timeout-context timing passes including close. Cooperative finite measurements, no blanket hard-deadline guarantee. |
| Python synchronous boundaries | `concurrent.futures` and `multiprocessing` contracts | 96 actual calls contrasting timeout notification with a pre-started process boundary; cleanup completion is measured separately from exception delivery. |
| Concurrent causal attribution | Requests and urllib3 client hooks plus independent loopback arrivals | 720 logical operations and 2,160 requests across status retry, nested ownership, constituents, and body recovery. The study tests join correctness under controlled interleaving, not distributed tracing throughput. |

Each phase protocol records its sampling role, fixed configuration grid, and
seeds. The extension, timing, and causal phases are controlled local evaluations,
not blind industrial holdouts. Append-only resume metadata preserves prefix and
source hashes, and no completed operation is replaced.
