// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Zone Editor
 * Draw and manage monitoring zones on camera views
 */

class ZoneEditor {
    constructor(containerId, cameraId) {
        this.container = document.getElementById(containerId);
        this.cameraId = cameraId;
        this.canvas = null;
        this.ctx = null;
        this.zones = [];
        this.currentPolygon = [];
        this.isDrawing = false;
        this.selectedZone = null;
        this.backgroundImage = null;

        this.init();
    }

    init() {
        // Create canvas overlay
        this.canvas = document.createElement('canvas');
        this.canvas.id = 'zone-canvas';
        this.canvas.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            cursor: crosshair;
            z-index: 10;
        `;
        this.container.style.position = 'relative';
        this.container.appendChild(this.canvas);

        this.ctx = this.canvas.getContext('2d');

        // Event listeners
        this.canvas.addEventListener('click', (e) => this.handleClick(e));
        this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
        this.canvas.addEventListener('contextmenu', (e) => this.handleRightClick(e));
        window.addEventListener('resize', () => this.resize());
        document.addEventListener('keydown', (e) => this.handleKeyDown(e));

        this.resize();
        this.loadZones();
    }

    resize() {
        const rect = this.container.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        this.render();
    }

    async loadZones() {
        try {
            const response = await fetch(`/api/zones?camera_id=${this.cameraId}`);
            if (response.ok) {
                this.zones = await response.json();
                this.render();
            }
        } catch (e) {
            console.error('Failed to load zones:', e);
        }
    }

    handleClick(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = Math.round((e.clientX - rect.left) / rect.width * this.canvas.width);
        const y = Math.round((e.clientY - rect.top) / rect.height * this.canvas.height);

        if (this.isDrawing) {
            this.currentPolygon.push([x, y]);
            this.render();
        } else {
            // Check if clicked on existing zone
            this.selectedZone = this.findZoneAt(x, y);
            this.render();

            if (this.selectedZone) {
                this.showZoneInfo(this.selectedZone);
            }
        }
    }

    handleMouseMove(e) {
        if (!this.isDrawing || this.currentPolygon.length === 0) return;

        const rect = this.canvas.getBoundingClientRect();
        const x = Math.round((e.clientX - rect.left) / rect.width * this.canvas.width);
        const y = Math.round((e.clientY - rect.top) / rect.height * this.canvas.height);

        this.render();

        // Draw preview line to cursor
        this.ctx.strokeStyle = '#00f0ff';
        this.ctx.lineWidth = 2;
        this.ctx.setLineDash([5, 5]);
        this.ctx.beginPath();
        const lastPoint = this.currentPolygon[this.currentPolygon.length - 1];
        this.ctx.moveTo(lastPoint[0], lastPoint[1]);
        this.ctx.lineTo(x, y);
        this.ctx.stroke();
        this.ctx.setLineDash([]);
    }

    handleRightClick(e) {
        e.preventDefault();

        if (this.isDrawing && this.currentPolygon.length >= 3) {
            // Complete the polygon
            this.completePolygon();
        }
    }

    handleKeyDown(e) {
        if (e.key === 'Escape') {
            this.cancelDrawing();
        } else if (e.key === 'Enter' && this.isDrawing && this.currentPolygon.length >= 3) {
            this.completePolygon();
        } else if (e.key === 'Delete' && this.selectedZone) {
            this.deleteZone(this.selectedZone.zone_id);
        }
    }

    startDrawing() {
        this.isDrawing = true;
        this.currentPolygon = [];
        this.canvas.style.cursor = 'crosshair';
        this.showMessage('Click to add points. Right-click or Enter to complete. Escape to cancel.');
    }

    cancelDrawing() {
        this.isDrawing = false;
        this.currentPolygon = [];
        this.canvas.style.cursor = 'default';
        this.render();
        this.hideMessage();
    }

    async completePolygon() {
        if (this.currentPolygon.length < 3) {
            this.showMessage('Need at least 3 points for a zone', 'error');
            return;
        }

        // Prompt for zone name
        const name = prompt('Zone name (e.g., "Dumpster", "Front Door"):');
        if (!name) {
            this.cancelDrawing();
            return;
        }

        // Prompt for zone type
        const types = ['activity', 'entry_exit', 'object_monitor', 'tripwire'];
        const typeIndex = prompt(
            'Zone type:\n' +
            '1. Activity (track all activity)\n' +
            '2. Entry/Exit (track enters and exits)\n' +
            '3. Object Monitor (track state changes)\n' +
            '4. Tripwire (line crossing)\n' +
            'Enter number (1-4):'
        );

        const zoneType = types[parseInt(typeIndex) - 1] || 'activity';

        let monitoredObject = null;
        if (zoneType === 'object_monitor') {
            monitoredObject = prompt('What object are you monitoring? (e.g., "dumpster", "garage door"):');
        }

        try {
            const response = await fetch('/api/zones/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    camera_id: this.cameraId,
                    name: name,
                    polygon: this.currentPolygon,
                    zone_type: zoneType,
                    monitored_object: monitoredObject,
                }),
            });

            if (response.ok) {
                const zone = await response.json();
                this.zones.push(zone);
                this.showMessage(`Zone "${name}" created!`, 'success');
            } else {
                const error = await response.json();
                this.showMessage(`Error: ${error.detail}`, 'error');
            }
        } catch (e) {
            this.showMessage(`Error: ${e.message}`, 'error');
        }

        this.cancelDrawing();
    }

    async deleteZone(zoneId) {
        if (!confirm('Delete this zone?')) return;

        try {
            const response = await fetch(`/api/zones/${zoneId}`, { method: 'DELETE' });
            if (response.ok) {
                this.zones = this.zones.filter(z => z.zone_id !== zoneId);
                this.selectedZone = null;
                this.render();
                this.showMessage('Zone deleted', 'success');
            }
        } catch (e) {
            this.showMessage(`Error: ${e.message}`, 'error');
        }
    }

    findZoneAt(x, y) {
        for (const zone of this.zones) {
            if (this.pointInPolygon(x, y, zone.polygon)) {
                return zone;
            }
        }
        return null;
    }

    pointInPolygon(x, y, polygon) {
        let inside = false;
        const n = polygon.length;

        for (let i = 0, j = n - 1; i < n; j = i++) {
            const xi = polygon[i][0], yi = polygon[i][1];
            const xj = polygon[j][0], yj = polygon[j][1];

            if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
                inside = !inside;
            }
        }

        return inside;
    }

    render() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw existing zones
        for (const zone of this.zones) {
            this.drawZone(zone, zone === this.selectedZone);
        }

        // Draw current polygon being created
        if (this.currentPolygon.length > 0) {
            this.drawPolygon(this.currentPolygon, '#00f0ff', true);
        }
    }

    drawZone(zone, selected = false) {
        const color = this.getZoneColor(zone.zone_type);
        const alpha = selected ? 0.4 : 0.2;

        // Fill
        this.ctx.fillStyle = this.hexToRgba(color, alpha);
        this.ctx.beginPath();
        this.ctx.moveTo(zone.polygon[0][0], zone.polygon[0][1]);
        for (let i = 1; i < zone.polygon.length; i++) {
            this.ctx.lineTo(zone.polygon[i][0], zone.polygon[i][1]);
        }
        this.ctx.closePath();
        this.ctx.fill();

        // Stroke
        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = selected ? 3 : 2;
        this.ctx.stroke();

        // Label
        const centroid = this.getPolygonCentroid(zone.polygon);
        this.ctx.fillStyle = color;
        this.ctx.font = 'bold 14px "JetBrains Mono", monospace';
        this.ctx.textAlign = 'center';
        this.ctx.fillText(zone.name, centroid[0], centroid[1]);

        // Event count badge
        if (zone.total_events > 0) {
            const badgeX = centroid[0];
            const badgeY = centroid[1] + 18;
            this.ctx.fillStyle = '#ff2a6d';
            this.ctx.beginPath();
            this.ctx.arc(badgeX, badgeY, 12, 0, Math.PI * 2);
            this.ctx.fill();
            this.ctx.fillStyle = '#fff';
            this.ctx.font = 'bold 10px sans-serif';
            this.ctx.fillText(zone.total_events.toString(), badgeX, badgeY + 3);
        }
    }

    drawPolygon(points, color, showPoints = false) {
        if (points.length === 0) return;

        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.moveTo(points[0][0], points[0][1]);

        for (let i = 1; i < points.length; i++) {
            this.ctx.lineTo(points[i][0], points[i][1]);
        }
        this.ctx.stroke();

        if (showPoints) {
            this.ctx.fillStyle = color;
            for (const point of points) {
                this.ctx.beginPath();
                this.ctx.arc(point[0], point[1], 5, 0, Math.PI * 2);
                this.ctx.fill();
            }
        }
    }

    getZoneColor(zoneType) {
        const colors = {
            activity: '#00f0ff',      // Cyan
            entry_exit: '#05ffa1',    // Green
            object_monitor: '#fcee0a', // Yellow
            tripwire: '#ff2a6d',      // Magenta
        };
        return colors[zoneType] || '#00f0ff';
    }

    getPolygonCentroid(polygon) {
        let x = 0, y = 0;
        for (const point of polygon) {
            x += point[0];
            y += point[1];
        }
        return [x / polygon.length, y / polygon.length];
    }

    hexToRgba(hex, alpha) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    showZoneInfo(zone) {
        // Create info popup
        let popup = document.getElementById('zone-info-popup');
        if (!popup) {
            popup = document.createElement('div');
            popup.id = 'zone-info-popup';
            popup.style.cssText = `
                position: absolute;
                top: 10px;
                right: 10px;
                background: rgba(10, 10, 15, 0.95);
                border: 1px solid #00f0ff;
                padding: 15px;
                color: #00f0ff;
                font-family: 'JetBrains Mono', monospace;
                font-size: 12px;
                z-index: 20;
                max-width: 300px;
            `;
            this.container.appendChild(popup);
        }

        popup.innerHTML = `
            <div style="color: #ff2a6d; font-weight: bold; margin-bottom: 10px;">
                ${zone.name.toUpperCase()}
            </div>
            <div><strong>Type:</strong> ${zone.zone_type}</div>
            <div><strong>Events:</strong> ${zone.total_events}</div>
            ${zone.monitored_object ? `<div><strong>Monitors:</strong> ${zone.monitored_object}</div>` : ''}
            ${zone.last_event_at ? `<div><strong>Last activity:</strong> ${new Date(zone.last_event_at).toLocaleString()}</div>` : ''}
            <div style="margin-top: 10px;">
                <button onclick="zoneEditor.viewZoneEvents('${zone.zone_id}')"
                        style="background: #1a1a2e; color: #00f0ff; border: 1px solid #00f0ff; padding: 5px 10px; cursor: pointer; margin-right: 5px;">
                    View Events
                </button>
                <button onclick="zoneEditor.deleteZone('${zone.zone_id}')"
                        style="background: #1a1a2e; color: #ff2a6d; border: 1px solid #ff2a6d; padding: 5px 10px; cursor: pointer;">
                    Delete
                </button>
            </div>
        `;
        popup.style.display = 'block';
    }

    async viewZoneEvents(zoneId) {
        try {
            const response = await fetch(`/api/zones/${zoneId}/summary`);
            if (response.ok) {
                const summary = await response.json();
                console.log('Zone summary:', summary);

                // Show events in a modal (simplified)
                alert(
                    `Zone: ${summary.zone_name}\n` +
                    `Total events: ${summary.total_events}\n` +
                    `Peak hour: ${summary.peak_hour}:00\n` +
                    `Events by type:\n${JSON.stringify(summary.events_by_type, null, 2)}`
                );
            }
        } catch (e) {
            console.error('Failed to load zone summary:', e);
        }
    }

    showMessage(text, type = 'info') {
        let msg = document.getElementById('zone-message');
        if (!msg) {
            msg = document.createElement('div');
            msg.id = 'zone-message';
            msg.style.cssText = `
                position: absolute;
                bottom: 10px;
                left: 50%;
                transform: translateX(-50%);
                padding: 10px 20px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 12px;
                z-index: 20;
            `;
            this.container.appendChild(msg);
        }

        const colors = {
            info: { bg: 'rgba(0, 240, 255, 0.2)', border: '#00f0ff', text: '#00f0ff' },
            success: { bg: 'rgba(5, 255, 161, 0.2)', border: '#05ffa1', text: '#05ffa1' },
            error: { bg: 'rgba(255, 42, 109, 0.2)', border: '#ff2a6d', text: '#ff2a6d' },
        };

        const c = colors[type] || colors.info;
        msg.style.background = c.bg;
        msg.style.border = `1px solid ${c.border}`;
        msg.style.color = c.text;
        msg.textContent = text;
        msg.style.display = 'block';

        if (type !== 'info') {
            setTimeout(() => this.hideMessage(), 3000);
        }
    }

    hideMessage() {
        const msg = document.getElementById('zone-message');
        if (msg) msg.style.display = 'none';
    }

    destroy() {
        if (this.canvas) {
            this.canvas.remove();
        }
        const popup = document.getElementById('zone-info-popup');
        if (popup) popup.remove();
        const msg = document.getElementById('zone-message');
        if (msg) msg.remove();
    }
}

// Export for global access
window.ZoneEditor = ZoneEditor;
