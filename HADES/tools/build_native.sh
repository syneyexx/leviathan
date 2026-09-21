#!/usr/bin/env sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CXX="${CXX:-g++}" cmake -S "$root/native" -B "$root/native/build/linux-release" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build "$root/native/build/linux-release" --parallel
ctest --test-dir "$root/native/build/linux-release" --output-on-failure
cmake --install "$root/native/build/linux-release" --prefix "$root"
