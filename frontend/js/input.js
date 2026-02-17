/**
 * TRITIUM-SC Input Manager
 * Unified input handling for keyboard + gamepad navigation
 * Enables full UI control without mouse
 */

// =============================================================================
// CONSTANTS
// =============================================================================

const GAMEPAD_DEADZONE = 0.25;
const GAMEPAD_POLL_INTERVAL = 16; // ~60fps
const REPEAT_DELAY = 400; // Initial delay before repeat
const REPEAT_RATE = 100; // Repeat rate in ms

// Standard gamepad button mapping (Xbox layout)
const GAMEPAD_BUTTONS = {
    A: 0,           // Confirm/Select
    B: 1,           // Back/Cancel
    X: 2,           // Context menu
    Y: 3,           // Secondary action
    LB: 4,          // Previous view
    RB: 5,          // Next view
    LT: 6,          // Page up / Jump back
    RT: 7,          // Page down / Jump forward
    SELECT: 8,      // Help overlay
    START: 9,       // Main menu
    L3: 10,         // Toggle sidebar
    R3: 11,         // Reset view
    DPAD_UP: 12,
    DPAD_DOWN: 13,
    DPAD_LEFT: 14,
    DPAD_RIGHT: 15,
};

// Axis indices
const GAMEPAD_AXES = {
    LEFT_X: 0,
    LEFT_Y: 1,
    RIGHT_X: 2,
    RIGHT_Y: 3,
};

// View order for LB/RB navigation
const VIEW_ORDER = ['grid', 'player', '3d', 'zones', 'targets', 'assets', 'analytics', 'war'];

// =============================================================================
// FOCUS MANAGER
// =============================================================================

class FocusManager {
    constructor() {
        this.currentView = 'grid';
        this.focusableElements = new Map(); // view -> array of elements
        this.currentFocusIndex = new Map(); // view -> index
        this.focusTrapStack = []; // For modal focus trapping
    }

    /**
     * Register focusable elements for a view
     */
    setFocusables(view, selector) {
        const elements = Array.from(document.querySelectorAll(selector));
        this.focusableElements.set(view, elements);
        if (!this.currentFocusIndex.has(view)) {
            this.currentFocusIndex.set(view, 0);
        }
    }

    /**
     * Update focusables for current view (call after DOM changes)
     */
    updateFocusables(view) {
        const selectors = this.getSelectorsForView(view);
        if (selectors) {
            this.setFocusables(view, selectors);
        }
    }

    /**
     * Get CSS selectors for focusable elements in each view
     */
    getSelectorsForView(view) {
        const selectorMap = {
            'grid': '#video-grid .video-cell, .channel-item, .date-item',
            'player': '.play-btn, .timeline, .video-list-item',
            '3d': '.btn-cyber[onclick*="switchView"]',
            'zones': '#zone-list .zone-item, #btn-draw-zone, .zone-events-item',
            'targets': '.target-card, #btn-target-people, #btn-target-vehicles, #target-load-more button',
            'assets': '.asset-item, .task-btn',
            'analytics': '.stat-box, .btn-cyber',
            'list': '.video-list-item',
        };
        return selectorMap[view] || '.btn-cyber, button, [data-focusable]';
    }

    /**
     * Set current view and update focusables
     */
    setView(view) {
        this.currentView = view;
        this.updateFocusables(view);
        this.focusFirst();
    }

    /**
     * Get currently focused element
     */
    getCurrentFocusable() {
        const elements = this.focusableElements.get(this.currentView) || [];
        const index = this.currentFocusIndex.get(this.currentView) || 0;
        return elements[index] || null;
    }

    /**
     * Focus first element in current view
     */
    focusFirst() {
        const elements = this.focusableElements.get(this.currentView) || [];
        if (elements.length > 0) {
            this.currentFocusIndex.set(this.currentView, 0);
            this.applyFocus(elements[0]);
        }
    }

    /**
     * Move focus in a direction
     */
    moveFocus(direction) {
        const elements = this.focusableElements.get(this.currentView) || [];
        if (elements.length === 0) return;

        let index = this.currentFocusIndex.get(this.currentView) || 0;

        // Calculate grid dimensions if in grid view
        const isGrid = this.currentView === 'grid' || this.currentView === 'targets';
        let columns = 1;

        if (isGrid) {
            const container = elements[0]?.parentElement;
            if (container) {
                const style = getComputedStyle(container);
                const templateColumns = style.gridTemplateColumns;
                if (templateColumns && templateColumns !== 'none') {
                    columns = templateColumns.split(' ').length;
                }
            }
        }

        // Calculate new index based on direction
        switch (direction) {
            case 'up':
                if (isGrid && columns > 1) {
                    index = Math.max(0, index - columns);
                } else {
                    index = Math.max(0, index - 1);
                }
                break;
            case 'down':
                if (isGrid && columns > 1) {
                    index = Math.min(elements.length - 1, index + columns);
                } else {
                    index = Math.min(elements.length - 1, index + 1);
                }
                break;
            case 'left':
                index = Math.max(0, index - 1);
                break;
            case 'right':
                index = Math.min(elements.length - 1, index + 1);
                break;
        }

        this.currentFocusIndex.set(this.currentView, index);
        this.applyFocus(elements[index]);
    }

