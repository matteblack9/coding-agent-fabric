#!/usr/bin/env node

import readline from "node:readline";
import {
  bridgeHealth,
  closeBridgeResources,
  runCodex,
  runOpencode,
} from "./lib/runtime.mjs";

function writeMessage(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

async function dispatch(method, params) {
  switch (method) {
    case "health":
      return bridgeHealth();
    case "run":
      if (params.runtime === "codex") {
        return runCodex(params);
      }
      if (params.runtime === "opencode") {
        return runOpencode(params);
      }
      throw new Error(`Unsupported runtime: ${params.runtime}`);
    default:
      throw new Error(`Unknown method: ${method}`);
  }
}

async function handleLine(line) {
  let message;
  try {
    message = JSON.parse(line);
  } catch (error) {
    writeMessage({
      id: null,
      ok: false,
      error: { message: `Invalid JSON request: ${error.message}` },
    });
    return;
  }

  const { id, method, params = {} } = message;
  try {
    const result = await dispatch(method, params);
    writeMessage({ id, ok: true, result });
  } catch (error) {
    writeMessage({
      id,
      ok: false,
      error: {
        message: error instanceof Error ? error.message : String(error),
      },
    });
  }
}

const rl = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});

rl.on("line", (line) => {
  void handleLine(line);
});

async function shutdown(code = 0) {
  await closeBridgeResources();
  process.exit(code);
}

process.on("SIGINT", () => {
  void shutdown(0);
});
process.on("SIGTERM", () => {
  void shutdown(0);
});
