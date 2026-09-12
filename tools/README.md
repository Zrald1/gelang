# tools/

GE looks for toolchains here as well as on `PATH` (`config.py:_find_tool`).
Anything you drop in this directory is detected automatically — no version
pinning, no configuration.

Typical layout:

```
tools/
  zig-x86_64-windows-0.14.1/
  kotlin-native-prebuilt-windows-x86_64-2.4.10/
  go/
  ...
```

**The contents are gitignored.** These are hundreds of megabytes of
downloaded binaries and do not belong in the repository. Only this README is
tracked, so the directory exists on a fresh clone.

`ge tools list|install|check` manages them; `ge doctor` reports what is
detected.