    /**
     * Apply focus visual and scroll into view
     */
    applyFocus(element) {
        if (!element) return;

        // Remove focus from all elements
        document.querySelectorAll('.gamepad-focus').forEach(el => {
            el.classList.remove('gamepad-focus');
        });

        // Add focus to current element
        element.classList.add('gamepad-focus');

        // Scroll into view if needed
        element.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });

        // Update aria-activedescendant if applicable
        const container = element.closest('[role="listbox"], [role="grid"]');
        if (container && element.id) {
            container.setAttribute('aria-activedescendant', element.id);
        }
    }

    /**
     * Activate (click) the currently focused element
     */
    activateCurrent() {
        const element = this.getCurrentFocusable();
        if (element) {
            element.click();
            return true;
        }
        return false;
    }

    /**
     * Push a focus trap (for modals)
     */
    pushFocusTrap(containerSelector) {
        this.focusTrapStack.push({
            view: this.currentView,
            index: this.currentFocusIndex.get(this.currentView),
        });

        const container = document.querySelector(containerSelector);
        if (container) {
            const focusables = container.querySelectorAll(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );
            this.focusableElements.set('modal', Array.from(focusables));
            this.currentFocusIndex.set('modal', 0);
            this.currentView = 'modal';
            this.focusFirst();
        }
    }

    /**
     * Pop a focus trap (modal closed)
     */
    popFocusTrap() {
        const previous = this.focusTrapStack.pop();
        if (previous) {
            this.currentView = previous.view;
            this.currentFocusIndex.set(this.currentView, previous.index);
            this.applyFocus(this.getCurrentFocusable());
        }
        this.focusableElements.delete('modal');
    }
}

// =============================================================================
// GAMEPAD HANDLER
// =============================================================================

class GamepadHandler {
    constructor(inputManager) {
        this.inputManager = inputManager;
        this.connected = false;
        this.gamepadIndex = null;
        this.previousButtonStates = new Array(16).fill(false);
        this.previousAxes = new Array(4).fill(0);
        this.buttonHoldTimers = {};
        this.lastAxisTime = {};
        this.animationFrameId = null;
    }

    /**
     * Start listening for gamepad connections
     */
    start() {
        window.addEventListener('gamepadconnected', (e) => this.onGamepadConnected(e));
        window.addEventListener('gamepaddisconnected', (e) => this.onGamepadDisconnected(e));

        // Check for already-connected gamepads
        const gamepads = navigator.getGamepads();
        for (let i = 0; i < gamepads.length; i++) {
            if (gamepads[i]) {
                this.onGamepadConnected({ gamepad: gamepads[i] });
                break;
            }
        }

        // Start polling
        this.poll();
    }

