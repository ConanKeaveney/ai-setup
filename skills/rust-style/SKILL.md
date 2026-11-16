---
name: rust-style
description: >-
  How to write Rust on this machine: error handling, lints, sync-first, unsafe,
  security defaults for HTTP, downloads, parsers and durable writes,
  performance, testing patterns, dependency picks, and a list of Rust gotchas
  (serde flatten, atomics ordering, BufWriter drop, float casts, edition 2024
  unsafe forms). Load BEFORE writing or reviewing Rust code in any project.
  Triggers on "Rust", "cargo", "crate", "clippy", "unsafe", "serde", "thiserror",
  "anyhow", "memmap", "criterion", "rust-dev". Coding rules only.
---

# Rust style

## Conventions

- Shared dependencies go in the root `[workspace.dependencies]`; members use `dep.workspace = true`.
- Edition 2021+. Run `cargo fmt`. `cargo clippy --all-targets` must be clean; fix rather than `#[allow]`, unless the lint is wrong, then say why in the commit message.
- `anyhow::Result` at binary boundaries, `thiserror` for library errors callers match on.
- Library code never panics on input data: no `unwrap()`/`expect()` on values from files, network or user input.
- Stay synchronous unless the task calls for async. Do not add tokio casually.

## Security defaults

- HTTP clients never inherit proxy settings from the environment. Set the proxy explicitly (`.proxy(None)` for loopback), set `max_redirects(0)` unless redirects are needed, and set a global timeout. `NO_PROXY=localhost` does not cover `127.0.0.1`.
- Pin every downloaded artefact to a fixed revision, never a moving ref like `main`. Verify its sha256 and size before loading. Write to a temp name unique to the writer, then rename.
- A timeout covers the whole operation, including prepare, plan and bind. Never report a limit or duration you did not enforce.
- Arithmetic on input values uses `checked_*`; release builds wrap silently. Validate calendar dates instead of letting them roll over.
- Never format a path with `{:?}` or `{}` into a shell command a person will paste. Shell-quote it, or print the path on its own line.
- Every `unsafe` block has a `// SAFETY:` comment stating its invariant. A memory-mapped file must not be shortened while mapped; check its length before scanning if anything outside the process can touch it.
- Durable replace is: write, fsync the file, rename, fsync the directory. Apply it on every path, not most.
- A local HTTP server pins an accepted `Origin` to its own host and port, sets a read timeout, and never lets one request hold the only handler thread unbounded.
- Destructive operations are logged with what they matched, and a match-everything scope is refused unless explicitly confirmed.
- A filesystem path taken from a request or config is validated: refuse the store's own directory, the home root and system directories, not just relative paths.
- Untrusted-file parsers cap the input size before reading it, and cap every derived allocation (decompressed bytes, rows times columns, cloned strings) before building it, not after.
- A parser never rescans to the end of its input for each token. Test every parser at three input sizes, each four times the last, and fail on superlinear growth.
- A size or pixel check works for every format the code accepts; refuse what it cannot measure.

## Performance

- Measure before optimizing: `criterion` benches for hot paths, under `benches/`.
- State the latency budget in the bench file when the task defines one.
- Prefer memory-mapped I/O (`memmap2`) and contiguous layouts for scan-heavy data. `half::f16` for storage, f32 for math.
- For SIMD, start with auto-vectorizable plain loops and `#[inline]`; use intrinsics or `std::simd` only when a bench proves the loop insufficient.
- No per-item statements in a loop: fetch what a batch of documents needs in one set-based query, and insert rows in batches with prepared statements.
- Cache data that changes rarely (catalogs, function lists, file censuses) with an explicit invalidation trigger; never recompute it on every request.
- Skip an expensive stage when its result cannot change the outcome, such as reranking a result that is already refused.
- Long-lived processes set explicit memory and thread limits on embedded engines (DuckDB `memory_limit`/`threads`, ONNX arenas); defaults size themselves to the whole machine and never give memory back.
- Load each model once per process and share the session; never open a second copy for another code path.
- Every long-lived map, set or cache has a bound or a pruning path; a detached thread never outlives the work it was started for.

## Testing

- Run only the tests the change calls for: the tests that exercise the files you changed, your negative controls, and fmt and clippy for the touched crates. Run a package-wide or workspace suite only when the change touches `brain-core`, `brain-store`, the lockfile, or several crates. A reviewer re-runs the author's controls, not the suite.
- Unit tests colocated in `#[cfg(test)] mod tests`; integration tests in `tests/` for the public API.
- Use real data samples only when the task provides a corpus and the repo permits it; synthetic fixtures for edge cases (empty input, invalid UTF-8, truncated files).
- Every failure path has a test proving it fails loudly (returns Err or quarantines), not silently.
- UPDATE/DELETE get a bystander test: insert two rows, change one, assert the other is unchanged.
- Upserts test both the insert and the update branch, and assert untouched columns stayed untouched.
- `IN (...)` lists get an empty case and one larger than the batch size; paginated reads are walked to the empty final page.
- Assert against the row read back from storage, never an auto-increment counter or affected-rows count.

## Dependencies

- Lean by default: std plus small focused crates. Justify every new dependency in the report.
- Known-good picks on this machine: `duckdb` (bundled; the first compile is slow), `tantivy`, `memmap2`, `half`, `ort`, `tokenizers`, `walkdir`, `rayon` (only when parallelism is measured to matter).

## Gotchas

- serde: `deny_unknown_fields` is not supported together with `flatten`, on either the outer struct or the flattened one; do not rely on it there.
- serde: `flatten` buffers the input into an intermediate map, which is slower and fails with non-self-describing formats such as bincode.
- serde: a newtype that must be validated deserializes through `#[serde(try_from = "String")]`, so an invalid value cannot be constructed.
- serde: a custom format uses `#[serde(with = "module")]`, never `serialize_with` alone, so it round-trips.
- Casts: integer `as` truncates and float-to-int `as` saturates with NaN becoming 0; narrow with `try_from` and handle the error.
- Floats sort with `total_cmp`, never `partial_cmp(..).unwrap()`.
- Atomics: `Relaxed` only for a value nobody synchronises other memory on, such as a statistics counter; publishing data to another thread is a `Release` store paired with an `Acquire` load.
- `BufWriter` finishes with `into_inner()?` or `flush()?`; a flush during drop discards its error.
- Unsafe: run Miri with `MIRIFLAGS=-Zmiri-strict-provenance` on code whose `unsafe` changed, where it can run.
- Unsafe: build uninitialized arrays with `[const { MaybeUninit::uninit() }; N]`.
- Edition 2024: `std::env::set_var`/`remove_var` are `unsafe` (call them only before threads start, or only in tests); extern blocks are `unsafe extern`; `no_mangle`, `export_name` and `link_section` are written `#[unsafe(...)]`.
- Statics: `std::sync::LazyLock`/`OnceLock`, not `lazy_static` or `once_cell`.
- Compile-time checks: `const _: () = assert!(size_of::<T>() == N);` pins a hot struct's size; `const { assert!(..) }` works inside generic functions.
- Frozen collections: `Box<[T]>` and `Box<str>` are two words, `Vec`/`String` three.
- `macro_rules!`: refer to items through `$crate::`, accept a trailing comma with `$(,)?`, and keep helpers the expansion needs under `#[doc(hidden)] pub mod __private`.
- Lints: a lint group in `[lints]` needs `priority = -1` for individual lints to override it; a custom `cfg` needs `unexpected_cfgs = { level = "warn", check-cfg = ['cfg(name)'] }`.
