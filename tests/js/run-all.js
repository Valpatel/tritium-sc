// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Batch JS test runner — runs test files as child processes with controlled
 * concurrency. Each test still gets its own V8 isolate (avoiding global state
 * conflicts and process.exit() issues) but we launch N in parallel to cut
 * wall-clock time from ~5s sequential to ~1-2s.
 *
 * Usage:
 *   node tests/js/run-all.js                          # discover all test_*.js
 *   node tests/js/run-all.js test_store.js test_events.js  # run specific files
 *   node tests/js/run-all.js --concurrency 8          # override parallelism
 *
 * Output format matches what test.sh tier3_js() expects:
 *   BATCH_PASS: test_store.js
 *   BATCH_FAIL: test_websocket.js
 *   BATCH_SUMMARY: 86 passed, 5 failed, 0 skipped
 *
 * Exit code: number of failed tests (0 = all passed).
 */

const { execFile } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

// Parse arguments
const args = process.argv.slice(2);
let concurrency = Math.max(2, Math.floor(os.cpus().length / 2));
const testFiles = [];

for (let i = 0; i < args.length; i++) {
    if (args[i] === '--concurrency' && args[i + 1]) {
        concurrency = parseInt(args[i + 1], 10);
        i++;
    } else {
        testFiles.push(args[i]);
    }
}

// If no files specified, discover all test_*.js in this directory
const testDir = path.resolve(__dirname);
// Stress/perf tests are sensitive to CPU contention — run them last, sequentially
const SEQUENTIAL_TESTS = new Set(['test_city_sim_stress.js']);

if (testFiles.length === 0) {
    const entries = fs.readdirSync(testDir)
        .filter(f => f.startsWith('test_') && f.endsWith('.js') && f !== 'run-all.js')
        .sort();
    // Move sequential tests to the end
    const parallel = entries.filter(f => !SEQUENTIAL_TESTS.has(f));
    const sequential = entries.filter(f => SEQUENTIAL_TESTS.has(f));
    testFiles.push(...parallel, ...sequential);
}

if (testFiles.length === 0) {
    console.error('No test files found.');
    process.exit(1);
}

/**
 * Run a single test file as a child process.
 * Returns { file, passed, error, stdout, stderr }.
 */
function runTest(file) {
    return new Promise((resolve) => {
        const fullPath = path.resolve(testDir, file);
        if (!fs.existsSync(fullPath)) {
            resolve({ file, passed: false, skipped: true, error: 'not found', stdout: '', stderr: '' });
            return;
        }

        const child = execFile('node', [fullPath], {
            timeout: 30000,  // 30s per test max
            maxBuffer: 2 * 1024 * 1024,  // 2MB output buffer
            env: { ...process.env, NODE_OPTIONS: '' },
        }, (error, stdout, stderr) => {
            const passed = !error || error.code === 0;
            resolve({
                file,
                passed,
                skipped: false,
                error: error ? (error.killed ? 'timeout' : `exit ${error.code}`) : null,
                stdout: stdout || '',
                stderr: stderr || '',
            });
        });
    });
}

/**
 * Run all tests with bounded concurrency.
 */
function reportResult(result, counts) {
    if (result.skipped) {
        console.log(`BATCH_SKIP: ${result.file}`);
        counts.skip++;
    } else if (result.passed) {
        console.log(`BATCH_PASS: ${result.file}`);
        counts.pass++;
    } else {
        console.log(`BATCH_FAIL: ${result.file}`);
        counts.fail++;
        const output = (result.stdout + '\n' + result.stderr).trim();
        const lines = output.split('\n');
        const excerpt = lines.slice(-5).join('\n');
        if (excerpt) {
            console.error(`  ${excerpt.replace(/\n/g, '\n  ')}`);
        }
    }
}

async function runAll() {
    const counts = { pass: 0, fail: 0, skip: 0 };

    // Split into parallel and sequential sets
    const parallelFiles = testFiles.filter(f => !SEQUENTIAL_TESTS.has(f));
    const sequentialFiles = testFiles.filter(f => SEQUENTIAL_TESTS.has(f));

    // Run parallel batch with bounded concurrency
    let running = 0;
    let idx = 0;

    if (parallelFiles.length > 0) {
        await new Promise((resolveAll) => {
            function tryNext() {
                while (running < concurrency && idx < parallelFiles.length) {
                    const file = parallelFiles[idx++];
                    running++;
                    runTest(file).then((result) => {
                        reportResult(result, counts);
                        running--;
                        if (running === 0 && idx >= parallelFiles.length) {
                            resolveAll();
                        } else {
                            tryNext();
                        }
                    });
                }
            }
            tryNext();
        });
    }

    // Run sequential tests one at a time (perf-sensitive, no CPU contention)
    for (const file of sequentialFiles) {
        const result = await runTest(file);
        reportResult(result, counts);
    }

    console.log(`BATCH_SUMMARY: ${counts.pass} passed, ${counts.fail} failed, ${counts.skip} skipped`);
    process.exit(counts.fail);
}

runAll();
