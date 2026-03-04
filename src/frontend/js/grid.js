// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM - 3D Camera Grid with Live Previews
 * Interactive Three.js visualization for camera spatial layout
 */

let threeInitialized = false;
let scene, camera, renderer, controls, dragControls;
let cameraCards = [];
let assetMarkers = [];  // 3D markers for assets
let detectionMarkers = [];  // 3D markers for recent detections
let animationId = null;
let selectedCard = null;
let cameraTextures = {};  // Cache for camera preview textures
let assetUpdateInterval = null;  // Interval for updating asset positions

// Cyberpunk color palette
const COLORS = {
    cyan: 0x00f0ff,
    magenta: 0xff2a6d,
    green: 0x05ffa1,
    yellow: 0xfcee0a,
    void: 0x0a0a0f,
    dark: 0x12121a,
    gray: 0x1a1a2e,
};

// Camera position storage
let cameraPositions = JSON.parse(localStorage.getItem('tritium_camera_positions') || '{}');

/**
 * Initialize Three.js scene
 */
function initThreeJS() {
    if (threeInitialized) {
        animate();
        return;
    }

    const canvas = document.getElementById('three-canvas');
    if (!canvas) return;

    console.log('%c[THREE] Initializing 3D property view...', 'color: #00f0ff;');

    // Scene - represents your property from above
    scene = new THREE.Scene();
    scene.background = new THREE.Color(COLORS.void);

    // Camera - top-down isometric view
    const aspect = canvas.clientWidth / canvas.clientHeight;
    camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 1000);
    camera.position.set(0, 15, 15);
    camera.lookAt(0, 0, 0);

    // Renderer
    renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: true,
    });
    renderer.setSize(canvas.clientWidth, canvas.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Orbit controls - let user rotate/pan/zoom the view
    if (typeof THREE.OrbitControls !== 'undefined') {
        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.maxPolarAngle = Math.PI / 2.2;  // Prevent going below ground
        controls.minDistance = 5;
        controls.maxDistance = 50;
    }

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(10, 20, 10);
    scene.add(directionalLight);

    // Create property layout
    createPropertyGrid();
    createCameraCards();
    createInfoPanel();

    // Handle resize
    window.addEventListener('resize', onWindowResize);

    // Setup drag controls for camera positioning
    setupDragControls(canvas);

    threeInitialized = true;
    animate();

    // Load camera previews
    loadCameraPreviews();

    // Start loading assets
    startAssetUpdates();
}

/**
 * Create property grid (represents your property from above)
 */
function createPropertyGrid() {
    // Ground plane
    const groundGeometry = new THREE.PlaneGeometry(30, 30);
    const groundMaterial = new THREE.MeshBasicMaterial({
        color: 0x0d0d15,
        side: THREE.DoubleSide,
    });
    const ground = new THREE.Mesh(groundGeometry, groundMaterial);
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.01;
    scene.add(ground);

    // Grid lines
    const gridHelper = new THREE.GridHelper(30, 30, COLORS.cyan, 0x1a1a2e);
    gridHelper.material.opacity = 0.3;
    gridHelper.material.transparent = true;
    scene.add(gridHelper);

    // Add house representation (simple box)
    const houseGeometry = new THREE.BoxGeometry(6, 3, 8);
    const houseMaterial = new THREE.MeshBasicMaterial({
        color: 0x1a1a2e,
        transparent: true,
        opacity: 0.7,
    });
    const house = new THREE.Mesh(houseGeometry, houseMaterial);
    house.position.set(0, 1.5, 0);
    scene.add(house);

    // House edges
    const houseEdges = new THREE.EdgesGeometry(houseGeometry);
    const houseLine = new THREE.LineSegments(houseEdges, new THREE.LineBasicMaterial({
        color: COLORS.cyan,
        opacity: 0.5,
        transparent: true,
    }));
    houseLine.position.copy(house.position);
    scene.add(houseLine);

    // Add driveway
    const driveGeometry = new THREE.PlaneGeometry(3, 8);
    const driveMaterial = new THREE.MeshBasicMaterial({
        color: 0x15151f,
        side: THREE.DoubleSide,
    });
    const driveway = new THREE.Mesh(driveGeometry, driveMaterial);
    driveway.rotation.x = -Math.PI / 2;
    driveway.position.set(-6, 0.01, 0);
    scene.add(driveway);

    // Labels
    addTextLabel('HOUSE', 0, 3.5, 0);
    addTextLabel('DRIVEWAY', -6, 0.1, 0);
}

/**
 * Add text label to scene
 */