    /**
     * Stop gamepad polling
     */
    stop() {
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }
    }

    /**
     * Handle gamepad connection
     */
    onGamepadConnected(event) {
        const gamepad = event.gamepad;
        console.log(`%c[GAMEPAD] Connected: ${gamepad.id}`, 'color: #05ffa1;');

        this.connected = true;
        this.gamepadIndex = gamepad.index;

        // Show notification
        if (typeof showNotification === 'function') {
            showNotification('GAMEPAD', `${gamepad.id.split('(')[0].trim()} connected`, 'success');
        }

        // Update indicator
        if (typeof updateGamepadIndicator === 'function') {
            updateGamepadIndicator(true);
        }

        // Vibrate briefly to confirm
        this.vibrate(100, 0.3, 0.3);
    }

    /**
     * Handle gamepad disconnection
     */
    onGamepadDisconnected(event) {
        const gamepad = event.gamepad;
        console.log(`%c[GAMEPAD] Disconnected: ${gamepad.id}`, 'color: #ff2a6d;');

        if (this.gamepadIndex === gamepad.index) {
            this.connected = false;
            this.gamepadIndex = null;

            if (typeof showNotification === 'function') {
                showNotification('GAMEPAD', 'Controller disconnected', 'error');
            }

            // Update indicator
            if (typeof updateGamepadIndicator === 'function') {
                updateGamepadIndicator(false);
            }
        }
    }

    /**
     * Main polling loop
     */
    poll() {
        this.animationFrameId = requestAnimationFrame(() => this.poll());

        if (!this.connected || this.gamepadIndex === null) return;

        const gamepads = navigator.getGamepads();
        const gamepad = gamepads[this.gamepadIndex];
        if (!gamepad) return;

        // Process buttons
        this.processButtons(gamepad);

        // Process axes (sticks)
        this.processAxes(gamepad);
    }

    /**
     * Process button inputs
     */
    processButtons(gamepad) {
        for (let i = 0; i < gamepad.buttons.length; i++) {
            const button = gamepad.buttons[i];
            const pressed = button.pressed || button.value > 0.5;
            const wasPressed = this.previousButtonStates[i];

            // Button just pressed
            if (pressed && !wasPressed) {
                this.onButtonDown(i);
            }

            // Button released
            if (!pressed && wasPressed) {
                this.onButtonUp(i);
            }

            // Handle button hold for repeat
            if (pressed && wasPressed) {
                this.handleButtonHold(i);
            }

            this.previousButtonStates[i] = pressed;
        }
    }

    /**
     * Handle button press
     */
    onButtonDown(buttonIndex) {
        const action = this.mapButtonToAction(buttonIndex);
        if (action) {
            this.inputManager.executeAction(action);
        }

        // Start hold timer for D-pad buttons
        if (buttonIndex >= GAMEPAD_BUTTONS.DPAD_UP && buttonIndex <= GAMEPAD_BUTTONS.DPAD_RIGHT) {
            this.buttonHoldTimers[buttonIndex] = {
                startTime: Date.now(),
                repeating: false,
            };
        }
    }

    /**
     * Handle button release
     */
    onButtonUp(buttonIndex) {
        delete this.buttonHoldTimers[buttonIndex];
    }

    /**
     * Handle button being held
     */
    handleButtonHold(buttonIndex) {
        const timer = this.buttonHoldTimers[buttonIndex];
        if (!timer) return;

        const elapsed = Date.now() - timer.startTime;

        if (!timer.repeating && elapsed > REPEAT_DELAY) {
            timer.repeating = true;
            timer.lastRepeat = Date.now();
            this.onButtonDown(buttonIndex);
        } else if (timer.repeating && Date.now() - timer.lastRepeat > REPEAT_RATE) {
            timer.lastRepeat = Date.now();
            this.onButtonDown(buttonIndex);
        }
    }

    /**
     * Map button index to action
     */
    mapButtonToAction(buttonIndex) {
        const actionMap = {
            [GAMEPAD_BUTTONS.A]: 'confirm',
            [GAMEPAD_BUTTONS.B]: 'back',
            [GAMEPAD_BUTTONS.X]: 'context',
            [GAMEPAD_BUTTONS.Y]: 'secondary',
            [GAMEPAD_BUTTONS.LB]: 'view_prev',
            [GAMEPAD_BUTTONS.RB]: 'view_next',
            [GAMEPAD_BUTTONS.LT]: 'page_up',
            [GAMEPAD_BUTTONS.RT]: 'page_down',
            [GAMEPAD_BUTTONS.SELECT]: 'help',
            [GAMEPAD_BUTTONS.START]: 'menu',
            [GAMEPAD_BUTTONS.L3]: 'toggle_sidebar',
            [GAMEPAD_BUTTONS.R3]: 'reset_view',
            [GAMEPAD_BUTTONS.DPAD_UP]: 'nav_up',
            [GAMEPAD_BUTTONS.DPAD_DOWN]: 'nav_down',
            [GAMEPAD_BUTTONS.DPAD_LEFT]: 'nav_left',
            [GAMEPAD_BUTTONS.DPAD_RIGHT]: 'nav_right',
        };
        return actionMap[buttonIndex];
    }

    /**
     * Process analog stick inputs
     */
    processAxes(gamepad) {
        const now = Date.now();

        // Left stick for navigation/scrolling
        const leftX = this.applyDeadzone(gamepad.axes[GAMEPAD_AXES.LEFT_X]);
        const leftY = this.applyDeadzone(gamepad.axes[GAMEPAD_AXES.LEFT_Y]);

        // Convert stick to navigation with rate limiting
        if (Math.abs(leftX) > 0 || Math.abs(leftY) > 0) {
            const lastNav = this.lastAxisTime.leftNav || 0;
            const navRate = 200 - Math.max(Math.abs(leftX), Math.abs(leftY)) * 100; // Faster for larger deflection

            if (now - lastNav > navRate) {
                if (Math.abs(leftY) > Math.abs(leftX)) {
                    this.inputManager.executeAction(leftY < 0 ? 'nav_up' : 'nav_down');
                } else {
                    this.inputManager.executeAction(leftX < 0 ? 'nav_left' : 'nav_right');
                }
                this.lastAxisTime.leftNav = now;
            }
        }

        // Right stick for 3D camera control
        const rightX = this.applyDeadzone(gamepad.axes[GAMEPAD_AXES.RIGHT_X]);
        const rightY = this.applyDeadzone(gamepad.axes[GAMEPAD_AXES.RIGHT_Y]);

        if (Math.abs(rightX) > 0 || Math.abs(rightY) > 0) {
            this.inputManager.executeAction('camera_move', { x: rightX, y: rightY });
        }

        this.previousAxes = [leftX, leftY, rightX, rightY];
    }

    /**
     * Apply deadzone to axis value
     */
    applyDeadzone(value) {
        if (Math.abs(value) < GAMEPAD_DEADZONE) return 0;
        // Rescale to 0-1 range after deadzone
        const sign = value > 0 ? 1 : -1;
        return sign * (Math.abs(value) - GAMEPAD_DEADZONE) / (1 - GAMEPAD_DEADZONE);
    }

    /**
     * Vibrate the gamepad
     */
    vibrate(duration = 100, weakMagnitude = 0.5, strongMagnitude = 0.5) {
        if (!this.connected || this.gamepadIndex === null) return;

        const gamepads = navigator.getGamepads();
        const gamepad = gamepads[this.gamepadIndex];

        if (gamepad && gamepad.vibrationActuator) {
            gamepad.vibrationActuator.playEffect('dual-rumble', {
                startDelay: 0,
                duration: duration,
                weakMagnitude: weakMagnitude,
                strongMagnitude: strongMagnitude,
            }).catch(() => {}); // Ignore errors
        }
    }
}

