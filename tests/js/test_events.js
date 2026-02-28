// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC EventBus tests
 * Tests: on/off/emit lifecycle, wildcard listeners, error isolation,
 * data passing, unsubscribe functions, memory cleanup, edge cases.
 * Run: node tests/js/test_events.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}
function assertDeepEqual(a, b, msg) {
    assert(JSON.stringify(a) === JSON.stringify(b), msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// Load events.js into a sandboxed context
const code = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
const plain = code
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout,
};
const ctx = vm.createContext(sandbox);
vm.runInContext(plain + '\nvar _EventBus = EventBus;', ctx);

// Extract EventBus from context
const EventBus = ctx._EventBus;

// Helper: reset EventBus between tests to prevent cross-contamination
function resetBus() {
    EventBus._handlers.clear();
}

// ============================================================
// 1. Basic emit and listener invocation
// ============================================================

console.log('\n--- Basic emit and listener invocation ---');

(function testEmitCallsListener() {
    resetBus();
    let called = false;
    EventBus.on('test:event', () => { called = true; });
    EventBus.emit('test:event');
    assert(called, 'emit triggers registered listener');
})();

(function testListenerReceivesData() {
    resetBus();
    let received = null;
    EventBus.on('test:data', (data) => { received = data; });
    EventBus.emit('test:data', { id: 'rover-01', x: 100 });
    assertDeepEqual(received, { id: 'rover-01', x: 100 }, 'listener receives emitted data object');
})();

(function testListenerReceivesPrimitiveData() {
    resetBus();
    let received = null;
    EventBus.on('test:primitive', (data) => { received = data; });
    EventBus.emit('test:primitive', 42);
    assertEqual(received, 42, 'listener receives primitive data');
})();

(function testListenerReceivesStringData() {
    resetBus();
    let received = null;
    EventBus.on('test:string', (data) => { received = data; });
    EventBus.emit('test:string', 'hello');
    assertEqual(received, 'hello', 'listener receives string data');
})();

(function testListenerReceivesNullData() {
    resetBus();
    let received = 'sentinel';
    EventBus.on('test:null', (data) => { received = data; });
    EventBus.emit('test:null', null);
    assertEqual(received, null, 'listener receives null data');
})();

(function testListenerReceivesUndefinedWhenNoData() {
    resetBus();
    let received = 'sentinel';
    EventBus.on('test:nodata', (data) => { received = data; });
    EventBus.emit('test:nodata');
    assertEqual(received, undefined, 'listener receives undefined when no data passed');
})();

(function testListenerReceivesArrayData() {
    resetBus();
    let received = null;
    EventBus.on('test:array', (data) => { received = data; });
    const arr = [1, 2, 3];
    EventBus.emit('test:array', arr);
    assertDeepEqual(received, [1, 2, 3], 'listener receives array data');
})();

// ============================================================
// 2. Multiple listeners on same event
// ============================================================

console.log('\n--- Multiple listeners on same event ---');

(function testMultipleListenersSameEvent() {
    resetBus();
    let count = 0;
    EventBus.on('multi', () => { count++; });
    EventBus.on('multi', () => { count++; });
    EventBus.on('multi', () => { count++; });
    EventBus.emit('multi');
    assertEqual(count, 3, 'all 3 listeners called on same event');
})();

(function testMultipleListenersAllReceiveData() {
    resetBus();
    const results = [];
    EventBus.on('multi:data', (d) => results.push('a:' + d.val));
    EventBus.on('multi:data', (d) => results.push('b:' + d.val));
    EventBus.emit('multi:data', { val: 7 });
    assert(results.includes('a:7'), 'first listener receives data');
    assert(results.includes('b:7'), 'second listener receives data');
    assertEqual(results.length, 2, 'exactly 2 listeners invoked');
})();

(function testMultipleEmitsCallListenerEachTime() {
    resetBus();
    let count = 0;
    EventBus.on('repeat', () => { count++; });
    EventBus.emit('repeat');
    EventBus.emit('repeat');
    EventBus.emit('repeat');
    assertEqual(count, 3, 'listener called on each emit');
})();

// ============================================================
// 3. Listener removal via off()
// ============================================================

console.log('\n--- Listener removal via off() ---');

(function testOffRemovesListener() {
    resetBus();
    let count = 0;
    const handler = () => { count++; };
    EventBus.on('offtest', handler);
    EventBus.emit('offtest');
    assertEqual(count, 1, 'handler called before off()');
    EventBus.off('offtest', handler);
    EventBus.emit('offtest');
    assertEqual(count, 1, 'handler NOT called after off()');
})();

(function testOffOnlyRemovesSpecificHandler() {
    resetBus();
    let countA = 0, countB = 0;
    const handlerA = () => { countA++; };
    const handlerB = () => { countB++; };
    EventBus.on('offspecific', handlerA);
    EventBus.on('offspecific', handlerB);
    EventBus.off('offspecific', handlerA);
    EventBus.emit('offspecific');
    assertEqual(countA, 0, 'removed handler A not called');
    assertEqual(countB, 1, 'remaining handler B still called');
})();

(function testOffNonexistentHandlerNoError() {
    resetBus();
    const handler = () => {};
    // off on event with no listeners
    EventBus.off('nonexistent', handler);
    assert(true, 'off() with nonexistent event does not crash');
})();

(function testOffNonexistentHandlerOnExistingEvent() {
    resetBus();
    EventBus.on('existing', () => {});
    EventBus.off('existing', () => {}); // different function ref
    assert(true, 'off() with non-matching handler does not crash');
})();

// ============================================================
// 4. Listener removal via unsubscribe function returned by on()
// ============================================================

console.log('\n--- Unsubscribe function from on() ---');

(function testUnsubscribeFunctionRemovesListener() {
    resetBus();
    let count = 0;
    const unsub = EventBus.on('unsub', () => { count++; });
    EventBus.emit('unsub');
    assertEqual(count, 1, 'handler called before unsub()');
    unsub();
    EventBus.emit('unsub');
    assertEqual(count, 1, 'handler NOT called after unsub()');
})();

(function testUnsubscribeReturnsFunction() {
    resetBus();
    const unsub = EventBus.on('typecheck', () => {});
    assertEqual(typeof unsub, 'function', 'on() returns a function');
})();

(function testDoubleUnsubscribeDoesNotCrash() {
    resetBus();
    const unsub = EventBus.on('double-unsub', () => {});
    unsub();
    unsub(); // second call should not crash
    assert(true, 'calling unsub() twice does not crash');
})();

(function testUnsubscribeOnlyAffectsOwnHandler() {
    resetBus();
    let countA = 0, countB = 0;
    const unsubA = EventBus.on('selective', () => { countA++; });
    EventBus.on('selective', () => { countB++; });
    unsubA();
    EventBus.emit('selective');
    assertEqual(countA, 0, 'unsubscribed handler A not called');
    assertEqual(countB, 1, 'other handler B still called');
})();

// ============================================================
// 5. Emit with no listeners (no crash)
// ============================================================

console.log('\n--- Emit with no listeners ---');

(function testEmitNoListenersNoCrash() {
    resetBus();
    EventBus.emit('nobody:listening');
    assert(true, 'emit with no listeners does not crash');
})();

(function testEmitNoListenersWithData() {
    resetBus();
    EventBus.emit('nobody:listening', { complex: { nested: true } });
    assert(true, 'emit with no listeners and data does not crash');
})();

(function testEmitAfterAllListenersRemoved() {
    resetBus();
    const unsub = EventBus.on('temp', () => {});
    unsub();
    EventBus.emit('temp');
    assert(true, 'emit after all listeners removed does not crash');
})();

// ============================================================
// 6. Error isolation -- handler errors do not break other handlers
// ============================================================

console.log('\n--- Error isolation ---');

(function testErrorInHandlerDoesNotBreakOthers() {
    resetBus();
    let secondCalled = false;
    EventBus.on('error:test', () => { throw new Error('intentional'); });
    EventBus.on('error:test', () => { secondCalled = true; });
    // Suppress console.error for this test
    const origError = console.error;
    let errorLogged = false;
    console.error = () => { errorLogged = true; };
    EventBus.emit('error:test');
    console.error = origError;
    assert(secondCalled, 'second handler called despite first throwing');
    assert(errorLogged, 'error was logged via console.error');
})();

(function testErrorIncludesEventName() {
    resetBus();
    let errorMsg = '';
    const origError = console.error;
    console.error = (...args) => { errorMsg = args.join(' '); };
    EventBus.on('named:error', () => { throw new Error('boom'); });
    EventBus.emit('named:error');
    console.error = origError;
    assert(errorMsg.includes('named:error'), 'error message includes event name');
})();

// ============================================================
// 7. Wildcard '*' listener
// ============================================================

console.log('\n--- Wildcard listener ---');

(function testWildcardListenerReceivesAllEvents() {
    resetBus();
    const events = [];
    EventBus.on('*', (event, data) => { events.push({ event, data }); });
    EventBus.emit('unit:selected', { id: 'u1' });
    EventBus.emit('game:state', { wave: 3 });
    EventBus.emit('alert:new', { type: 'threat' });
    assertEqual(events.length, 3, 'wildcard listener called for all 3 events');
    assertEqual(events[0].event, 'unit:selected', 'wildcard receives event name as first arg');
    assertDeepEqual(events[0].data, { id: 'u1' }, 'wildcard receives data as second arg');
    assertEqual(events[1].event, 'game:state', 'wildcard receives second event name');
    assertEqual(events[2].event, 'alert:new', 'wildcard receives third event name');
})();

(function testWildcardDoesNotDuplicateForSpecificListeners() {
    resetBus();
    let specificCount = 0;
    let wildcardCount = 0;
    EventBus.on('specific:event', () => { specificCount++; });
    EventBus.on('*', () => { wildcardCount++; });
    EventBus.emit('specific:event');
    assertEqual(specificCount, 1, 'specific listener called once');
    assertEqual(wildcardCount, 1, 'wildcard listener called once (not duplicated)');
})();

(function testWildcardListenerCanBeRemoved() {
    resetBus();
    let count = 0;
    const handler = () => { count++; };
    EventBus.on('*', handler);
    EventBus.emit('any:event');
    assertEqual(count, 1, 'wildcard called before removal');
    EventBus.off('*', handler);
    EventBus.emit('any:event');
    assertEqual(count, 1, 'wildcard NOT called after off()');
})();

(function testWildcardUnsubFunction() {
    resetBus();
    let count = 0;
    const unsub = EventBus.on('*', () => { count++; });
    EventBus.emit('foo');
    assertEqual(count, 1, 'wildcard called before unsub');
    unsub();
    EventBus.emit('bar');
    assertEqual(count, 1, 'wildcard NOT called after unsub()');
})();

(function testWildcardErrorDoesNotBreakEmit() {
    resetBus();
    let specificCalled = false;
    EventBus.on('safe:event', () => { specificCalled = true; });
    EventBus.on('*', () => { throw new Error('wildcard boom'); });
    const origError = console.error;
    console.error = () => {};
    EventBus.emit('safe:event');
    console.error = origError;
    assert(specificCalled, 'specific handler called despite wildcard error');
})();

(function testWildcardDoesNotFireForWildcardEmit() {
    resetBus();
    // Emitting '*' as an event name -- wildcard handlers should fire
    // once as the specific handler and once as the wildcard
    let specificCount = 0;
    let wildcardCount = 0;
    EventBus.on('*', (event, data) => {
        if (event === '*') wildcardCount++;
        else specificCount++;
    });
    // Emitting '*' triggers: first the specific '*' handlers (as a named event),
    // then the '*' handlers again as wildcard observers.
    // Actually looking at the code: emit('*', data) calls _handlers.get('*').forEach
    // twice -- once for the named event, then again for the wildcard observer.
    EventBus.emit('*', { test: true });
    // The handler is in the '*' Set, so it fires once for named event,
    // then forEach on '*' fires it again for wildcard observation.
    // But on the wildcard pass, handler(event='*', data) so wildcardCount increments.
    // On the named pass, handler receives (data) as first arg, not (event, data).
    // Wait -- for named event, handler receives handler(data), so event={test:true}, data=undefined
    // For wildcard pass, handler receives handler('*', {test:true})
    // So the first call: event={test:true}, data=undefined -- neither branch
    // The second call: event='*', data={test:true} -- wildcardCount++
    assertEqual(wildcardCount, 1, 'wildcard sees itself when * is emitted as event name');
})();

// ============================================================
// 8. Removing a listener during emission
// ============================================================

console.log('\n--- Removing listener during emission ---');

(function testRemoveSelfDuringEmission() {
    resetBus();
    let count = 0;
    let unsub;
    unsub = EventBus.on('self-remove', () => {
        count++;
        unsub();
    });
    EventBus.emit('self-remove');
    EventBus.emit('self-remove');
    assertEqual(count, 1, 'self-removing listener only called once');
})();

(function testRemoveOtherDuringEmission() {
    resetBus();
    let countA = 0, countB = 0;
    let unsubB;
    EventBus.on('cross-remove', () => {
        countA++;
        unsubB(); // remove handler B while iterating
    });
    unsubB = EventBus.on('cross-remove', () => {
        countB++;
    });
    // Due to Set iteration behavior, removing during forEach may or may not
    // prevent the second handler from being called on this emit.
    // We just verify it does not crash.
    EventBus.emit('cross-remove');
    assert(countA >= 1, 'handler A was called at least once');
    // After first emit, handler B is removed
    countA = 0;
    countB = 0;
    EventBus.emit('cross-remove');
    assertEqual(countA, 1, 'handler A still active on second emit');
    assertEqual(countB, 0, 'handler B removed and not called on second emit');
})();

// ============================================================
// 9. Memory leak prevention / cleanup
// ============================================================

console.log('\n--- Memory cleanup ---');

(function testHandlersMapClearedByReset() {
    resetBus();
    EventBus.on('leak:test', () => {});
    EventBus.on('leak:test2', () => {});
    assert(EventBus._handlers.size > 0, 'handlers map has entries before clear');
    EventBus._handlers.clear();
    assertEqual(EventBus._handlers.size, 0, 'handlers map empty after clear');
})();

(function testRemovedHandlerDoesNotPreventGC() {
    resetBus();
    let callCount = 0;
    const handler = () => { callCount++; };
    const unsub = EventBus.on('gc:test', handler);
    unsub();
    // The handler should be removed from the Set
    const set = EventBus._handlers.get('gc:test');
    assertEqual(set.size, 0, 'handler removed from Set after unsub (allows GC)');
})();

(function testManyListenersCanBeAdded() {
    resetBus();
    const unsubs = [];
    for (let i = 0; i < 100; i++) {
        unsubs.push(EventBus.on('mass:event', () => {}));
    }
    const set = EventBus._handlers.get('mass:event');
    assertEqual(set.size, 100, '100 listeners registered');
    // Clean up all
    unsubs.forEach(u => u());
    assertEqual(set.size, 0, 'all 100 listeners removed');
})();

(function testDuplicateHandlerReference() {
    resetBus();
    let count = 0;
    const handler = () => { count++; };
    // Set-based storage means same function ref is only stored once
    EventBus.on('dup', handler);
    EventBus.on('dup', handler);
    EventBus.emit('dup');
    assertEqual(count, 1, 'same handler ref registered twice only called once (Set dedup)');
})();

// ============================================================
// 10. Independent event namespaces
// ============================================================

console.log('\n--- Independent event namespaces ---');

(function testDifferentEventsAreIndependent() {
    resetBus();
    let countA = 0, countB = 0;
    EventBus.on('event:a', () => { countA++; });
    EventBus.on('event:b', () => { countB++; });
    EventBus.emit('event:a');
    assertEqual(countA, 1, 'event:a handler called');
    assertEqual(countB, 0, 'event:b handler NOT called by event:a emit');
})();

(function testOffOnOneEventDoesNotAffectOther() {
    resetBus();
    let countA = 0, countB = 0;
    const handlerA = () => { countA++; };
    const handlerB = () => { countB++; };
    EventBus.on('ns:a', handlerA);
    EventBus.on('ns:b', handlerB);
    EventBus.off('ns:a', handlerA);
    EventBus.emit('ns:a');
    EventBus.emit('ns:b');
    assertEqual(countA, 0, 'ns:a handler removed');
    assertEqual(countB, 1, 'ns:b handler unaffected by ns:a off');
})();

// ============================================================
// 11. Standard event name patterns (from events.js reference)
// ============================================================

console.log('\n--- Standard event name patterns ---');

(function testUnitSelectedEventPattern() {
    resetBus();
    let received = null;
    EventBus.on('unit:selected', (data) => { received = data; });
    EventBus.emit('unit:selected', { id: 'tank-01' });
    assertDeepEqual(received, { id: 'tank-01' }, 'unit:selected event passes id');
})();

(function testGameEliminationEventPattern() {
    resetBus();
    let received = null;
    EventBus.on('game:elimination', (data) => { received = data; });
    EventBus.emit('game:elimination', { interceptor: 'turret-01', target: 'hostile-03', weapon: 'nerf_blaster' });
    assertEqual(received.interceptor, 'turret-01', 'game:elimination has interceptor');
    assertEqual(received.target, 'hostile-03', 'game:elimination has target');
    assertEqual(received.weapon, 'nerf_blaster', 'game:elimination has weapon');
})();

(function testWsLifecycleEvents() {
    resetBus();
    let connected = false, disconnected = false;
    EventBus.on('ws:connected', () => { connected = true; });
    EventBus.on('ws:disconnected', () => { disconnected = true; });
    EventBus.emit('ws:connected');
    assert(connected, 'ws:connected fires');
    assert(!disconnected, 'ws:disconnected not fired by ws:connected');
    EventBus.emit('ws:disconnected');
    assert(disconnected, 'ws:disconnected fires');
})();

(function testToastEvent() {
    resetBus();
    let received = null;
    EventBus.on('toast:show', (data) => { received = data; });
    EventBus.emit('toast:show', { message: 'Unit deployed', type: 'success', duration: 3000 });
    assertEqual(received.message, 'Unit deployed', 'toast:show message');
    assertEqual(received.type, 'success', 'toast:show type');
    assertEqual(received.duration, 3000, 'toast:show duration');
})();

// ============================================================
// 12. Edge cases and robustness
// ============================================================

console.log('\n--- Edge cases ---');

(function testEmptyStringEventName() {
    resetBus();
    let called = false;
    EventBus.on('', () => { called = true; });
    EventBus.emit('');
    assert(called, 'empty string event name works');
})();

(function testEventNameWithSpecialCharacters() {
    resetBus();
    let called = false;
    EventBus.on('event/with:special.chars-and_more', () => { called = true; });
    EventBus.emit('event/with:special.chars-and_more');
    assert(called, 'event name with special characters works');
})();

(function testHandlerOrderIsPreserved() {
    resetBus();
    const order = [];
    EventBus.on('order', () => order.push(1));
    EventBus.on('order', () => order.push(2));
    EventBus.on('order', () => order.push(3));
    EventBus.emit('order');
    // Set forEach iterates in insertion order
    assertDeepEqual(order, [1, 2, 3], 'handlers called in registration order');
})();

(function testReRegisterAfterUnsubscribe() {
    resetBus();
    let count = 0;
    const handler = () => { count++; };
    const unsub = EventBus.on('rereg', handler);
    unsub();
    EventBus.on('rereg', handler);
    EventBus.emit('rereg');
    assertEqual(count, 1, 'handler works after re-registration');
})();

(function testMultipleEventsFromSameHandler() {
    resetBus();
    let count = 0;
    const handler = () => { count++; };
    EventBus.on('multi:a', handler);
    EventBus.on('multi:b', handler);
    EventBus.emit('multi:a');
    EventBus.emit('multi:b');
    assertEqual(count, 2, 'same handler on different events both fire');
})();

(function testEmitReturnsSilently() {
    resetBus();
    const result = EventBus.emit('silent:event', { foo: 'bar' });
    assertEqual(result, undefined, 'emit returns undefined');
})();

(function testOnReturnsFunction() {
    resetBus();
    const result = EventBus.on('return:check', () => {});
    assertEqual(typeof result, 'function', 'on() returns function');
})();

(function testRapidFireEmit() {
    resetBus();
    let count = 0;
    EventBus.on('rapid', () => { count++; });
    for (let i = 0; i < 1000; i++) {
        EventBus.emit('rapid');
    }
    assertEqual(count, 1000, '1000 rapid emits all received');
})();

(function testWildcardWithManyEvents() {
    resetBus();
    const seen = new Set();
    EventBus.on('*', (event) => { seen.add(event); });
    const events = ['a', 'b', 'c', 'd', 'e', 'f', 'g'];
    events.forEach(e => EventBus.emit(e));
    assertEqual(seen.size, 7, 'wildcard sees all 7 distinct events');
})();

// ============================================================
// 13. Simulated one-time listener pattern
// ============================================================

console.log('\n--- One-time listener pattern ---');

(function testOneTimeListenerViaUnsub() {
    resetBus();
    let count = 0;
    const unsub = EventBus.on('once:test', () => {
        count++;
        unsub();
    });
    EventBus.emit('once:test');
    EventBus.emit('once:test');
    EventBus.emit('once:test');
    assertEqual(count, 1, 'self-unsubscribing listener fires only once');
})();

(function testOneTimeHelperPattern() {
    resetBus();
    // Show that a once() helper can be built on top of on()
    function once(event, handler) {
        const unsub = EventBus.on(event, (data) => {
            unsub();
            handler(data);
        });
        return unsub;
    }
    let count = 0;
    once('once:helper', () => { count++; });
    EventBus.emit('once:helper');
    EventBus.emit('once:helper');
    assertEqual(count, 1, 'once() helper fires handler exactly once');
})();

(function testOneTimeCanBePreemptivelyRemoved() {
    resetBus();
    let count = 0;
    function once(event, handler) {
        const unsub = EventBus.on(event, (data) => {
            unsub();
            handler(data);
        });
        return unsub;
    }
    const unsub = once('once:preempt', () => { count++; });
    unsub(); // remove before any emit
    EventBus.emit('once:preempt');
    assertEqual(count, 0, 'once() listener removed before firing never fires');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