function addTextLabel(text, x, y, z) {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = 'transparent';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = 'bold 24px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#00f0ff';
    ctx.globalAlpha = 0.5;
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);

    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(3, 0.75, 1);
    sprite.position.set(x, y, z);
    scene.add(sprite);
}

/**
 * Create camera cards with preview capability
 */
function createCameraCards() {
    const channels = TRITIUM?.state?.channels || [];
    if (channels.length === 0) {
        console.log('[THREE] No channels available yet');
        // Create placeholder card
        addTextLabel('No cameras loaded - click SCAN in sidebar', 0, 3, 5);
        return;
    }

    const cardWidth = 3;
    const cardHeight = 2;

    // Default positions in a circle around the property
    const defaultPositions = [
        { x: -10, z: -8 },   // CH01 - back left
        { x: 10, z: -8 },    // CH02 - back right
        { x: -10, z: 8 },    // CH03 - front left
        { x: 10, z: 8 },     // CH04 - front right
        { x: 0, z: -12 },    // CH05 - back center
        { x: 0, z: 12 },     // CH06 - front center
        { x: -12, z: 0 },    // CH07 - left side
        { x: 12, z: 0 },     // CH08 - right side
    ];

    channels.forEach((channel, index) => {
        // Use saved position or default
        const savedPos = cameraPositions[`ch${channel.channel}`];
        const defaultPos = defaultPositions[index] || { x: (index % 4 - 1.5) * 5, z: Math.floor(index / 4) * 5 - 5 };
        const pos = savedPos || defaultPos;

        // Card group
        const cardGroup = new THREE.Group();
        cardGroup.position.set(pos.x, 2, pos.z);
        cardGroup.userData = {
            channel: channel.channel,
            name: channel.name,
            index,
            isDraggable: true,
        };

        // Camera preview plane (will be textured with actual footage)
        const previewGeometry = new THREE.PlaneGeometry(cardWidth, cardHeight);
        const previewMaterial = new THREE.MeshBasicMaterial({
            color: 0x1a1a2e,
            side: THREE.DoubleSide,
        });
        const preview = new THREE.Mesh(previewGeometry, previewMaterial);
        preview.userData.isPreview = true;
        cardGroup.add(preview);

        // Card border (neon glow)
        const borderGeometry = new THREE.EdgesGeometry(previewGeometry);
        const borderMaterial = new THREE.LineBasicMaterial({
            color: COLORS.cyan,
            linewidth: 2,
        });
        const border = new THREE.LineSegments(borderGeometry, borderMaterial);
        cardGroup.add(border);

        // Status indicator (online/offline)
        const statusColor = channel.enabled ? COLORS.green : COLORS.magenta;
        const statusGeometry = new THREE.CircleGeometry(0.15, 16);
        const statusMaterial = new THREE.MeshBasicMaterial({ color: statusColor });
        const status = new THREE.Mesh(statusGeometry, statusMaterial);
        status.position.set(cardWidth / 2 - 0.25, cardHeight / 2 - 0.25, 0.01);
        cardGroup.add(status);

        // Channel label
        const labelCanvas = document.createElement('canvas');
        labelCanvas.width = 256;
        labelCanvas.height = 64;
        const ctx = labelCanvas.getContext('2d');
        ctx.fillStyle = '#0a0a0f';
        ctx.fillRect(0, 0, labelCanvas.width, labelCanvas.height);
        ctx.font = 'bold 28px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#00f0ff';
        ctx.fillText(`CH${String(channel.channel).padStart(2, '0')} - ${channel.name || 'Camera'}`, labelCanvas.width / 2, labelCanvas.height / 2);

        const labelTexture = new THREE.CanvasTexture(labelCanvas);
        const labelMaterial = new THREE.SpriteMaterial({ map: labelTexture });
        const label = new THREE.Sprite(labelMaterial);
        label.scale.set(3, 0.6, 1);
        label.position.set(0, -cardHeight / 2 - 0.5, 0);
        cardGroup.add(label);

        // View cone (shows camera field of view direction)
        const coneGeometry = new THREE.ConeGeometry(1.5, 4, 4);
        const coneMaterial = new THREE.MeshBasicMaterial({
            color: COLORS.cyan,
            transparent: true,
            opacity: 0.15,
            wireframe: true,
        });
        const cone = new THREE.Mesh(coneGeometry, coneMaterial);
        cone.rotation.x = Math.PI / 2;
        cone.position.set(0, 0, 2.5);
        cardGroup.add(cone);

        // Make card face camera
        cardGroup.lookAt(0, cardGroup.position.y, 0);
        cardGroup.rotation.x = 0;  // Keep upright

        scene.add(cardGroup);
        cameraCards.push(cardGroup);
    });
}

