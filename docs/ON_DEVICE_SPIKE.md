# On-device model run (feasibility)

Status: write-up only. Nothing has been benchmarked here; the points below are
what the code already supports and what is still unmeasured.

## What exists today

`apps/field/infer.js` talks to a **local** OpenAI-compatible endpoint (default
`http://127.0.0.1:11434`, the Ollama default; default model `gemma3`). It sends
a photo and a strict-JSON prompt, and gets back `kind`, `species`, `confidence`
and `detail`. The model is swappable; `trust.js` only sees the stamped
`model_id`.

So the device-side pipeline is already "on-device" in the sense that the
network hop stays on the machine. What is not yet true is that the phone or
laptop runs the model itself: today it needs a separate local server.

## What "fully on-device" would mean

Three options, in increasing effort:

1. **Keep the local server, bundle it.** Ship an Ollama/llama.cpp-style runtime
   with the field app for desktop. Lowest effort, no browser change.
2. **Run in the browser.** A WebGPU or WASM runtime inside `apps/field`, so the
   PWA needs no install. Largest unknowns: model size versus download time on a
   field connection, and whether a vision model fits in phone memory.
3. **Native mobile runtime.** Out of scope for the current stack.

## Risks to measure before committing

- **Model size and vision support.** Confirm a vision-capable model under a
  size a phone can load. `gemma3:4b` is the model the tests use; its footprint
  on a target device is unmeasured.
- **Latency.** Time per identification on the target device. No figure exists yet.
- **Accuracy drop.** The observer already confirms or corrects the model
  (`journal.test.mjs`), so a weaker model is survivable, but the correction
  rate has not been measured.
- **Storage and first-run download.** Offline use needs the model cached.

## Recommendation

Do option 1 first. It matches the code, needs no new runtime, and is enough to
prove the claim that identification never leaves the device. Measure latency and
accuracy on one real device before deciding on option 2.

## Not decided

- The target device for the measurement.
- Whether the demo should claim "fully on-device" before option 2 exists. Until
  it is measured, the honest claim is "the model runs on the observer's machine,
  behind a local endpoint."
