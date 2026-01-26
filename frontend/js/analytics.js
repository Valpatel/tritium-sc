/**
 * TRITIUM-SC Analytics View
 * Detection trends and statistics
 */

// Safe notification helper
function notify(title, message, type = 'info') {
    if (typeof showNotification === 'function') {
        showNotification(title, message, type);
    } else if (window.TRITIUM?.showNotification) {
        window.TRITIUM.showNotification(title, message, type);
    } else {
        console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
    }
}

// State
let analyticsState = {
    data: null,
    days: 7,
};

/**
 * Initialize analytics view
 */
async function initAnalyticsView() {
    await loadAnalytics();
}

/**
 * Load analytics data from API
 */
async function loadAnalytics() {
    const days = parseInt(document.getElementById('analytics-days')?.value || '7');
    analyticsState.days = days;

    try {
        const response = await fetch(`/api/search/trends?days=${days}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        analyticsState.data = data;
        renderAnalytics(data);

    } catch (e) {
        console.error('Failed to load analytics:', e);
        notify('ERROR', 'Failed to load analytics: ' + e.message, 'error');
    }
}

/**
 * Render analytics data
 */
function renderAnalytics(data) {
    // Summary stats
    document.getElementById('analytics-total').textContent = data.total_detections || 0;
    document.getElementById('analytics-people').textContent = data.total_people || 0;
    document.getElementById('analytics-vehicles').textContent = data.total_vehicles || 0;
    document.getElementById('analytics-peak').textContent = data.peak_hour !== null ? `${String(data.peak_hour).padStart(2, '0')}:00` : '--';

    // Daily chart
    renderDailyChart(data.daily_counts);

    // Hourly chart
    renderHourlyChart(data.hourly_distribution);

    // Recent targets
    renderRecentTargets(data.recent_targets);

    // Channel breakdown
    renderChannelBreakdown(data.by_channel);
}

/**
 * Render daily detections chart
 */
function renderDailyChart(dailyCounts) {
    const container = document.getElementById('analytics-daily-chart');
    const labels = document.getElementById('analytics-daily-labels');

    if (!dailyCounts || Object.keys(dailyCounts).length === 0) {
        container.innerHTML = '<div class="text-muted" style="margin: auto;">No data available</div>';
        labels.innerHTML = '';
        return;
    }

    const days = Object.entries(dailyCounts).sort((a, b) => a[0].localeCompare(b[0]));
    const maxTotal = Math.max(...days.map(([_, d]) => d.total)) || 1;

    container.innerHTML = days.map(([date, counts]) => {
        const personHeight = (counts.person / maxTotal * 100) || 0;
        const vehicleHeight = (counts.vehicle / maxTotal * 100) || 0;
        const dayOfWeek = new Date(date).toLocaleDateString('en', { weekday: 'short' });

        return `
            <div class="daily-bar-group" style="flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%;">
                <div style="flex: 1; display: flex; flex-direction: column; justify-content: flex-end; gap: 2px; width: 100%;">
                    <div style="height: ${personHeight}%; background: var(--magenta); min-height: ${personHeight > 0 ? '2px' : '0'}; border-radius: 2px 2px 0 0;" title="${counts.person} people"></div>
                    <div style="height: ${vehicleHeight}%; background: var(--yellow); min-height: ${vehicleHeight > 0 ? '2px' : '0'}; border-radius: 0 0 2px 2px;" title="${counts.vehicle} vehicles"></div>
                </div>
            </div>
        `;
    }).join('');

    labels.innerHTML = days.map(([date]) => {
        const dayOfWeek = new Date(date).toLocaleDateString('en', { weekday: 'short' });
        const dayNum = date.split('-')[2];
        return `<span>${dayNum}</span>`;
    }).join('');
}

/**
 * Render hourly distribution chart
 */
function renderHourlyChart(hourlyData) {
    const container = document.getElementById('analytics-hourly-chart');

    if (!hourlyData || !Array.isArray(hourlyData)) {
        container.innerHTML = '<div class="text-muted" style="margin: auto;">No data available</div>';
        return;
    }

    const maxHour = Math.max(...hourlyData) || 1;

    container.innerHTML = hourlyData.map((count, hour) => {
        const height = (count / maxHour * 100) || 0;
        return `
            <div class="hour-bar-analytics"
                 style="flex: 1; height: ${Math.max(height, 2)}%; background: var(--cyan); border-radius: 2px 2px 0 0; cursor: pointer;"
                 title="${String(hour).padStart(2, '0')}:00 - ${count} detections"
                 onclick="filterByHour(${hour})">
            </div>
        `;
    }).join('');
}

/**
 * Render recent targets
 */
function renderRecentTargets(targets) {
    const container = document.getElementById('analytics-recent-targets');

    if (!targets || targets.length === 0) {
        container.innerHTML = '<div class="text-muted">No recent targets today</div>';
        return;
    }

    container.innerHTML = targets.slice(0, 20).map(target => {
        const thumbnailUrl = `/api/search/thumbnail/${target.thumbnail_id}`;
        const type = target.target_type === 'person' ? '👤' : '🚗';

        return `
            <div class="recent-target-card" onclick="viewTargetFromAnalytics('${target.thumbnail_id}')">
                <img src="${thumbnailUrl}" alt="Target"
                     onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect fill=%22%231a1a2e%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2255%22 text-anchor=%22middle%22 fill=%22%2300f0ff%22 font-size=%2230%22>?</text></svg>'">
                <div class="recent-target-info">
                    <span>${type}</span>
                    <span class="text-muted">CH${target.channel || '?'}</span>
                </div>
                ${target.label ? `<div class="recent-target-label">${target.label}</div>` : ''}
            </div>
        `;
    }).join('');
}

/**
 * Render channel breakdown
 */
function renderChannelBreakdown(byChannel) {
    const container = document.getElementById('analytics-channels');

    if (!byChannel || Object.keys(byChannel).length === 0) {
        container.innerHTML = '<div class="text-muted">No channel data available</div>';
        return;
    }

    const totalDetections = Object.values(byChannel).reduce((a, b) => a + b, 0);
    const sorted = Object.entries(byChannel).sort((a, b) => b[1] - a[1]);

    container.innerHTML = sorted.map(([channel, count]) => {
        const percentage = ((count / totalDetections) * 100).toFixed(1);
        return `
            <div class="channel-stat-box" onclick="filterByChannel(${channel})">
                <div class="channel-stat-name">CH${String(channel).padStart(2, '0')}</div>
                <div class="channel-stat-value">${count}</div>
                <div class="channel-stat-bar">
                    <div class="channel-stat-fill" style="width: ${percentage}%;"></div>
                </div>
                <div class="channel-stat-pct">${percentage}%</div>
            </div>
        `;
    }).join('');
}

/**
 * Filter targets by hour - switch to targets view with hour context
 */
function filterByHour(hour) {
    // Store the hour filter
    sessionStorage.setItem('tritium_hour_filter', hour);

    // Switch to targets view
    if (window.TRITIUM) {
        window.TRITIUM.switchView('targets');
        notify('FILTER', `Showing detections from ${String(hour).padStart(2, '0')}:00 - ${String(hour).padStart(2, '0')}:59`, 'info');
    }
}

/**
 * Filter targets by channel
 */
function filterByChannel(channel) {
    // Set filter and switch to targets view
    if (window.TRITIUM) {
        window.TRITIUM.switchView('targets');
        setTimeout(() => {
            const select = document.getElementById('target-channel-filter');
            if (select) {
                select.value = channel;
                if (typeof loadTargets !== 'undefined') {
                    loadTargets();
                }
            }
        }, 100);
    }
}

/**
 * View a target from analytics
 */
function viewTargetFromAnalytics(thumbnailId) {
    if (window.TRITIUM) {
        window.TRITIUM.switchView('targets');
        setTimeout(() => {
            if (typeof selectTarget !== 'undefined') {
                selectTarget(thumbnailId);
            }
        }, 300);
    }
}

// Add CSS styles
const analyticsStyles = document.createElement('style');
analyticsStyles.textContent = `
.recent-target-card {
    background: rgba(26, 26, 46, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 4px;
    overflow: hidden;
    cursor: pointer;
    transition: all 0.2s ease;
}

.recent-target-card:hover {
    border-color: var(--cyan);
    transform: translateY(-2px);
}

.recent-target-card img {
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
    background: #0a0a0f;
}

.recent-target-info {
    display: flex;
    justify-content: space-between;
    padding: 4px 6px;
    font-size: 0.7rem;
}

.recent-target-label {
    padding: 2px 6px;
    background: var(--cyan);
    color: #000;
    font-size: 0.6rem;
    text-align: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.channel-stat-box {
    background: rgba(26, 26, 46, 0.6);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 4px;
    padding: var(--space-sm);
    min-width: 120px;
    cursor: pointer;
    transition: all 0.2s ease;
}

.channel-stat-box:hover {
    border-color: var(--cyan);
    background: rgba(0, 240, 255, 0.1);
}

.channel-stat-name {
    font-size: 0.75rem;
    color: var(--cyan);
    font-weight: bold;
    margin-bottom: 4px;
}

.channel-stat-value {
    font-size: 1.2rem;
    font-weight: bold;
    color: var(--text-primary);
}

.channel-stat-bar {
    height: 4px;
    background: rgba(0, 240, 255, 0.2);
    border-radius: 2px;
    margin: 6px 0 4px;
    overflow: hidden;
}

.channel-stat-fill {
    height: 100%;
    background: var(--cyan);
    border-radius: 2px;
}

.channel-stat-pct {
    font-size: 0.65rem;
    color: var(--text-muted);
}

.hour-bar-analytics:hover {
    background: var(--green) !important;
}

.daily-bar-group:hover div {
    opacity: 0.8;
}
`;
document.head.appendChild(analyticsStyles);

// Expose functions globally
window.initAnalyticsView = initAnalyticsView;
window.loadAnalytics = loadAnalytics;
window.filterByHour = filterByHour;
window.filterByChannel = filterByChannel;
window.viewTargetFromAnalytics = viewTargetFromAnalytics;