/**
 * Create info panel for selected camera
 */
function createInfoPanel() {
    // Info panel in corner of screen (HTML overlay)
    const panel = document.createElement('div');
    panel.id = 'camera-info-panel';
    panel.className = 'neon-box';
    panel.style.cssText = `
        position: absolute;
        bottom: 20px;
        left: 20px;
        padding: 15px;
        background: rgba(10, 10, 15, 0.9);
        border: 1px solid #00f0ff;
        color: #00f0ff;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        z-index: 100;
        display: none;
        max-width: 250px;
    `;
    panel.innerHTML = `
        <div style="color: #ff2a6d; font-weight: bold; margin-bottom: 10px;">CAMERA INFO</div>
        <div id="camera-info-content"></div>
        <div style="margin-top: 10px; font-size: 10px; color: #666;">
            Drag to reposition • Click to select
        </div>
    `;

    const container = document.getElementById('three-canvas').parentElement;
    container.style.position = 'relative';
    container.appendChild(panel);
}

/**
 * Setup drag controls for repositioning cameras
 */
function setupDragControls(canvas) {
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -2);  // Horizontal plane at y=2
    const intersection = new THREE.Vector3();
    let isDragging = false;
    let draggedCard = null;

    canvas.addEventListener('mousedown', (event) => {
        updateMouse(event);
        raycaster.setFromCamera(mouse, camera);

        const intersects = raycaster.intersectObjects(cameraCards, true);
        if (intersects.length > 0) {
            let card = intersects[0].object;
            while (card.parent && !card.userData.channel) {
                card = card.parent;
            }
            if (card.userData.channel) {
                isDragging = true;
                draggedCard = card;
                if (controls) controls.enabled = false;  // Disable orbit while dragging
                selectCamera(card);
            }
        }
    });

    canvas.addEventListener('mousemove', (event) => {
        updateMouse(event);

        if (isDragging && draggedCard) {
            raycaster.setFromCamera(mouse, camera);
            if (raycaster.ray.intersectPlane(plane, intersection)) {
                draggedCard.position.x = intersection.x;
                draggedCard.position.z = intersection.z;

                // Update view cone direction
                draggedCard.lookAt(0, draggedCard.position.y, 0);
                draggedCard.rotation.x = 0;
            }
        } else {
            // Hover effect
            raycaster.setFromCamera(mouse, camera);
            const intersects = raycaster.intersectObjects(cameraCards, true);

            cameraCards.forEach(card => {
                const border = card.children[1];
                if (border && border.material) {
                    border.material.color.setHex(COLORS.cyan);
                }
            });

            if (intersects.length > 0) {
                let card = intersects[0].object;
                while (card.parent && !card.userData.channel) {
                    card = card.parent;
                }
                if (card.userData.channel) {
                    const border = card.children[1];
                    if (border && border.material) {
                        border.material.color.setHex(COLORS.magenta);
                    }
                    canvas.style.cursor = 'grab';
                }
            } else {
                canvas.style.cursor = 'default';
            }
        }
    });

    canvas.addEventListener('mouseup', () => {
        if (isDragging && draggedCard) {
            // Save position
            cameraPositions[`ch${draggedCard.userData.channel}`] = {
                x: draggedCard.position.x,
                z: draggedCard.position.z,
            };
            localStorage.setItem('tritium_camera_positions', JSON.stringify(cameraPositions));
            TRITIUM.showNotification('SAVED', `Camera ${draggedCard.userData.channel} position saved`, 'info');
        }
        isDragging = false;
        draggedCard = null;
        if (controls) controls.enabled = true;
    });

    canvas.addEventListener('dblclick', (event) => {
        updateMouse(event);
        raycaster.setFromCamera(mouse, camera);

        // Check for detection markers first
        const detectionIntersects = raycaster.intersectObjects(detectionMarkers, true);
        if (detectionIntersects.length > 0) {
            let marker = detectionIntersects[0].object;
            while (marker.parent && !marker.userData.detection) {
                marker = marker.parent;
            }
            if (marker.userData.detection) {
                showDetectionContextMenu(marker.userData.detection, event);
                return;
            }
        }

        // Then check camera cards
        const intersects = raycaster.intersectObjects(cameraCards, true);
        if (intersects.length > 0) {
            let card = intersects[0].object;
            while (card.parent && !card.userData.channel) {
                card = card.parent;
            }
            if (card.userData.channel) {
                // Double-click opens camera in list view
                TRITIUM.selectChannel(card.userData.channel);
                TRITIUM.switchView('list');
            }
        }
    });

    // Right-click context menu for detections
    canvas.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        updateMouse(event);
        raycaster.setFromCamera(mouse, camera);

        const detectionIntersects = raycaster.intersectObjects(detectionMarkers, true);
        if (detectionIntersects.length > 0) {
            let marker = detectionIntersects[0].object;
            while (marker.parent && !marker.userData.detection) {
                marker = marker.parent;
            }
            if (marker.userData.detection) {
                showDetectionContextMenu(marker.userData.detection, event);
            }
        }
    });

    function updateMouse(event) {
        const rect = canvas.getBoundingClientRect();
        mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    }
}

