#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const MIN_NODE_VERSION = [22, 13, 0];
export const MIN_PYTHON_VERSION = [3, 11, 0];

export function parseVersion(value) {
  const match = String(value ?? "").match(/(\d+)\.(\d+)(?:\.(\d+))?/);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3] ?? 0)];
}

export function versionAtLeast(actual, minimum) {
  if (!Array.isArray(actual) || !Array.isArray(minimum)) return false;
  const width = Math.max(actual.length, minimum.length);
  for (let index = 0; index < width; index += 1) {
    const current = Number(actual[index] ?? 0);
    const required = Number(minimum[index] ?? 0);
    if (!Number.isFinite(current) || !Number.isFinite(required)) return false;
    if (current > required) return true;
    if (current < required) return false;
  }
  return true;
}

export function formatVersion(version) {
  return Array.isArray(version) ? version.join(".") : "unknown";
}

export function checkCurrentRuntimes({
  nodeVersion = process.versions.node,
  pythonExecutable = process.env.HADES_PYTHON || "python",
} = {}) {
  const parsedNode = parseVersion(nodeVersion);
  if (!parsedNode || !versionAtLeast(parsedNode, MIN_NODE_VERSION)) {
    return {
      ok: false,
      message: `Node.js ${nodeVersion || "unknown"} is unsupported; HADES requires >= ${formatVersion(MIN_NODE_VERSION)}.`,
    };
  }

  const pythonProbe = spawnSync(pythonExecutable, ["--version"], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (pythonProbe.error) {
    return {
      ok: false,
      message: `Unable to execute ${pythonExecutable}: ${pythonProbe.error.message}`,
    };
  }
  if (pythonProbe.status !== 0) {
    return {
      ok: false,
      message: `${pythonExecutable} --version failed with exit code ${pythonProbe.status}.`,
    };
  }

  const pythonOutput = `${pythonProbe.stdout || ""}\n${pythonProbe.stderr || ""}`.trim();
  const parsedPython = parseVersion(pythonOutput);
  if (!parsedPython || !versionAtLeast(parsedPython, MIN_PYTHON_VERSION)) {
    return {
      ok: false,
      message: `Python ${parsedPython ? formatVersion(parsedPython) : "unknown"} is unsupported; HADES requires >= ${formatVersion(MIN_PYTHON_VERSION)}.`,
    };
  }

  return {
    ok: true,
    node: parsedNode,
    python: parsedPython,
    pythonExecutable,
  };
}

const invokedDirectly = Boolean(process.argv[1]) && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  const result = checkCurrentRuntimes();
  if (!result.ok) {
    console.error(`[FOUT] ${result.message}`);
    process.exitCode = 1;
  } else {
    console.log(
      `[OK] Runtimeversies: Node.js ${formatVersion(result.node)}; Python ${formatVersion(result.python)}.`,
    );
  }
}