// =============================================================================
// TRITIUM INPUT MANAGER
// =============================================================================

class TritiumInputManager {
    constructor() {
        this.focusManager = new FocusManager();
        this.gamepadHandler = new GamepadHandler(this);
        this.enabled = true;
        this.gamepadEnabled = true;
    }

    /**
     * Initialize the input system
     */
    init() {
        console.log('%c[INPUT] Initializing TRITIUM Input Manager', 'color: #00f0ff; font-weight: bold;');

        // Start gamepad handling
        this.gamepadHandler.start();

        // Listen for view changes to update focusables
        this.observeViewChanges();

        // Initial setup for current view
        const currentView = TRITIUM?.state?.currentView || 'grid';
        this.focusManager.setView(currentView);

        console.log('%c[INPUT] Input Manager ready', 'color: #05ffa1;');
    }

    /**
     * Observe view changes and update focusables
     */
    observeViewChanges() {
        // Use MutationObserver to detect view content changes
        const viewArea = document.querySelector('.view-area');
        if (viewArea) {
            const observer = new MutationObserver(() => {
                const currentView = TRITIUM?.state?.currentView || 'grid';
                this.focusManager.updateFocusables(currentView);
            });

            observer.observe(viewArea, {
                childList: true,
                subtree: true,
            });
        }
    }

    /**
     * Set current view (called from app.js switchView)
     */
    setView(view) {
        this.focusManager.setView(view);
    }

    /**
     * Execute an input action
     */
    executeAction(action, data = null) {
        if (!this.enabled) return;

        console.log(`%c[INPUT] Action: ${action}`, 'color: #fcee0a;');

        switch (action) {
            // Navigation
            case 'nav_up':
                if (TRITIUM?.state?.currentView === 'war') {
                    this.warCyclePrev();
                } else if (TRITIUM?.state?.currentView === 'player') {
                    if (typeof adjustVolume === 'function') adjustVolume(0.1);
                } else {
                    this.focusManager.moveFocus('up');
                }
                break;
            case 'nav_down':
                if (TRITIUM?.state?.currentView === 'war') {
                    this.warCycleNext();
                } else if (TRITIUM?.state?.currentView === 'player') {
                    if (typeof adjustVolume === 'function') adjustVolume(-0.1);
                } else {
                    this.focusManager.moveFocus('down');
                }
                break;
            case 'nav_left':
                if (TRITIUM?.state?.currentView === 'player') {
                    if (typeof skip === 'function') skip(-10);
                } else {
                    this.focusManager.moveFocus('left');
                }
                break;
            case 'nav_right':
                if (TRITIUM?.state?.currentView === 'player') {
                    if (typeof skip === 'function') skip(10);
                } else {
                    this.focusManager.moveFocus('right');
                }
                break;

            // Actions
            case 'confirm':
                if (TRITIUM?.state?.currentView === 'war') {
                    this.warSelectNearest();
                    this.gamepadHandler.vibrate(50, 0.2, 0.1);
                } else if (TRITIUM?.state?.currentView === 'player') {
                    if (typeof togglePlay === 'function') {
                        togglePlay();
                        this.gamepadHandler.vibrate(50, 0.2, 0.1);
                        break;
                    }
                } else {
                    this.focusManager.activateCurrent();
                    this.gamepadHandler.vibrate(50, 0.2, 0.1);
                }
                break;
            case 'back':
                if (TRITIUM?.state?.currentView === 'war') {
                    if (typeof warState !== 'undefined') {
                        warState.selectedTargets = [];
                        if (typeof updateUnitInfo === 'function') updateUnitInfo();
                    }
                } else {
                    this.handleBack();
                }
                break;
            case 'context':
                if (TRITIUM?.state?.currentView === 'war') {
                    this.warCycleModes();
                } else {
                    this.handleContext();
                }
                break;
            case 'secondary':
                if (TRITIUM?.state?.currentView === 'war') {
                    if (typeof centerOnSelected === 'function') centerOnSelected();
                } else {
                    this.handleSecondary();
                }
                break;

            // View navigation
            case 'view_prev':
                this.navigateView(-1);
                break;
            case 'view_next':
                this.navigateView(1);
                break;

            // Special actions
            case 'help':
                this.toggleHelp();
                break;
            case 'menu':
                this.toggleMenu();
                break;
            case 'toggle_sidebar':
                this.toggleSidebar();
                break;
            case 'reset_view':
                this.resetView();
                break;
            case 'page_up':
                this.handlePageUp();
                break;
            case 'page_down':
                this.handlePageDown();
                break;

            // Camera control (3D + War Room)
            case 'camera_move':
                if (TRITIUM?.state?.currentView === 'war') {
                    this.handleWarCameraMove(data);
                } else {
                    this.handle3DCameraMove(data);
                }
                break;
        }
    }