/**
 * Select a camera and show info
 */
function selectCamera(card) {
    selectedCard = card;

    // Update info panel
    const panel = document.getElementById('camera-info-panel');
    const content = document.getElementById('camera-info-content');
    if (panel && content) {
        panel.style.display = 'block';
        content.innerHTML = `
            <div><strong>Channel:</strong> ${card.userData.channel}</div>
            <div><strong>Name:</strong> ${card.userData.name || 'Camera ' + card.userData.channel}</div>
            <div><strong>Position:</strong> (${card.position.x.toFixed(1)}, ${card.position.z.toFixed(1)})</div>
            <div style="margin-top: 10px;">
                <button onclick="resetCameraPosition(${card.userData.channel})"
                        style="background: #1a1a2e; color: #00f0ff; border: 1px solid #00f0ff; padding: 5px 10px; cursor: pointer;">
                    Reset Position
                </button>
            </div>
        `;
    }

    // Highlight selected card
    cameraCards.forEach(c => {
        const border = c.children[1];
        if (border && border.material) {
            border.material.color.setHex(c === card ? COLORS.yellow : COLORS.cyan);
        }
    });
}

/**
 * Reset camera position to default
 */
window.resetCameraPosition = function(channel) {
    delete cameraPositions[`ch${channel}`];
    localStorage.setItem('tritium_camera_positions', JSON.stringify(cameraPositions));

    // Recreate cards
    cameraCards.forEach(card => scene.remove(card));
    cameraCards = [];
    createCameraCards();
    loadCameraPreviews();

    TRITIUM.showNotification('RESET', `Camera ${channel} position reset`, 'info');
};

/**
 * Load camera preview images
 */
async function loadCameraPreviews() {
    const loader = new THREE.TextureLoader();

    for (const card of cameraCards) {
        const channel = card.userData.channel;

        try {
            // Try to get a recent frame from the API
            // Correct endpoint: /api/videos/channels/{channel}/dates
            const response = await fetch(`/api/videos/channels/${channel}/dates`);
            if (response.ok) {
                const dates = await response.json();
                if (dates.length > 0) {
                    const latestDate = dates[0].date;
                    // Correct endpoint: /api/videos/channels/{channel}/dates/{date}
                    const videosResponse = await fetch(`/api/videos/channels/${channel}/dates/${latestDate}`);
                    if (videosResponse.ok) {
                        const videos = await videosResponse.json();
                        if (videos.length > 0) {
                            // Correct thumbnail endpoint
                            const thumbUrl = `/api/videos/thumbnail/${channel}/${latestDate}/${videos[0].filename}`;

                            loader.load(thumbUrl, (texture) => {
                                const preview = card.children.find(c => c.userData && c.userData.isPreview);
                                if (preview) {
                                    preview.material = new THREE.MeshBasicMaterial({
                                        map: texture,
                                        side: THREE.DoubleSide,
                                    });
                                }
                            }, undefined, (err) => {
                                console.log(`[THREE] No thumbnail for CH${channel}:`, err);
                                // Apply placeholder texture
                                applyPlaceholderTexture(card, channel);
                            });
                        } else {
                            applyPlaceholderTexture(card, channel);
                        }
                    } else {
                        applyPlaceholderTexture(card, channel);
                    }
                } else {
                    applyPlaceholderTexture(card, channel);
                }
            } else {
                applyPlaceholderTexture(card, channel);
            }
        } catch (e) {
            console.log(`[THREE] Could not load preview for CH${channel}:`, e.message);
            applyPlaceholderTexture(card, channel);
        }
    }
}

/**
 * Apply placeholder texture to camera card
 */
