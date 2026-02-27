/**
 * TRITIUM-SC TritiumStore tests
 * Tests dot-path get/set, subscriber notification, unit telemetry,
 * alerts, wildcard listeners, unsubscribe, edge cases.
 * Run: node tests/js/test_store.js
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

// Load store.js into a sandboxed context
const code = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8');
const plainCode = code
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');

// Helper: create a fresh TritiumStore instance for each test group
// We re-run the module code each time to avoid cross-test pollution
function createStore() {
    const sandbox = {
        Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
        Infinity, NaN, undefined, parseInt, parseFloat, JSON,
    };
    const ctx = vm.createContext(sandbox);
    vm.runInContext(plainCode + '\nvar _store = TritiumStore;', ctx);
    return ctx._store;
}

// ============================================================
// 1. Initial state structure
// ============================================================

console.log('\n--- Initial State Structure ---');

(function testInitialMapState() {
    const store = createStore();
    assertEqual(store.map.mode, 'observe', 'Initial map.mode is observe');
    assertEqual(store.map.selectedUnitId, null, 'Initial map.selectedUnitId is null');
    assertEqual(store.map.viewport.x, 0, 'Initial map.viewport.x is 0');
    assertEqual(store.map.viewport.y, 0, 'Initial map.viewport.y is 0');
    assertEqual(store.map.viewport.zoom, 1, 'Initial map.viewport.zoom is 1');
})();

(function testInitialGameState() {
    const store = createStore();
    assertEqual(store.game.phase, 'idle', 'Initial game.phase is idle');
    assertEqual(store.game.wave, 0, 'Initial game.wave is 0');
    assertEqual(store.game.totalWaves, 10, 'Initial game.totalWaves is 10');
    assertEqual(store.game.score, 0, 'Initial game.score is 0');
    assertEqual(store.game.eliminations, 0, 'Initial game.eliminations is 0');
})();

(function testInitialUnitsIsMap() {
    const store = createStore();
    assert(store.units instanceof Map, 'Initial units is a Map');
    assertEqual(store.units.size, 0, 'Initial units is empty');
})();

(function testInitialAmyState() {
    const store = createStore();
    assertEqual(store.amy.state, 'idle', 'Initial amy.state is idle');
    assertEqual(store.amy.mood, 'calm', 'Initial amy.mood is calm');
    assertEqual(store.amy.lastThought, '', 'Initial amy.lastThought is empty string');
    assertEqual(store.amy.speaking, false, 'Initial amy.speaking is false');
    assertEqual(store.amy.nodeCount, 0, 'Initial amy.nodeCount is 0');
})();

(function testInitialConnectionState() {
    const store = createStore();
    assertEqual(store.connection.status, 'disconnected', 'Initial connection.status is disconnected');
})();

(function testInitialAlerts() {
    const store = createStore();
    assert(Array.isArray(store.alerts), 'Initial alerts is an array');
    assertEqual(store.alerts.length, 0, 'Initial alerts is empty');
})();

(function testInitialCameras() {
    const store = createStore();
    assert(Array.isArray(store.cameras), 'Initial cameras is an array');
    assertEqual(store.cameras.length, 0, 'Initial cameras is empty');
})();

(function testListenersMapExists() {
    const store = createStore();
    assert(store._listeners instanceof Map, '_listeners is a Map');
    assertEqual(store._listeners.size, 0, '_listeners is initially empty');
})();

// ============================================================
// 2. Dot-path get operations
// ============================================================

console.log('\n--- Dot-path get ---');

(function testGetTopLevel() {
    const store = createStore();
    const game = store.get('game');
    assertEqual(game.phase, 'idle', 'get("game") returns game object with phase=idle');
})();

(function testGetNestedPath() {
    const store = createStore();
    assertEqual(store.get('game.phase'), 'idle', 'get("game.phase") returns idle');
})();

(function testGetDeeplyNested() {
    const store = createStore();
    assertEqual(store.get('map.viewport.zoom'), 1, 'get("map.viewport.zoom") returns 1');
})();

(function testGetNonExistentPath() {
    const store = createStore();
    assertEqual(store.get('nonexistent'), undefined, 'get("nonexistent") returns undefined');
})();

(function testGetNonExistentNestedPath() {
    const store = createStore();
    assertEqual(store.get('foo.bar.baz'), undefined, 'get("foo.bar.baz") returns undefined');
})();

(function testGetPartiallyExistentPath() {
    const store = createStore();
    assertEqual(store.get('game.nonexistent'), undefined, 'get("game.nonexistent") returns undefined');
})();

(function testGetMapBasedUnits() {
    const store = createStore();
    store.units.set('drone-1', { id: 'drone-1', type: 'drone' });
    const unit = store.get('units.drone-1');
    assertEqual(unit.type, 'drone', 'get("units.drone-1") traverses Map with .get()');
})();

(function testGetMapBasedUnitsNested() {
    const store = createStore();
    store.units.set('rover-1', { id: 'rover-1', type: 'rover', position: { x: 10, y: 20 } });
    assertEqual(store.get('units.rover-1.position.x'), 10, 'get("units.rover-1.position.x") deep traverses through Map then Object');
})();

(function testGetMapMissingKey() {
    const store = createStore();
    assertEqual(store.get('units.nonexistent'), undefined, 'get("units.nonexistent") returns undefined for missing Map key');
})();

(function testGetThroughNullValue() {
    const store = createStore();
    // map.selectedUnitId is null, so going deeper should return undefined
    assertEqual(store.get('map.selectedUnitId.foo'), undefined, 'get through null returns undefined');
})();

// ============================================================
// 3. Dot-path set operations
// ============================================================

console.log('\n--- Dot-path set ---');

(function testSetSimplePath() {
    const store = createStore();
    store.set('game.phase', 'active');
    assertEqual(store.game.phase, 'active', 'set("game.phase", "active") updates game.phase');
})();

(function testSetDeeplyNested() {
    const store = createStore();
    store.set('map.viewport.zoom', 2.5);
    assertEqual(store.map.viewport.zoom, 2.5, 'set("map.viewport.zoom", 2.5) updates nested value');
})();

(function testSetTopLevelProperty() {
    const store = createStore();
    store.set('game.score', 1500);
    assertEqual(store.game.score, 1500, 'set("game.score", 1500) updates game.score');
})();

(function testSetCreatesIntermediateObjects() {
    const store = createStore();
    store.set('custom.deeply.nested.value', 42);
    assertEqual(store.custom.deeply.nested.value, 42, 'set creates intermediate objects for new path');
    assertEqual(store.get('custom.deeply.nested.value'), 42, 'get reads the created nested path');
})();

(function testSetCreatesIntermediateWhenNull() {
    const store = createStore();
    // map.selectedUnitId is null, but we can't set through it since it is a leaf
    // Instead, test with a property we set to null first
    store.set('custom', null);
    // Now set through it -- set should create intermediate object
    store.set('custom.field', 'hello');
    assertEqual(store.get('custom.field'), 'hello', 'set creates intermediate when parent is null');
})();

(function testSetDoesNotOverwriteSiblings() {
    const store = createStore();
    store.set('game.phase', 'battle');
    assertEqual(store.game.wave, 0, 'set("game.phase") does not change game.wave');
    assertEqual(store.game.score, 0, 'set("game.phase") does not change game.score');
})();

(function testSetSameValueIsNoOp() {
    const store = createStore();
    let callCount = 0;
    store.on('game.phase', () => callCount++);
    store.set('game.phase', 'idle'); // same as initial
    assertEqual(callCount, 0, 'set with same value does not notify listeners');
})();

(function testSetSameValueNoOpForNumbers() {
    const store = createStore();
    let callCount = 0;
    store.on('game.score', () => callCount++);
    store.set('game.score', 0); // same as initial
    assertEqual(callCount, 0, 'set with same number value does not notify');
})();

(function testSetDifferentValueNotifies() {
    const store = createStore();
    let callCount = 0;
    store.on('game.phase', () => callCount++);
    store.set('game.phase', 'active');
    assertEqual(callCount, 1, 'set with different value notifies listeners');
})();

(function testSetObjectAlwaysNotifies() {
    const store = createStore();
    // Setting an object should always notify (object reference equality is always false)
    let callCount = 0;
    store.on('map.viewport', () => callCount++);
    store.set('map.viewport', { x: 0, y: 0, zoom: 1 }); // same values but new object
    assertEqual(callCount, 1, 'set with new object reference always notifies (not identical by ===)');
})();

(function testSetNullValue() {
    const store = createStore();
    store.set('game.phase', null);
    assertEqual(store.game.phase, null, 'set can assign null');
})();

(function testSetUndefinedValue() {
    const store = createStore();
    store.set('game.phase', undefined);
    assertEqual(store.game.phase, undefined, 'set can assign undefined');
})();

(function testSetBooleanValue() {
    const store = createStore();
    store.set('amy.speaking', true);
    assertEqual(store.amy.speaking, true, 'set can assign boolean true');
})();

(function testSetNumericZero() {
    const store = createStore();
    store.set('game.wave', 5);
    store.set('game.wave', 0);
    assertEqual(store.game.wave, 0, 'set can assign numeric 0');
})();

(function testSetEmptyString() {
    const store = createStore();
    store.set('amy.lastThought', 'something');
    store.set('amy.lastThought', '');
    assertEqual(store.amy.lastThought, '', 'set can assign empty string');
})();

// ============================================================
// 4. Subscriber notification
// ============================================================

console.log('\n--- Subscriber Notification ---');

(function testSubscriberReceivesNewValue() {
    const store = createStore();
    let received = null;
    store.on('game.phase', (val) => { received = val; });
    store.set('game.phase', 'countdown');
    assertEqual(received, 'countdown', 'subscriber receives new value');
})();

(function testSubscriberReceivesOldValue() {
    const store = createStore();
    let oldVal = null;
    store.on('game.phase', (val, old) => { oldVal = old; });
    store.set('game.phase', 'countdown');
    assertEqual(oldVal, 'idle', 'subscriber receives old value');
})();

(function testMultipleSubscribersNotified() {
    const store = createStore();
    let count1 = 0, count2 = 0;
    store.on('game.wave', () => count1++);
    store.on('game.wave', () => count2++);
    store.set('game.wave', 3);
    assertEqual(count1, 1, 'first subscriber notified');
    assertEqual(count2, 1, 'second subscriber notified');
})();

(function testSubscriberOnlyForOwnPath() {
    const store = createStore();
    let phaseCalls = 0, waveCalls = 0;
    store.on('game.phase', () => phaseCalls++);
    store.on('game.wave', () => waveCalls++);
    store.set('game.phase', 'active');
    assertEqual(phaseCalls, 1, 'game.phase subscriber called');
    assertEqual(waveCalls, 0, 'game.wave subscriber NOT called for game.phase change');
})();

(function testUnsubscribe() {
    const store = createStore();
    let callCount = 0;
    const unsub = store.on('game.phase', () => callCount++);
    store.set('game.phase', 'active');
    assertEqual(callCount, 1, 'subscriber called before unsubscribe');
    unsub();
    store.set('game.phase', 'idle');
    assertEqual(callCount, 1, 'subscriber NOT called after unsubscribe');
})();

(function testUnsubscribeReturnsFunctionType() {
    const store = createStore();
    const unsub = store.on('game.phase', () => {});
    assertEqual(typeof unsub, 'function', 'on() returns a function');
})();

(function testDoubleUnsubscribeDoesNotCrash() {
    const store = createStore();
    const unsub = store.on('game.phase', () => {});
    unsub();
    unsub(); // should not throw
    assert(true, 'double unsubscribe does not crash');
})();

(function testSubscriberErrorDoesNotBreakOthers() {
    const store = createStore();
    let secondCalled = false;
    // Suppress console.error during this test
    const origError = console.error;
    const errors = [];
    console.error = (...args) => errors.push(args);
    store.on('game.phase', () => { throw new Error('boom'); });
    store.on('game.phase', () => { secondCalled = true; });
    store.set('game.phase', 'active');
    console.error = origError;
    assert(secondCalled, 'second subscriber called even when first throws');
    assert(errors.length > 0, 'error was logged for throwing subscriber');
})();

// ============================================================
// 5. Wildcard subscriber ('*')
// ============================================================

console.log('\n--- Wildcard Subscriber ---');

(function testWildcardReceivesAllChanges() {
    const store = createStore();
    const received = [];
    store.on('*', (path, value) => received.push({ path, value }));
    store.set('game.phase', 'active');
    store.set('game.wave', 3);
    store.set('amy.mood', 'excited');
    assertEqual(received.length, 3, 'wildcard received 3 notifications');
    assertEqual(received[0].path, 'game.phase', 'wildcard first path is game.phase');
    assertEqual(received[0].value, 'active', 'wildcard first value is active');
    assertEqual(received[1].path, 'game.wave', 'wildcard second path is game.wave');
    assertEqual(received[2].path, 'amy.mood', 'wildcard third path is amy.mood');
})();

(function testWildcardAndSpecificBothFire() {
    const store = createStore();
    let specificCalled = false, wildcardCalled = false;
    store.on('game.phase', () => { specificCalled = true; });
    store.on('*', () => { wildcardCalled = true; });
    store.set('game.phase', 'battle');
    assert(specificCalled, 'specific subscriber called');
    assert(wildcardCalled, 'wildcard subscriber called');
})();

(function testUnsubscribeWildcard() {
    const store = createStore();
    let count = 0;
    const unsub = store.on('*', () => count++);
    store.set('game.phase', 'active');
    assertEqual(count, 1, 'wildcard called once');
    unsub();
    store.set('game.phase', 'idle');
    assertEqual(count, 1, 'wildcard NOT called after unsubscribe');
})();

// ============================================================
// 6. Unit telemetry (Map-based storage)
// ============================================================

console.log('\n--- Unit Telemetry ---');

(function testUpdateUnitCreatesNew() {
    const store = createStore();
    store.updateUnit('turret-1', { type: 'turret', health: 100, position: { x: 5, y: 10 } });
    const unit = store.units.get('turret-1');
    assertEqual(unit.id, 'turret-1', 'updateUnit sets id on new unit');
    assertEqual(unit.type, 'turret', 'updateUnit sets type on new unit');
    assertEqual(unit.health, 100, 'updateUnit sets health on new unit');
    assertEqual(unit.position.x, 5, 'updateUnit sets nested position.x');
})();

(function testUpdateUnitMergesFields() {
    const store = createStore();
    store.updateUnit('drone-1', { type: 'drone', health: 100 });
    store.updateUnit('drone-1', { health: 75, battery: 80 });
    const unit = store.units.get('drone-1');
    assertEqual(unit.type, 'drone', 'merge preserves existing type');
    assertEqual(unit.health, 75, 'merge updates health');
    assertEqual(unit.battery, 80, 'merge adds new battery field');
    assertEqual(unit.id, 'drone-1', 'merge preserves id');
})();

(function testUpdateUnitIdOverridesSafely() {
    const store = createStore();
    store.updateUnit('rover-1', { id: 'wrong-id', type: 'rover' });
    const unit = store.units.get('rover-1');
    assertEqual(unit.id, 'rover-1', 'updateUnit forces id to match key parameter');
})();

(function testUpdateUnitNotifiesListeners() {
    const store = createStore();
    let notified = false;
    store.on('units', () => { notified = true; });
    store.updateUnit('turret-1', { type: 'turret' });
    assert(notified, 'updateUnit notifies units listeners');
})();

(function testUpdateUnitNotifiesWithMapValue() {
    const store = createStore();
    let receivedVal = null;
    store.on('units', (val) => { receivedVal = val; });
    store.updateUnit('tank-1', { type: 'tank' });
    assert(receivedVal instanceof Map, 'units listener receives Map');
    assertEqual(receivedVal.size, 1, 'units listener receives Map with 1 entry');
})();

(function testRemoveUnit() {
    const store = createStore();
    store.updateUnit('drone-1', { type: 'drone' });
    assertEqual(store.units.size, 1, 'units has 1 entry before remove');
    store.removeUnit('drone-1');
    assertEqual(store.units.size, 0, 'units is empty after removeUnit');
})();

(function testRemoveUnitNotifiesListeners() {
    const store = createStore();
    store.updateUnit('drone-1', { type: 'drone' });
    let notified = false;
    store.on('units', () => { notified = true; });
    store.removeUnit('drone-1');
    assert(notified, 'removeUnit notifies units listeners');
})();

(function testRemoveNonexistentUnit() {
    const store = createStore();
    let notified = false;
    store.on('units', () => { notified = true; });
    store.removeUnit('nonexistent');
    // Map.delete on missing key returns false but does not throw
    assert(notified, 'removeUnit on missing key still notifies (Map.delete is safe)');
})();

(function testMultipleUnits() {
    const store = createStore();
    store.updateUnit('turret-1', { type: 'turret' });
    store.updateUnit('drone-1', { type: 'drone' });
    store.updateUnit('rover-1', { type: 'rover' });
    assertEqual(store.units.size, 3, 'units map has 3 entries after 3 updateUnit calls');
    assertEqual(store.units.get('turret-1').type, 'turret', 'turret-1 is turret');
    assertEqual(store.units.get('drone-1').type, 'drone', 'drone-1 is drone');
    assertEqual(store.units.get('rover-1').type, 'rover', 'rover-1 is rover');
})();

(function testUpdateUnitWildcardNotified() {
    const store = createStore();
    let wildcardPath = null;
    store.on('*', (path) => { wildcardPath = path; });
    store.updateUnit('tank-1', { type: 'tank' });
    assertEqual(wildcardPath, 'units', 'wildcard receives "units" path on updateUnit');
})();

// ============================================================
// 7. Alerts
// ============================================================

console.log('\n--- Alerts ---');

(function testAddAlertPrependsToList() {
    const store = createStore();
    store.addAlert({ type: 'threat', message: 'Hostile detected', source: 'sim' });
    assertEqual(store.alerts.length, 1, 'alerts has 1 entry after addAlert');
    assertEqual(store.alerts[0].type, 'threat', 'alert type is threat');
    assertEqual(store.alerts[0].message, 'Hostile detected', 'alert message matches');
    assertEqual(store.alerts[0].source, 'sim', 'alert source matches');
    assertEqual(store.alerts[0].read, false, 'alert.read defaults to false');
})();

(function testAddAlertHasIdAndTime() {
    const store = createStore();
    store.addAlert({ type: 'info', message: 'Test' });
    assert(typeof store.alerts[0].id === 'number', 'alert has numeric id (from Date.now)');
    assert(store.alerts[0].time instanceof Date, 'alert has Date time');
})();

(function testAddAlertPrependsNewestFirst() {
    const store = createStore();
    store.addAlert({ type: 'a', message: 'First' });
    store.addAlert({ type: 'b', message: 'Second' });
    assertEqual(store.alerts[0].message, 'Second', 'newest alert is at index 0');
    assertEqual(store.alerts[1].message, 'First', 'older alert is at index 1');
})();

(function testAddAlertCapsAt100() {
    const store = createStore();
    for (let i = 0; i < 105; i++) {
        store.addAlert({ type: 'test', message: 'Alert ' + i });
    }
    assertEqual(store.alerts.length, 100, 'alerts capped at 100 entries');
    assertEqual(store.alerts[0].message, 'Alert 104', 'newest alert is at front');
})();

(function testAddAlertNotifiesListeners() {
    const store = createStore();
    let notified = false;
    store.on('alerts', () => { notified = true; });
    store.addAlert({ type: 'test', message: 'Test' });
    assert(notified, 'addAlert notifies alerts listeners');
})();

(function testAddAlertNotifiesWildcard() {
    const store = createStore();
    let wildcardPath = null;
    store.on('*', (path) => { wildcardPath = path; });
    store.addAlert({ type: 'test', message: 'Test' });
    assertEqual(wildcardPath, 'alerts', 'wildcard receives "alerts" path on addAlert');
})();

// ============================================================
// 8. Bulk state updates via set
// ============================================================

console.log('\n--- Bulk State Updates ---');

(function testSetEntireGameObject() {
    const store = createStore();
    store.set('game', { phase: 'active', wave: 5, totalWaves: 10, score: 3000, eliminations: 12 });
    assertEqual(store.game.phase, 'active', 'bulk set game.phase');
    assertEqual(store.game.wave, 5, 'bulk set game.wave');
    assertEqual(store.game.score, 3000, 'bulk set game.score');
    assertEqual(store.game.eliminations, 12, 'bulk set game.eliminations');
})();

(function testSetEntireAmyObject() {
    const store = createStore();
    store.set('amy', { state: 'thinking', mood: 'alert', lastThought: 'Scanning...', speaking: true, nodeCount: 3 });
    assertEqual(store.amy.state, 'thinking', 'bulk set amy.state');
    assertEqual(store.amy.mood, 'alert', 'bulk set amy.mood');
    assertEqual(store.amy.lastThought, 'Scanning...', 'bulk set amy.lastThought');
    assertEqual(store.amy.speaking, true, 'bulk set amy.speaking');
    assertEqual(store.amy.nodeCount, 3, 'bulk set amy.nodeCount');
})();

(function testMultipleRapidSetsAllNotify() {
    const store = createStore();
    let count = 0;
    store.on('game.wave', () => count++);
    store.set('game.wave', 1);
    store.set('game.wave', 2);
    store.set('game.wave', 3);
    assertEqual(count, 3, 'rapid set calls each trigger notification');
})();

(function testSetConnectionStatus() {
    const store = createStore();
    let received = null;
    store.on('connection.status', (val) => { received = val; });
    store.set('connection.status', 'connected');
    assertEqual(received, 'connected', 'set("connection.status") notifies with new value');
    assertEqual(store.connection.status, 'connected', 'connection.status updated');
})();

// ============================================================
// 9. Edge cases
// ============================================================

console.log('\n--- Edge Cases ---');

(function testSetSingleSegmentPath() {
    const store = createStore();
    // Set a top-level property that replaces the whole thing
    store.set('cameras', [{ id: 'cam-1' }]);
    assertEqual(store.cameras.length, 1, 'set("cameras", [...]) replaces array');
    assertEqual(store.cameras[0].id, 'cam-1', 'new cameras array accessible');
})();

(function testGetSingleSegmentPath() {
    const store = createStore();
    const alerts = store.get('alerts');
    assert(Array.isArray(alerts), 'get("alerts") returns the alerts array');
})();

(function testSetEmptyStringPath() {
    const store = createStore();
    // '' split by '.' yields [''], setting store[''] = value
    store.set('', 'test');
    assertEqual(store[''], 'test', 'set("", value) sets store[""]');
})();

(function testGetEmptyStringPath() {
    const store = createStore();
    store[''] = 'something';
    assertEqual(store.get(''), 'something', 'get("") returns store[""]');
})();

(function testDeepNestingCreation() {
    const store = createStore();
    store.set('a.b.c.d.e.f', 'deep');
    assertEqual(store.get('a.b.c.d.e.f'), 'deep', '6-level deep nesting created correctly');
    assertEqual(typeof store.a.b.c.d.e, 'object', 'intermediate objects are plain objects');
})();

(function testSetThroughPrimitiveDoesNotMutateString() {
    const store = createStore();
    store.set('game.phase', 'active');
    // Setting a child of a string primitive: set() checks if obj[parts[i]] is
    // undefined/null and creates an intermediate object. A string is neither,
    // so set() traverses into the string wrapper. JS strings are immutable
    // primitives, so the assignment to .sub on a temporary wrapper is silently
    // discarded. The original string value remains unchanged.
    store.set('game.phase.sub', 'value');
    assertEqual(store.game.phase, 'active', 'original string value preserved after set through primitive');
    // get('game.phase.sub') returns String.prototype.sub (the old HTML wrapper
    // method), not 'value', because the set was silently discarded.
    assertEqual(typeof store.get('game.phase.sub'), 'function', 'get through string returns String.prototype.sub method');
})();

(function testSetArrayValue() {
    const store = createStore();
    store.set('custom.list', [1, 2, 3]);
    assertDeepEqual(store.get('custom.list'), [1, 2, 3], 'set can store array value');
})();

(function testSetMapSelectedUnitId() {
    const store = createStore();
    store.set('map.selectedUnitId', 'drone-1');
    assertEqual(store.map.selectedUnitId, 'drone-1', 'set("map.selectedUnitId") updates from null to string');
    assertEqual(store.get('map.selectedUnitId'), 'drone-1', 'get("map.selectedUnitId") returns string');
})();

(function testSetBackToNull() {
    const store = createStore();
    store.set('map.selectedUnitId', 'turret-1');
    store.set('map.selectedUnitId', null);
    assertEqual(store.map.selectedUnitId, null, 'set back to null works');
})();

(function testSetFromNullNotifies() {
    const store = createStore();
    let callCount = 0;
    store.on('map.selectedUnitId', () => callCount++);
    store.set('map.selectedUnitId', 'rover-1');
    assertEqual(callCount, 1, 'setting from null to value notifies');
})();

(function testSetToNullNotifies() {
    const store = createStore();
    store.set('map.selectedUnitId', 'rover-1');
    let callCount = 0;
    store.on('map.selectedUnitId', () => callCount++);
    store.set('map.selectedUnitId', null);
    assertEqual(callCount, 1, 'setting from value to null notifies');
})();

(function testSetNullToNullNoOp() {
    const store = createStore();
    // selectedUnitId starts as null
    let callCount = 0;
    store.on('map.selectedUnitId', () => callCount++);
    store.set('map.selectedUnitId', null);
    assertEqual(callCount, 0, 'setting null to null is no-op (null === null)');
})();

(function testSetUndefinedToUndefinedNoOp() {
    const store = createStore();
    store.set('game.phase', undefined);
    let callCount = 0;
    store.on('game.phase', () => callCount++);
    store.set('game.phase', undefined);
    assertEqual(callCount, 0, 'setting undefined to undefined is no-op');
})();

(function testSetZeroToZeroNoOp() {
    const store = createStore();
    // game.score starts at 0
    let callCount = 0;
    store.on('game.score', () => callCount++);
    store.set('game.score', 0);
    assertEqual(callCount, 0, 'setting 0 to 0 is no-op');
})();

(function testSetFalseToFalseNoOp() {
    const store = createStore();
    // amy.speaking starts as false
    let callCount = 0;
    store.on('amy.speaking', () => callCount++);
    store.set('amy.speaking', false);
    assertEqual(callCount, 0, 'setting false to false is no-op');
})();

(function testSetEmptyStringToEmptyStringNoOp() {
    const store = createStore();
    // amy.lastThought starts as ''
    let callCount = 0;
    store.on('amy.lastThought', () => callCount++);
    store.set('amy.lastThought', '');
    assertEqual(callCount, 0, 'setting empty string to empty string is no-op');
})();

// ============================================================
// 10. Listener isolation between paths
// ============================================================

console.log('\n--- Listener Isolation ---');

(function testListenersIsolatedBetweenPaths() {
    const store = createStore();
    const calls = { game: 0, amy: 0, map: 0 };
    store.on('game.phase', () => calls.game++);
    store.on('amy.state', () => calls.amy++);
    store.on('map.mode', () => calls.map++);
    store.set('game.phase', 'active');
    assertEqual(calls.game, 1, 'game listener called');
    assertEqual(calls.amy, 0, 'amy listener not called');
    assertEqual(calls.map, 0, 'map listener not called');
})();

(function testParentPathDoesNotTriggerChildListener() {
    const store = createStore();
    let childCalled = false;
    store.on('game.phase', () => { childCalled = true; });
    // Setting 'game' as a whole does NOT trigger 'game.phase' listener
    // because _notify is called with path='game', not 'game.phase'
    store.set('game', { phase: 'battle', wave: 1, totalWaves: 10, score: 0, eliminations: 0 });
    assertEqual(childCalled, false, 'setting parent path does not trigger child path listener');
})();

(function testChildPathDoesNotTriggerParentListener() {
    const store = createStore();
    let parentCalled = false;
    store.on('game', () => { parentCalled = true; });
    store.set('game.phase', 'active');
    assertEqual(parentCalled, false, 'setting child path does not trigger parent path listener');
})();

// ============================================================
// 11. Multiple subscriptions and cleanup
// ============================================================

console.log('\n--- Multiple Subscriptions ---');

(function testManyListenersOnSamePath() {
    const store = createStore();
    const counts = [0, 0, 0, 0, 0];
    const unsubs = counts.map((_, i) => store.on('game.wave', () => counts[i]++));
    store.set('game.wave', 7);
    assert(counts.every(c => c === 1), 'all 5 listeners called once each');
    // Unsubscribe half
    unsubs[0]();
    unsubs[2]();
    unsubs[4]();
    store.set('game.wave', 8);
    assertDeepEqual(counts, [1, 2, 1, 2, 1], 'only active listeners called on second set');
})();

(function testSubscribeAfterSetWorksForNextChange() {
    const store = createStore();
    store.set('game.phase', 'active');
    let received = null;
    store.on('game.phase', (val) => { received = val; });
    store.set('game.phase', 'game_over');
    assertEqual(received, 'game_over', 'late subscriber receives next change');
})();

// ============================================================
// 12. _notify direct call validation
// ============================================================

console.log('\n--- _notify ---');

(function testNotifyWithNoListenersDoesNotCrash() {
    const store = createStore();
    store._notify('nonexistent.path', 'value', 'oldValue');
    assert(true, '_notify with no listeners does not crash');
})();

(function testNotifyWildcardErrorDoesNotBreakSpecific() {
    const store = createStore();
    let specificCalled = false;
    const origError = console.error;
    console.error = () => {};
    store.on('*', () => { throw new Error('wildcard boom'); });
    store.on('game.phase', () => { specificCalled = true; });
    // Wildcard is called after specific for same path via _notify
    // But _notify calls path listeners first, then wildcard
    store.set('game.phase', 'active');
    console.error = origError;
    assert(specificCalled, 'specific listener called even when wildcard throws');
})();

// ============================================================
// 13. Realistic scenario: game lifecycle
// ============================================================

console.log('\n--- Realistic Scenario ---');

(function testGameLifecycle() {
    const store = createStore();
    const phaseHistory = [];
    store.on('game.phase', (val) => phaseHistory.push(val));

    // Idle -> setup -> countdown -> active -> wave_complete -> active -> game_over
    store.set('game.phase', 'setup');
    store.set('game.phase', 'countdown');
    store.set('game.phase', 'active');
    store.set('game.wave', 1);
    store.set('game.score', 150);
    store.set('game.phase', 'wave_complete');
    store.set('game.phase', 'active');
    store.set('game.wave', 2);
    store.set('game.score', 350);
    store.set('game.eliminations', 5);
    store.set('game.phase', 'game_over');

    assertDeepEqual(phaseHistory,
        ['setup', 'countdown', 'active', 'wave_complete', 'active', 'game_over'],
        'game lifecycle phase transitions recorded correctly');
    assertEqual(store.game.wave, 2, 'final wave is 2');
    assertEqual(store.game.score, 350, 'final score is 350');
    assertEqual(store.game.eliminations, 5, 'final eliminations is 5');
})();

(function testUnitTelemetryScenario() {
    const store = createStore();
    let updateCount = 0;
    store.on('units', () => updateCount++);

    // Spawn units
    store.updateUnit('turret-1', { type: 'turret', health: 100, maxHealth: 100, position: { x: 10, y: 20 } });
    store.updateUnit('drone-1', { type: 'drone', health: 80, maxHealth: 80, battery: 95, position: { x: 30, y: 40 } });
    store.updateUnit('hostile-1', { type: 'hostile_person', health: 50, maxHealth: 50, position: { x: 100, y: 100 } });

    // Update positions (telemetry)
    store.updateUnit('drone-1', { position: { x: 35, y: 45 }, battery: 90 });
    store.updateUnit('hostile-1', { position: { x: 90, y: 95 } });

    // Damage
    store.updateUnit('hostile-1', { health: 25 });

    // Eliminate
    store.removeUnit('hostile-1');

    assertEqual(updateCount, 7, '7 unit notifications (3 spawns + 2 moves + 1 damage + 1 remove)');
    assertEqual(store.units.size, 2, '2 units remain after elimination');
    assertEqual(store.units.get('drone-1').battery, 90, 'drone battery updated');
    assertEqual(store.units.get('drone-1').type, 'drone', 'drone type preserved through updates');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