    /**
     * Handle back action
     */
    handleBack() {
        // Check for open modals first
        const modal = document.querySelector('.modal-overlay');
        if (modal) {
            modal.remove();
            this.focusManager.popFocusTrap();
            return;
        }

        // Check for target detail panel
        const targetDetail = document.getElementById('target-detail-panel');
        if (targetDetail && targetDetail.style.display !== 'none') {
            if (typeof closeTargetDetail === 'function') {
                closeTargetDetail();
            }
            return;
        }

        // Check for context menus
        const contextMenu = document.getElementById('detection-context-menu');
        if (contextMenu) {
            contextMenu.remove();
            return;
        }

        // View-specific back behavior
        const view = TRITIUM?.state?.currentView;
        if (view === 'player') {
            if (typeof switchView === 'function') {
                switchView('grid');
            }
        } else if (view === 'list') {
            if (typeof switchView === 'function') {
                switchView('grid');
            }
        }
    }

    /**
     * Handle context menu action
     */
    handleContext() {
        const current = this.focusManager.getCurrentFocusable();
        if (!current) return;

        const view = TRITIUM?.state?.currentView;

        // Show context menu for current element based on view
        if (view === 'targets' && current.classList.contains('target-card')) {
            // Show target context menu
            const targetId = current.dataset.targetId;
            if (targetId && typeof showTargetContextMenu === 'function') {
                const rect = current.getBoundingClientRect();
                showTargetContextMenu(targetId, rect.left + rect.width / 2, rect.top + rect.height / 2);
            }
        } else if (view === 'zones' && current.classList.contains('zone-item')) {
            // Show zone context menu
            const zoneId = current.dataset.zoneId;
            if (zoneId && typeof showZoneContextMenu === 'function') {
                showZoneContextMenu(zoneId);
            }
        }
    }

    /**
     * Handle secondary action (Y button)
     */
    handleSecondary() {
        const view = TRITIUM?.state?.currentView;
        const current = this.focusManager.getCurrentFocusable();

        switch (view) {
            case 'grid':
                // Quick playback last hour of selected camera
                if (current && current.dataset && current.dataset.channel) {
                    this.quickPlayback(current.dataset.channel);
                } else if (TRITIUM?.state?.selectedChannel) {
                    this.quickPlayback(TRITIUM.state.selectedChannel);
                }
                break;
            case 'player':
                // Toggle fullscreen
                if (typeof toggleFullscreen === 'function') {
                    toggleFullscreen();
                } else {
                    this.toggleFullscreen();
                }
                break;
            case 'targets':
                // Find similar targets
                if (typeof findSimilar === 'function') {
                    findSimilar();
                }
                break;
            case 'zones':
                // Toggle zone enabled
                if (current && current.dataset && current.dataset.zoneId) {
                    if (typeof toggleZone === 'function') {
                        toggleZone(current.dataset.zoneId);
                    }
                }
                break;
            case 'assets':
                // Quick recall selected asset
                if (typeof recallAsset === 'function') {
                    recallAsset();
                }
                break;
            case 'analytics':
                // Refresh analytics
                if (typeof loadAnalytics === 'function') {
                    loadAnalytics();
                }
                break;
        }
    }

    /**
     * Navigate between views
     */
    navigateView(direction) {
        const currentView = TRITIUM?.state?.currentView || 'grid';
        let index = VIEW_ORDER.indexOf(currentView);

        if (index === -1) index = 0;

        index += direction;
        if (index < 0) index = VIEW_ORDER.length - 1;
        if (index >= VIEW_ORDER.length) index = 0;

        const newView = VIEW_ORDER[index];
        if (typeof switchView === 'function') {
            switchView(newView);
        }
    }

    /**
     * Toggle help overlay
     */
    toggleHelp() {
        // Check if help is already open
        const existing = document.getElementById('controls-overlay');
        if (existing) {
            existing.remove();
            this.focusManager.popFocusTrap();
            return;
        }

        this.showControlsOverlay();
    }

    /**
     * Toggle main menu
     */
    toggleMenu() {
        // For now, just show help - could expand to full menu later
        this.toggleHelp();
    }