function applyPlaceholderTexture(card, channel) {
    const canvas = document.createElement('canvas');
    canvas.width = 320;
    canvas.height = 180;
    const ctx = canvas.getContext('2d');

    // Dark background
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Grid pattern
    ctx.strokeStyle = '#00f0ff22';
    ctx.lineWidth = 1;
    for (let i = 0; i < canvas.width; i += 20) {
        ctx.beginPath();
        ctx.moveTo(i, 0);
        ctx.lineTo(i, canvas.height);
        ctx.stroke();
    }
    for (let i = 0; i < canvas.height; i += 20) {
        ctx.beginPath();
        ctx.moveTo(0, i);
        ctx.lineTo(canvas.width, i);
        ctx.stroke();
    }

    // Camera icon
    ctx.font = '48px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#00f0ff';
    ctx.fillText('📹', canvas.width / 2, canvas.height / 2 - 10);

    // Channel label
    ctx.font = 'bold 14px "JetBrains Mono", monospace';
    ctx.fillText(`CH${String(channel).padStart(2, '0')}`, canvas.width / 2, canvas.height / 2 + 35);

    // No video text
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = '#666';
    ctx.fillText('No video preview', canvas.width / 2, canvas.height - 15);

    const texture = new THREE.CanvasTexture(canvas);
    const preview = card.children.find(c => c.userData && c.userData.isPreview);
    if (preview) {
        preview.material = new THREE.MeshBasicMaterial({
            map: texture,
            side: THREE.DoubleSide,
        });
    }
}

/**
 * Animation loop
 */
function animate() {
    if (TRITIUM.state.currentView !== '3d') {
        cancelAnimationFrame(animationId);
        return;
    }

    animationId = requestAnimationFrame(animate);

    // Update orbit controls
    if (controls) {
        controls.update();
    }

    // Subtle animation for cards
    const time = Date.now() * 0.001;
    cameraCards.forEach((card, index) => {
        // Gentle bob
        card.position.y = 2 + Math.sin(time * 0.5 + index) * 0.05;
    });

    // Animate detection markers
    animateDetections(time);

    renderer.render(scene, camera);
}

/**
 * Handle window resize
 */
function onWindowResize() {
    const canvas = document.getElementById('three-canvas');
    if (!canvas) return;

    camera.aspect = canvas.clientWidth / canvas.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(canvas.clientWidth, canvas.clientHeight);
}

/**
 * Clean up Three.js resources
 */
function disposeThreeJS() {
    if (!threeInitialized) return;

    cancelAnimationFrame(animationId);

    scene.traverse((object) => {
        if (object.geometry) object.geometry.dispose();
        if (object.material) {
            if (Array.isArray(object.material)) {
                object.material.forEach(m => m.dispose());
            } else {
                object.material.dispose();
            }
        }
    });

    if (controls) controls.dispose();
    renderer.dispose();

    // Remove info panel
    const panel = document.getElementById('camera-info-panel');
    if (panel) panel.remove();

    threeInitialized = false;
}

/**
 * Reload 3D view when channels are updated
 */
function reloadThreeJS() {
    if (!threeInitialized) return;

    // Remove existing camera cards
    cameraCards.forEach(card => scene.remove(card));
    cameraCards = [];

    // Recreate
    createCameraCards();
    loadCameraPreviews();
}

/**
 * Load and display assets in 3D view
 */
async function loadAssetsIn3D() {
    try {
        const response = await fetch('/api/assets');
        if (!response.ok) return;

        const assets = await response.json();
        updateAssetMarkers(assets);
    } catch (e) {
        console.log('[THREE] Could not load assets:', e.message);
    }
}

/**
 * Update asset markers in 3D scene
 */
