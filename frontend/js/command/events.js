// EventBus -- simple pub/sub for frontend UI events
// Usage:
//   import { EventBus } from './events.js';
//   const unsub = EventBus.on('unit:selected', (data) => console.log(data));
//   EventBus.emit('unit:selected', { id: 'rover-01' });
//   unsub();  // unsubscribe

export const EventBus = {
    _handlers: new Map(),

    /**
     * Subscribe to an event.
     * @param {string} event - event name, or '*' for all events
     * @param {Function} handler - callback(data) or callback(event, data) for '*'
     * @returns {Function} unsubscribe function
     */
    on(event, handler) {
        if (!this._handlers.has(event)) this._handlers.set(event, new Set());
        this._handlers.get(event).add(handler);
        return () => this._handlers.get(event)?.delete(handler);
    },

    /**
     * Unsubscribe a specific handler from an event.
     * @param {string} event
     * @param {Function} handler
     */
    off(event, handler) {
        this._handlers.get(event)?.delete(handler);
    },

    /**
     * Emit an event to all subscribers.
     * @param {string} event
     * @param {*} data
     */
    emit(event, data) {
        this._handlers.get(event)?.forEach(handler => {
            try {
                handler(data);
            } catch (e) {
                console.error(`[EventBus] ${event} handler error:`, e);
            }
        });
        // Also emit to '*' for debugging/logging
        this._handlers.get('*')?.forEach(handler => {
            try { handler(event, data); } catch (_) { /* ignore debug errors */ }
        });
    },
};

// ---------------------------------------------------------------------------
// Standard events reference:
// ---------------------------------------------------------------------------
//
// Unit events:
//   'unit:selected'       { id }
//   'unit:deselected'     {}
//   'unit:dispatched'     { id, target: {x, y} }
//   'unit:recalled'       { id }
//   'units:updated'       [ ...targets ]
//
// Amy events:
//   'amy:thought'         { text, timestamp }
//   'amy:speech'          { text, action }
//   'amy:state'           { state, mood }
//
// Game events:
//   'game:state'          { phase, wave, score, eliminations }
//   'game:elimination'    { interceptor, target, weapon }
//
// Alert events:
//   'alert:new'           { type, message, source }
//
// Announcer events:
//   'announcer'           { text, priority }
//
// Camera events:
//   'camera:frame'        { cameraId, data }
//   'detection'           { cameraId, boxes, ... }
//
// UI events:
//   'toast:show'          { message, type, duration }
//   'chat:open'           {}
//   'chat:close'          {}
//   'sidebar:toggle'      {}
//
// Robot events:
//   'robot:thought'       { robotId, name, text }
//
// WebSocket lifecycle:
//   'ws:connected'        undefined
//   'ws:disconnected'     undefined
