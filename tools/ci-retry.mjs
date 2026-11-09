#!/usr/bin/env node
// Run a CI command again after a transient failure (#1360).
//
//   node tools/ci-retry.mjs [--attempts=N] [--delay=SECONDS]
//       [--attempt-timeout=SECONDS] [--retry-on=npm-network] COMMAND [ARGS...]
//
// The command runs up to --attempts times, with --delay seconds between
// attempts. Each attempt is killed after --attempt-timeout seconds; a killed
// attempt counts as transient. With --retry-on=npm-network, a failed attempt
// is retried only when its output shows a registry or network error, so an
// `npm audit` advisory finding fails after one attempt. After the last failed
// attempt the helper exits with that attempt's status (124 after a timeout).
//
// The helper's options end at the first argument that does not start with
// `--`, or after a literal `--`. Node runs on every runner that runs npm, so
// one helper serves Linux, macOS and Windows steps.

import { spawn, spawnSync } from "node:child_process";
import { constants } from "node:os";
import process from "node:process";

const DEFAULTS = Object.freeze({ attempts: 3, delay: 20, attemptTimeout: 240 });

// Output of npm when the registry or the network failed, not the project.
const NPM_NETWORK = new RegExp(
  [
    String.raw`\bE(?:CONNRESET|CONNREFUSED|CONNABORTED|TIMEDOUT|SOCKETTIMEDOUT|AI_AGAIN|NOTFOUND|PIPE|NETUNREACH|HOSTUNREACH)\b`,
    String.raw`\bE(?:429|5\d\d)\b`,
    String.raw`\b(?:429 Too Many Requests|5\d\d (?:Internal Server Error|Bad Gateway|Service Unavailable|Gateway Time-?out))\b`,
    String.raw`audit endpoint returned an error`,
    String.raw`socket hang up`,
    String.raw`network timeout`,
  ].join("|"),
  "i",
);

const RETRY_FILTERS = Object.freeze({ "npm-network": NPM_NETWORK });
// The tail of an attempt's output that the retry filter reads.
const KEEP_OUTPUT = 1 << 20;

function usage(message) {
  process.stderr.write(`ci-retry: ${message}\n`);
  process.exit(2);
}

function parseSeconds(name, text, minimum) {
  const value = Number(text);
  if (!Number.isFinite(value) || value < minimum) {
    usage(`--${name} needs a number of at least ${minimum}, got ${JSON.stringify(text)}`);
  }
  return value;
}

function parseArgs(argv) {
  const options = { ...DEFAULTS, retryOn: null };
  let index = 0;
  for (; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--") {
      index += 1;
      break;
    }
    if (!arg.startsWith("--")) break;
    const [name, value] = arg.slice(2).split(/=(.*)/s, 2);
    if (value === undefined) usage(`write options as --${name}=VALUE`);
    if (name === "attempts") {
      options.attempts = parseSeconds(name, value, 1);
      if (!Number.isInteger(options.attempts)) usage("--attempts needs a whole number");
    } else if (name === "delay") {
      options.delay = parseSeconds(name, value, 0);
    } else if (name === "attempt-timeout") {
      options.attemptTimeout = parseSeconds(name, value, 1);
    } else if (name === "retry-on") {
      if (!(value in RETRY_FILTERS)) usage(`unknown --retry-on filter ${JSON.stringify(value)}`);
      options.retryOn = value;
    } else {
      usage(`unknown option --${name}`);
    }
  }
  const command = argv.slice(index);
  if (command.length === 0) usage("a command is required");
  return { options, command };
}

function killTree(child) {
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    return;
  }
  try {
    process.kill(-child.pid, "SIGKILL");
  } catch {
    // The process group has already exited.
  }
}

function quoteForCmd(arg) {
  return /[\s"&|<>^]/.test(arg) ? `"${arg.replace(/"/g, '""')}"` : arg;
}

function runAttempt(command, timeoutSeconds) {
  return new Promise((resolve) => {
    // npm is a .cmd shim on Windows, which Node starts only through a shell.
    const windows = process.platform === "win32";
    const child = windows
      ? spawn(command.map(quoteForCmd).join(" "), {
          shell: true,
          stdio: ["inherit", "pipe", "pipe"],
        })
      : spawn(command[0], command.slice(1), {
          detached: true,
          stdio: ["inherit", "pipe", "pipe"],
        });
    let output = "";
    let timedOut = false;
    const keep = (chunk, stream) => {
      stream.write(chunk);
      output = (output + chunk.toString("utf8")).slice(-KEEP_OUTPUT);
    };
    child.stdout.on("data", (chunk) => keep(chunk, process.stdout));
    child.stderr.on("data", (chunk) => keep(chunk, process.stderr));
    const timer = setTimeout(() => {
      timedOut = true;
      killTree(child);
    }, timeoutSeconds * 1000);
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ status: 127, output: String(error), timedOut: false });
    });
    child.on("close", (code, signal) => {
      clearTimeout(timer);
      const status = timedOut ? 124 : (code ?? 128 + (constants.signals[signal] ?? 0));
      resolve({ status, output, timedOut });
    });
  });
}

async function main(argv) {
  const { options, command } = parseArgs(argv);
  const filter = options.retryOn ? RETRY_FILTERS[options.retryOn] : null;
  const shown = command.join(" ");
  let status = 1;
  for (let attempt = 1; attempt <= options.attempts; attempt += 1) {
    console.log(`ci-retry: attempt ${attempt} of ${options.attempts}: ${shown}`);
    const result = await runAttempt(command, options.attemptTimeout);
    status = result.status;
    if (status === 0) return 0;
    if (result.timedOut) {
      console.log(`ci-retry: attempt ${attempt} ran longer than ${options.attemptTimeout} s`);
    } else if (filter && !filter.test(result.output)) {
      console.log(
        `ci-retry: attempt ${attempt} exited ${status} without a ${options.retryOn} error; not retrying`,
      );
      return status;
    }
    if (attempt < options.attempts) {
      console.log(`ci-retry: attempt ${attempt} exited ${status}; retrying in ${options.delay} s`);
      await new Promise((resolve) => setTimeout(resolve, options.delay * 1000));
    }
  }
  console.log(`ci-retry: ${options.attempts} attempts failed; exiting ${status}`);
  return status;
}

process.exitCode = await main(process.argv.slice(2));