function updateAssetMarkers(assets) {
    // Remove old markers
    assetMarkers.forEach(marker => scene.remove(marker));
    assetMarkers = [];

    assets.forEach(asset => {
        if (asset.position_x === null || asset.position_y === null) return;

        // Create asset marker group
        const markerGroup = new THREE.Group();
        markerGroup.position.set(asset.position_x, 0.5, asset.position_y);
        markerGroup.userData = { asset_id: asset.asset_id, asset: asset };

        // Asset body based on type
        const bodyColor = asset.status === 'active' || asset.status === 'tasked'
            ? COLORS.green
            : asset.status === 'offline' ? 0x666666 : COLORS.cyan;

        let bodyGeometry;
        if (asset.asset_type === 'aerial') {
            // Drone - pyramid shape
            bodyGeometry = new THREE.ConeGeometry(0.4, 0.6, 4);
        } else if (asset.asset_type === 'fixed') {
            // Fixed sensor - cylinder
            bodyGeometry = new THREE.CylinderGeometry(0.3, 0.3, 0.5, 8);
        } else {
            // Ground vehicle - box
            bodyGeometry = new THREE.BoxGeometry(0.8, 0.4, 1.2);
        }

        const bodyMaterial = new THREE.MeshBasicMaterial({ color: bodyColor });
        const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
        if (asset.asset_type !== 'aerial') {
            body.position.y = 0.2;
        }
        markerGroup.add(body);

        // Heading indicator
        if (asset.heading !== null) {
            const headingGeometry = new THREE.ConeGeometry(0.15, 0.5, 4);
            const headingMaterial = new THREE.MeshBasicMaterial({ color: COLORS.magenta });
            const headingArrow = new THREE.Mesh(headingGeometry, headingMaterial);
            headingArrow.rotation.x = Math.PI / 2;
            headingArrow.position.set(0, 0.3, 0.8);
            markerGroup.add(headingArrow);

            // Rotate whole group to heading
            markerGroup.rotation.y = -((asset.heading - 90) * Math.PI / 180);
        }

        // Label
        const labelCanvas = document.createElement('canvas');
        labelCanvas.width = 128;
        labelCanvas.height = 32;
        const ctx = labelCanvas.getContext('2d');
        ctx.fillStyle = 'rgba(10, 10, 15, 0.8)';
        ctx.fillRect(0, 0, labelCanvas.width, labelCanvas.height);
        ctx.font = 'bold 16px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = asset.status === 'tasked' ? '#fcee0a' : '#00f0ff';
        ctx.fillText(asset.asset_id, labelCanvas.width / 2, labelCanvas.height / 2);

        const labelTexture = new THREE.CanvasTexture(labelCanvas);
        const labelMaterial = new THREE.SpriteMaterial({ map: labelTexture });
        const label = new THREE.Sprite(labelMaterial);
        label.scale.set(2, 0.5, 1);
        label.position.set(0, 1.2, 0);
        markerGroup.add(label);

        // Battery indicator (small bar)
        if (asset.battery_level !== null) {
            const batteryWidth = 0.6 * (asset.battery_level / 100);
            const batteryGeometry = new THREE.BoxGeometry(batteryWidth, 0.08, 0.15);
            const batteryColor = asset.battery_level > 50 ? COLORS.green
                : asset.battery_level > 20 ? COLORS.yellow : COLORS.magenta;
            const batteryMaterial = new THREE.MeshBasicMaterial({ color: batteryColor });
            const battery = new THREE.Mesh(batteryGeometry, batteryMaterial);
            battery.position.set(0, 0.7, 0);
            markerGroup.add(battery);
        }

        // Trail/path if tasked
        if (asset.current_task && asset.current_task.task_type === 'patrol') {
            // Add patrol path visualization
            const pathMaterial = new THREE.LineBasicMaterial({
                color: COLORS.cyan,
                opacity: 0.3,
                transparent: true,
            });
            // Simple circle for patrol visualization
            const pathGeometry = new THREE.CircleGeometry(3, 32);
            const pathEdges = new THREE.EdgesGeometry(pathGeometry);
            const pathLine = new THREE.LineSegments(pathEdges, pathMaterial);
            pathLine.rotation.x = -Math.PI / 2;
            pathLine.position.y = 0.05;
            markerGroup.add(pathLine);
        }

        scene.add(markerGroup);
        assetMarkers.push(markerGroup);
    });
}

/**
 * Start asset position updates
 */
function startAssetUpdates() {
    if (assetUpdateInterval) {
        clearInterval(assetUpdateInterval);
    }

    // Initial load
    loadAssetsIn3D();
    loadDetectionsIn3D();

    // Update every 2 seconds
    assetUpdateInterval = setInterval(() => {
        if (TRITIUM.state.currentView === '3d') {
            loadAssetsIn3D();
        }
    }, 2000);

    // Update detections less frequently (every 30 seconds)
    setInterval(() => {
        if (TRITIUM.state.currentView === '3d') {
            loadDetectionsIn3D();
        }
    }, 30000);
}

/**
 * Stop asset updates
 */
function stopAssetUpdates() {
    if (assetUpdateInterval) {
        clearInterval(assetUpdateInterval);
        assetUpdateInterval = null;
    }
}

/**
 * Show context menu for detection
 */
