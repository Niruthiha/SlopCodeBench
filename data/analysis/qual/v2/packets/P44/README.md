Packet P44. Task: sith. Checkpoints: 1..6.
trace_digest.md: every tool call as [checkpoint.step] TOOL args -> result head; SAY = agent text; RESULT = session end.
spec/: the prompt given at each checkpoint. code/checkpoint_k/: the code after checkpoint k. diffs/checkpoint_k.patch: what checkpoint k changed.
results/: hidden-test results per checkpoint (failing tests with assertion output). tests/: the benchmark test files.
Each checkpoint was a fresh agent session that saw only the code left by the previous one.
