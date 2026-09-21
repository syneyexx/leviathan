# Native runtime install location

Built binaries are copied here by `BUILD_HADES_NATIVE.bat` / `tools/build_native.sh`.

Python looks for:

- `hades_native_runtime.exe` (Windows)
- `hades_native_runtime` (POSIX)

Do not point production at `native/build/` directories.