function showDetectionContextMenu(detection, event) {
    // Remove existing menu
    const existing = document.getElementById('detection-context-menu');
    if (existing) existing.remove();

    const isPerson = detection.target_type === 'person';
    const thumbnailUrl = `/api/search/thumbnail/${detection.thumbnail_id}`;

    const menu = document.createElement('div');
    menu.id = 'detection-context-menu';
    menu.style.cssText = `
        position: fixed;
        left: ${event.clientX}px;
        top: ${event.clientY}px;
        background: rgba(10, 10, 15, 0.95);
        border: 1px solid ${isPerson ? '#ff2a6d' : '#fcee0a'};
        padding: 8px;
        z-index: 1000;
        min-width: 200px;
        border-radius: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.8rem;
    `;

    menu.innerHTML = `
        <div style="display: flex; gap: 8px; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid rgba(0,240,255,0.2);">
            <img src="${thumbnailUrl}" style="width: 50px; height: 50px; object-fit: contain; border: 1px solid rgba(0,240,255,0.3);"
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 50 50%22><rect fill=%22%231a1a2e%22 width=%2250%22 height=%2250%22/><text x=%2225%22 y=%2230%22 text-anchor=%22middle%22 fill=%22%2300f0ff%22 font-size=%2220%22>?</text></svg>'">
            <div>
                <div style="color: ${isPerson ? '#ff2a6d' : '#fcee0a'};">${isPerson ? 'PERSON' : 'VEHICLE'}</div>
                ${detection.label ? `<div style="color: #00f0ff;">${detection.label}</div>` : ''}
                <div style="color: #666; font-size: 0.7rem;">CH${detection.channel || '?'}</div>
            </div>
        </div>
        <div class="context-menu-item" onclick="viewDetectionDetails('${detection.thumbnail_id}')">
            <span>🔍</span> View Details
        </div>
        <div class="context-menu-item" onclick="dispatchAssetFromContext('${detection.thumbnail_id}', 'track')">
            <span>🎯</span> Dispatch: TRACK
        </div>
        <div class="context-menu-item" onclick="dispatchAssetFromContext('${detection.thumbnail_id}', 'engage')">
            <span>⚡</span> Dispatch: ENGAGE
        </div>
        <div class="context-menu-item" style="border-top: 1px solid rgba(0,240,255,0.2); margin-top: 4px; padding-top: 4px;" onclick="closeDetectionContextMenu()">
            <span>✖</span> Close
        </div>
    `;

    document.body.appendChild(menu);

    // Close on click outside
    const closeHandler = (e) => {
        if (!menu.contains(e.target)) {
            menu.remove();
            document.removeEventListener('click', closeHandler);
        }
    };
    setTimeout(() => document.addEventListener('click', closeHandler), 100);
}

/**
 * Close detection context menu
 */
function closeDetectionContextMenu() {
    const menu = document.getElementById('detection-context-menu');
    if (menu) menu.remove();
}

/**
 * View detection details
 */
function viewDetectionDetails(thumbnailId) {
    closeDetectionContextMenu();
    TRITIUM.switchView('targets');
    setTimeout(() => {
        if (typeof selectTarget !== 'undefined') {
            selectTarget(thumbnailId);
        }
    }, 300);
}

/**
 * Dispatch asset from context menu
 */
function dispatchAssetFromContext(thumbnailId, taskType) {
    closeDetectionContextMenu();
    if (typeof dispatchAssetToTarget !== 'undefined') {
        // Set up minimal target state for dispatch
        if (typeof targetState !== 'undefined') {
            targetState.selectedTarget = {
                thumbnail_id: thumbnailId,
                target_type: 'person',  // Default, will be overridden if needed
            };
        }
        dispatchAssetToTarget(thumbnailId, taskType);
    } else {
        TRITIUM.showNotification('ERROR', 'Asset dispatch not available', 'error');
    }
}

// Add context menu styles
const contextMenuStyle = document.createElement('style');
contextMenuStyle.textContent = `
.context-menu-item {
    padding: 6px 8px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    color: #ccc;
    transition: background 0.2s;
}

.context-menu-item:hover {
    background: rgba(0, 240, 255, 0.1);
    color: #00f0ff;
}
`;
document.head.appendChild(contextMenuStyle);

/**
 * Load recent detections and show in 3D
 */
async function loadDetectionsIn3D() {
    try {
        const response = await fetch('/api/search/trends?days=1');
        if (!response.ok) return;

        const data = await response.json();
        if (data.recent_targets && data.recent_targets.length > 0) {
            updateDetectionMarkers(data.recent_targets);
        }
    } catch (e) {
        console.log('[THREE] Could not load detections:', e.message);
    }
}

/**
 * Update detection markers in 3D scene
 */