    /**
     * Toggle sidebar visibility
     */
    toggleSidebar() {
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) {
            sidebar.classList.toggle('collapsed');
        }
    }

    /**
     * Reset view (3D camera, etc.)
     */
    resetView() {
        const view = TRITIUM?.state?.currentView;
        if (view === '3d') {
            // Reset 3D camera to default
            if (typeof controls !== 'undefined' && controls) {
                controls.reset();
            }
            if (typeof showNotification === 'function') {
                showNotification('VIEW', '3D view reset', 'info');
            }
        }
    }

    /**
     * Handle page up action
     */
    handlePageUp() {
        const view = TRITIUM?.state?.currentView;
        if (view === 'war') {
            if (typeof warState !== 'undefined') {
                warState.cam.targetZoom = Math.max(0.3, warState.cam.targetZoom * 0.85);
            }
        } else if (view === 'player') {
            if (typeof skip === 'function') skip(-60);
        } else if (view === '3d') {
            if (typeof controls !== 'undefined' && controls) {
                controls.dollyOut(1.2);
                controls.update();
            }
        } else {
            const viewContent = document.querySelector('.view-content:not(.hidden)');
            if (viewContent) {
                viewContent.scrollTop -= viewContent.clientHeight * 0.8;
            }
        }
    }

    /**
     * Handle page down action
     */
    handlePageDown() {
        const view = TRITIUM?.state?.currentView;
        if (view === 'war') {
            if (typeof warState !== 'undefined') {
                warState.cam.targetZoom = Math.min(5.0, warState.cam.targetZoom * 1.15);
            }
        } else if (view === 'player') {
            if (typeof skip === 'function') skip(60);
        } else if (view === '3d') {
            if (typeof controls !== 'undefined' && controls) {
                controls.dollyIn(1.2);
                controls.update();
            }
        } else {
            const viewContent = document.querySelector('.view-content:not(.hidden)');
            if (viewContent) {
                viewContent.scrollTop += viewContent.clientHeight * 0.8;
            }
        }
    }

    /**
     * Handle 3D camera movement from right stick
     */
    handle3DCameraMove(data) {
        if (!data || TRITIUM?.state?.currentView !== '3d') return;

        if (typeof controls !== 'undefined' && controls) {
            // Orbit the camera
            const rotateSpeed = 0.05;
            const azimuthAngle = -data.x * rotateSpeed;
            const polarAngle = data.y * rotateSpeed;

            controls.rotateLeft(azimuthAngle);
            controls.rotateUp(polarAngle);
        }
    }

    /**
     * War Room: pan camera from left stick
     */
    handleWarCameraMove(data) {
        if (!data || typeof warState === 'undefined') return;
        const panSpeed = 0.5 / warState.cam.zoom;
        warState.cam.targetX += data.x * panSpeed;
        warState.cam.targetY -= data.y * panSpeed;
    }

    /**
     * War Room: select the nearest target to camera center
     */
    warSelectNearest() {
        if (typeof warState === 'undefined' || typeof getTargets !== 'function') return;
        const targets = getTargets();
        const cam = warState.cam;
        let closest = null;
        let closestDist = Infinity;
        for (const [tid, t] of Object.entries(targets)) {
            const pos = typeof getTargetPosition === 'function' ? getTargetPosition(t) : { x: t.x, y: t.y };
            if (pos.x === undefined) continue;
            const dx = pos.x - cam.x;
            const dy = pos.y - cam.y;
            const dist = dx * dx + dy * dy;
            if (dist < closestDist) {
                closestDist = dist;
                closest = tid;
            }
        }
        if (closest) {
            warState.selectedTargets = [closest];
            if (typeof updateUnitInfo === 'function') updateUnitInfo();
        }
    }

    /**
     * War Room: cycle targets forward (D-pad down)
     */
    warCycleNext() {
        if (typeof cycleTargets === 'function') cycleTargets();
    }

    /**
     * War Room: cycle targets backward (D-pad up)
     */
    warCyclePrev() {
        if (typeof warState === 'undefined' || typeof getTargets !== 'function') return;
        const targets = getTargets();
        const keys = Object.keys(targets);
        if (keys.length === 0) return;
        warState.cycleIndex = (warState.cycleIndex - 1 + keys.length) % keys.length;
        const tid = keys[warState.cycleIndex];
        warState.selectedTargets = [tid];
        const t = targets[tid];
        if (t) {
            const pos = typeof getTargetPosition === 'function' ? getTargetPosition(t) : { x: t.x, y: t.y };
            warState.cam.targetX = pos.x;
            warState.cam.targetY = pos.y;
        }
        if (typeof updateUnitInfo === 'function') updateUnitInfo();
    }

    /**
     * War Room: cycle through modes (X button)
     */
    warCycleModes() {
        if (typeof warState === 'undefined' || typeof setWarMode !== 'function') return;
        const modes = ['observe', 'tactical', 'setup'];
        const idx = modes.indexOf(warState.mode);
        const next = modes[(idx + 1) % modes.length];
        setWarMode(next);
    }

    /**
     * Quick playback for a channel
     */
    quickPlayback(channel) {
        if (typeof TRITIUM !== 'undefined' && TRITIUM.selectChannel) {
            TRITIUM.selectChannel(parseInt(channel));
        }
    }

    /**
     * Toggle fullscreen
     */
    toggleFullscreen() {
        const player = document.getElementById('main-player');
        if (player) {
            if (document.fullscreenElement) {
                document.exitFullscreen();
            } else {
                player.requestFullscreen().catch(() => {});
            }
        }
    }

    /**
     * Show controls overlay
     */
    showControlsOverlay() {
        const currentView = TRITIUM?.state?.currentView || 'grid';
        const viewName = currentView.toUpperCase();

        const overlay = document.createElement('div');
        overlay.id = 'controls-overlay';
        overlay.className = 'modal-overlay';
        overlay.style.cssText = 'opacity: 1; visibility: visible;';

        const content = `
            <div class="modal neon-box" style="max-width: 700px; max-height: 90vh; overflow-y: auto;">
                <div class="modal-header">
                    <h3 class="text-cyan" style="margin: 0; letter-spacing: 2px;">CONTROLS - ${viewName} VIEW</h3>
                    <button class="modal-close" onclick="document.getElementById('controls-overlay').remove()">&times;</button>
                </div>
                <div class="modal-body" style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; font-size: 0.85rem;">
                    <!-- Keyboard Column -->
                    <div>
                        <div class="text-magenta" style="font-weight: bold; margin-bottom: 10px; letter-spacing: 1px;">KEYBOARD</div>
                        ${this.getKeyboardControlsHTML(currentView)}
                    </div>

                    <!-- Gamepad Column -->
                    <div>
                        <div class="text-green" style="font-weight: bold; margin-bottom: 10px; letter-spacing: 1px;">GAMEPAD</div>
                        ${this.getGamepadControlsHTML(currentView)}
                    </div>
                </div>
                <div class="modal-footer" style="border-top: 1px solid rgba(0,240,255,0.2); margin-top: 15px; padding-top: 15px;">
                    <span class="text-muted" style="font-size: 0.75rem;">Press SELECT/BACK or ? to toggle this overlay</span>
                </div>
            </div>
        `;

        overlay.innerHTML = content;
        document.body.appendChild(overlay);

        // Close on click outside
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                overlay.remove();
                this.focusManager.popFocusTrap();
            }
        });

        // Push focus trap
        this.focusManager.pushFocusTrap('#controls-overlay .modal');
    }

    /**
     * Get keyboard controls HTML for a view
     */
    getKeyboardControlsHTML(view) {
        const globalControls = `
            <div class="control-group">
                <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">GLOBAL</div>
                <div class="control-row"><kbd>G</kbd> Grid View</div>
                <div class="control-row"><kbd>P</kbd> Player View</div>
                <div class="control-row"><kbd>D</kbd> 3D View</div>
                <div class="control-row"><kbd>Z</kbd> Zones</div>
                <div class="control-row"><kbd>T</kbd> Targets</div>
                <div class="control-row"><kbd>A</kbd> Assets</div>
                <div class="control-row"><kbd>N</kbd> Analytics</div>
                <div class="control-row"><kbd>/</kbd> Focus Search</div>
                <div class="control-row"><kbd>ESC</kbd> Close/Cancel</div>
                <div class="control-row"><kbd>?</kbd> This Help</div>
            </div>
        `;

        const viewSpecific = {
            'grid': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">GRID VIEW</div>
                    <div class="control-row"><kbd>1</kbd> 1x1 Grid</div>
                    <div class="control-row"><kbd>2</kbd> 2x2 Grid</div>
                    <div class="control-row"><kbd>3</kbd> 3x3 Grid</div>
                    <div class="control-row"><kbd>Enter</kbd> Select Camera</div>
                </div>
            `,
            'player': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">PLAYER VIEW</div>
                    <div class="control-row"><kbd>Space</kbd> Play/Pause</div>
                    <div class="control-row"><kbd>Left/Right</kbd> Seek 10s</div>
                    <div class="control-row"><kbd>F</kbd> Fullscreen</div>
                </div>
            `,
            '3d': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">3D VIEW</div>
                    <div class="control-row"><kbd>Drag</kbd> Orbit Camera</div>
                    <div class="control-row"><kbd>Scroll</kbd> Zoom</div>
                    <div class="control-row"><kbd>Click</kbd> Select Object</div>
                    <div class="control-row"><kbd>Dbl-Click</kbd> View Camera</div>
                </div>
            `,
            'war': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">WAR ROOM</div>
                    <div class="control-row"><kbd>O</kbd> Observe Mode</div>
                    <div class="control-row"><kbd>T</kbd> Tactical Mode</div>
                    <div class="control-row"><kbd>S</kbd> Setup Mode</div>
                    <div class="control-row"><kbd>Click</kbd> Select Target</div>
                    <div class="control-row"><kbd>Shift+Click</kbd> Add to Selection</div>
                    <div class="control-row"><kbd>Right-Click</kbd> Dispatch Selected</div>
                    <div class="control-row"><kbd>Drag</kbd> Box Select Friendlies</div>
                    <div class="control-row"><kbd>Mid/Alt+Drag</kbd> Pan Camera</div>
                    <div class="control-row"><kbd>Scroll</kbd> Zoom (cursor-centered)</div>
                    <div class="control-row"><kbd>Dbl-Click</kbd> Center + Zoom Target</div>
                    <div class="control-row"><kbd>Tab</kbd> Cycle Targets</div>
                    <div class="control-row"><kbd>Space</kbd> Center on Selection</div>
                    <div class="control-row"><kbd>Delete</kbd> Remove (Setup)</div>
                    <div class="control-row"><kbd>Minimap Click</kbd> Pan to Location</div>
                </div>
            `,
        };

        return globalControls + (viewSpecific[view] || '');
    }

    /**
     * Get gamepad controls HTML for a view
     */
    getGamepadControlsHTML(view) {
        const globalControls = `
            <div class="control-group">
                <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">GLOBAL</div>
                <div class="control-row"><span class="gp-btn">D-Pad</span> Navigate</div>
                <div class="control-row"><span class="gp-btn">A</span> Confirm/Select</div>
                <div class="control-row"><span class="gp-btn">B</span> Back/Cancel</div>
                <div class="control-row"><span class="gp-btn">X</span> Context Menu</div>
                <div class="control-row"><span class="gp-btn">Y</span> Secondary Action</div>
                <div class="control-row"><span class="gp-btn">LB/RB</span> Switch View</div>
                <div class="control-row"><span class="gp-btn">Select</span> This Help</div>
            </div>
        `;

        const viewSpecific = {
            'grid': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">GRID VIEW</div>
                    <div class="control-row"><span class="gp-btn">A</span> Select Camera</div>
                    <div class="control-row"><span class="gp-btn">Y</span> Quick Playback</div>
                    <div class="control-row"><span class="gp-btn">L-Stick</span> Scroll Grid</div>
                </div>
            `,
            'player': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">PLAYER VIEW</div>
                    <div class="control-row"><span class="gp-btn">A</span> Play/Pause</div>
                    <div class="control-row"><span class="gp-btn">D-Pad L/R</span> Seek 10s</div>
                    <div class="control-row"><span class="gp-btn">LT/RT</span> Jump 1min</div>
                    <div class="control-row"><span class="gp-btn">Y</span> Fullscreen</div>
                </div>
            `,
            '3d': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">3D VIEW</div>
                    <div class="control-row"><span class="gp-btn">L-Stick</span> Pan Camera</div>
                    <div class="control-row"><span class="gp-btn">R-Stick</span> Orbit View</div>
                    <div class="control-row"><span class="gp-btn">LT/RT</span> Zoom Out/In</div>
                    <div class="control-row"><span class="gp-btn">R3</span> Reset View</div>
                </div>
            `,
            'targets': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">TARGETS VIEW</div>
                    <div class="control-row"><span class="gp-btn">D-Pad</span> Navigate Gallery</div>
                    <div class="control-row"><span class="gp-btn">A</span> View Details</div>
                    <div class="control-row"><span class="gp-btn">Y</span> Find Similar</div>
                    <div class="control-row"><span class="gp-btn">LT/RT</span> Page Results</div>
                </div>
            `,
            'assets': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">ASSETS VIEW</div>
                    <div class="control-row"><span class="gp-btn">D-Pad</span> Select Asset/Task</div>
                    <div class="control-row"><span class="gp-btn">A</span> Execute</div>
                    <div class="control-row"><span class="gp-btn">Y</span> Quick Recall</div>
                    <div class="control-row"><span class="gp-btn">X</span> Emergency Stop</div>
                </div>
            `,
            'zones': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">ZONES VIEW</div>
                    <div class="control-row"><span class="gp-btn">D-Pad</span> Navigate Zones</div>
                    <div class="control-row"><span class="gp-btn">A</span> Edit Zone</div>
                    <div class="control-row"><span class="gp-btn">Y</span> Toggle Enabled</div>
                    <div class="control-row"><span class="gp-btn">X</span> Delete Zone</div>
                </div>
            `,
            'analytics': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">ANALYTICS VIEW</div>
                    <div class="control-row"><span class="gp-btn">D-Pad</span> Navigate Stats</div>
                    <div class="control-row"><span class="gp-btn">A</span> Drill Down</div>
                    <div class="control-row"><span class="gp-btn">LB/RB</span> Change Period</div>
                </div>
            `,
            'war': `
                <div class="control-group" style="margin-top: 10px;">
                    <div class="text-muted" style="font-size: 0.7rem; margin-bottom: 4px;">WAR ROOM</div>
                    <div class="control-row"><span class="gp-btn">L-Stick</span> Pan Camera</div>
                    <div class="control-row"><span class="gp-btn">A</span> Select Nearest Target</div>
                    <div class="control-row"><span class="gp-btn">B</span> Deselect All</div>
                    <div class="control-row"><span class="gp-btn">Y</span> Center on Selection</div>
                    <div class="control-row"><span class="gp-btn">X</span> Cycle Modes</div>
                    <div class="control-row"><span class="gp-btn">LT/RT</span> Zoom Out/In</div>
                    <div class="control-row"><span class="gp-btn">D-Pad</span> Cycle Targets</div>
                </div>
            `,
        };

        return globalControls + (viewSpecific[view] || '');
    }

    /**
     * Enable/disable input handling
     */
    setEnabled(enabled) {
        this.enabled = enabled;
    }

    /**
     * Enable/disable gamepad
     */
    setGamepadEnabled(enabled) {
        this.gamepadEnabled = enabled;
        if (!enabled) {
            this.gamepadHandler.stop();
        } else {
            this.gamepadHandler.start();
        }
    }
}

// =============================================================================
// INITIALIZATION
// =============================================================================

// Create global instance
const tritiumInput = new TritiumInputManager();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Delay slightly to ensure TRITIUM app is initialized
    setTimeout(() => {
        tritiumInput.init();
    }, 100);
});

// Export for global access
window.tritiumInput = tritiumInput;
window.TritiumInputManager = TritiumInputManager;