function updateDetectionMarkers(detections) {
    // Remove old markers
    if (detectionMarkers && detectionMarkers.length > 0) {
        detectionMarkers.forEach(marker => {
            if (marker && scene) scene.remove(marker);
        });
    }
    detectionMarkers = [];

    // Safety check
    if (!detections || !Array.isArray(detections) || !scene || !cameraCards) return;

    // Only show recent detections (last 10)
    const recent = detections.slice(0, 10);

    recent.forEach((detection, index) => {
        // Position based on channel
        const channel = detection.channel || 1;
        const card = cameraCards.find(c => c.userData.channel === channel);

        if (!card) return;

        // Position near the camera card
        const offsetX = (Math.random() - 0.5) * 4;
        const offsetZ = 3 + Math.random() * 2;  // In front of camera

        // Rotate to camera direction
        const angle = Math.atan2(card.position.z, card.position.x);
        const posX = card.position.x + Math.cos(angle + Math.PI) * offsetZ + offsetX;
        const posZ = card.position.z + Math.sin(angle + Math.PI) * offsetZ;

        // Create marker group
        const markerGroup = new THREE.Group();
        markerGroup.position.set(posX, 0.3, posZ);
        markerGroup.userData = { detection };

        // Detection type determines shape and color
        const isPerson = detection.target_type === 'person';
        const color = isPerson ? COLORS.magenta : COLORS.yellow;

        // Body
        let bodyGeometry;
        if (isPerson) {
            // Person - simple cone/capsule
            bodyGeometry = new THREE.CylinderGeometry(0.15, 0.25, 0.6, 8);
        } else {
            // Vehicle - box
            bodyGeometry = new THREE.BoxGeometry(0.5, 0.3, 0.8);
        }

        const bodyMaterial = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.6 + (index * 0.03),  // Older = more faded
        });
        const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
        body.position.y = isPerson ? 0.3 : 0.15;
        markerGroup.add(body);

        // Pulsing ring
        const ringGeometry = new THREE.RingGeometry(0.4, 0.5, 16);
        const ringMaterial = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.4,
            side: THREE.DoubleSide,
        });
        const ring = new THREE.Mesh(ringGeometry, ringMaterial);
        ring.rotation.x = -Math.PI / 2;
        ring.userData.isRing = true;
        markerGroup.add(ring);

        // Label
        if (detection.label) {
            const labelCanvas = document.createElement('canvas');
            labelCanvas.width = 128;
            labelCanvas.height = 32;
            const ctx = labelCanvas.getContext('2d');
            ctx.fillStyle = 'rgba(10, 10, 15, 0.8)';
            ctx.fillRect(0, 0, labelCanvas.width, labelCanvas.height);
            ctx.font = 'bold 14px "JetBrains Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = isPerson ? '#ff2a6d' : '#fcee0a';
            ctx.fillText(detection.label, labelCanvas.width / 2, labelCanvas.height / 2);

            const labelTexture = new THREE.CanvasTexture(labelCanvas);
            const labelMaterial = new THREE.SpriteMaterial({ map: labelTexture });
            const label = new THREE.Sprite(labelMaterial);
            label.scale.set(2, 0.5, 1);
            label.position.set(0, 0.8, 0);
            markerGroup.add(label);
        }

        scene.add(markerGroup);
        detectionMarkers.push(markerGroup);
    });
}

/**
 * Animate detection rings (called from main animate loop)
 */
function animateDetections(time) {
    if (!detectionMarkers || detectionMarkers.length === 0) return;

    detectionMarkers.forEach((marker, i) => {
        if (!marker || !marker.children) return;

        // Pulse the ring
        const ring = marker.children.find(c => c && c.userData && c.userData.isRing);
        if (ring && ring.material) {
            const scale = 1 + Math.sin(time * 2 + i) * 0.2;
            ring.scale.set(scale, scale, 1);
            ring.material.opacity = 0.4 - Math.sin(time * 2 + i) * 0.2;
        }

        // Gentle bob
        if (marker.position) {
            marker.position.y = 0.3 + Math.sin(time * 1.5 + i * 0.5) * 0.05;
        }
    });
}

// Export for global access
window.initThreeJS = initThreeJS;
window.disposeThreeJS = disposeThreeJS;
window.reloadThreeJS = reloadThreeJS;
window.loadAssetsIn3D = loadAssetsIn3D;
window.loadDetectionsIn3D = loadDetectionsIn3D;
window.closeDetectionContextMenu = closeDetectionContextMenu;
window.viewDetectionDetails = viewDetectionDetails;
window.dispatchAssetFromContext = dispatchAssetFromContext;
