let sseSource = null;
let sseReconnectTimeout = null;
let sseReconnectAttempts = 0;
let fallbackPollingInterval = null;
const MAX_RECONNECT_ATTEMPTS = 10;
const INITIAL_RECONNECT_DELAY = 1000; // 1 second
const MAX_RECONNECT_DELAY = 30000; // 30 seconds
const FALLBACK_POLL_INTERVAL = 30000; // 30 seconds

function parseSSEData(event) {
    try {
        // SSE format: event.data contains the JSON string
        return JSON.parse(event.data);
    } catch (error) {
        console.error('Failed to parse SSE data:', error, event.data);
        return null;
    }
}

function updateLastUpdated() {
    const lastUpdated = document.getElementById('last-updated');
    if (lastUpdated) {
        lastUpdated.textContent = `Last update: ${new Date().toLocaleTimeString()}`;
    }
}

function startFallbackPolling() {
    if (fallbackPollingInterval) return;

    console.log('Starting fallback polling');
    fallbackPollingInterval = setInterval(() => {
        // Refresh data when SSE is down
        if (window.location.hash === '#systems' || window.location.hash === '#overview' || window.location.hash === '') {
            if (typeof updateSystemsTable === 'function') updateSystemsTable();
            if (typeof updateOverviewData === 'function') updateOverviewData();
        }
        if (window.location.hash.includes('sync-groups') || window.location.hash === '#overview' || window.location.hash === '') {
            if (typeof updateSyncGroupsGrid === 'function') updateSyncGroupsGrid();
            if (typeof updateOverviewData === 'function') updateOverviewData();
        }
        if (window.location.hash.includes('conflicts') || window.location.hash === '#overview' || window.location.hash === '') {
            if (typeof updateConflictsTable === 'function') updateConflictsTable();
            if (typeof updateOverviewData === 'function') updateOverviewData();
        }
        updateLastUpdated();
    }, FALLBACK_POLL_INTERVAL);
}

function stopFallbackPolling() {
    if (fallbackPollingInterval) {
        clearInterval(fallbackPollingInterval);
        fallbackPollingInterval = null;
        console.log('Stopped fallback polling');
    }
}

function connectSSE() {
    const sseStatus = document.getElementById('sse-status');
    if (!sseStatus) return;

    // Close existing connection if any
    if (sseSource) {
        sseSource.close();
    }

    sseSource = new EventSource('/api/v1/dashboard/events');

    sseSource.onopen = function() {
        sseStatus.classList.remove('bg-gray-500', 'bg-red-500');
        sseStatus.classList.add('bg-green-500');
        sseStatus.title = 'Connected';
        sseReconnectAttempts = 0;
        stopFallbackPolling();
        if (sseReconnectAttempts === 0) {
            addActivity('Real-time connection established.', 'info');
        } else {
            addActivity('Real-time connection re-established.', 'info');
        }
    };

    sseSource.onerror = function(event) {
        const sseStatus = document.getElementById('sse-status');
        if (!sseStatus) return;

        // Check if connection is closed
        if (sseSource.readyState === EventSource.CLOSED) {
            sseStatus.classList.remove('bg-green-500', 'bg-gray-500');
            sseStatus.classList.add('bg-red-500');
            sseStatus.title = 'Connection closed';

            // Start fallback polling
            startFallbackPolling();

            // Attempt reconnection with exponential backoff
            if (sseReconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                const delay = Math.min(
                    INITIAL_RECONNECT_DELAY * Math.pow(2, sseReconnectAttempts),
                    MAX_RECONNECT_DELAY
                );
                sseReconnectAttempts++;

                console.log(`SSE connection lost. Reconnecting in ${delay}ms (attempt ${sseReconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);
                addActivity(`Real-time connection lost. Reconnecting in ${Math.round(delay/1000)}s...`, 'error');

                sseReconnectTimeout = setTimeout(() => {
                    connectSSE();
                }, delay);
            } else {
                console.error('Max SSE reconnection attempts reached. Using fallback polling.');
                addActivity('Real-time connection failed. Using fallback polling.', 'error');
            }
        } else if (sseSource.readyState === EventSource.CONNECTING) {
            sseStatus.classList.remove('bg-green-500', 'bg-red-500');
            sseStatus.classList.add('bg-gray-500');
            sseStatus.title = 'Connecting...';
        }
    };

    sseSource.addEventListener('connected', function(event) {
        const data = parseSSEData(event);
        if (data) {
            console.log('SSE connected:', data);
        }
    });

    sseSource.addEventListener('system_heartbeat', function(event) {
        const data = parseSSEData(event);
        if (data && data.data) {
            addActivity(`System heartbeat from ${data.data.system_hostname || 'unknown'}.`, 'heartbeat');
            updateLastUpdated();
            // Potentially update system status on the systems page
            if (window.location.hash === '#systems' || window.location.hash === '#overview' || window.location.hash === '') {
                if (typeof updateSystemsTable === 'function') updateSystemsTable();
                if (typeof updateOverviewData === 'function') updateOverviewData();
            }
        }
    });

    sseSource.addEventListener('sync_state_changed', function(event) {
        const data = parseSSEData(event);
        if (data && data.data) {
            addActivity(`Sync state changed for ${data.data.dataset || 'unknown'} on ${data.data.system_hostname || 'unknown'} to ${data.data.state || 'unknown'}.`, 'sync');
            updateLastUpdated();
            if (window.location.hash.includes('sync-groups') || window.location.hash === '#overview' || window.location.hash === '') {
                if (typeof updateSyncGroupsGrid === 'function') updateSyncGroupsGrid();
                if (typeof updateOverviewData === 'function') updateOverviewData();
            }
        }
    });

    sseSource.addEventListener('conflict_detected', function(event) {
        const data = parseSSEData(event);
        if (data && data.data) {
            addActivity(`New conflict detected: ${data.data.conflict_type || 'unknown'} on ${data.data.pool || 'unknown'}/${data.data.dataset || 'unknown'}.`, 'conflict');
            updateLastUpdated();
            if (window.location.hash.includes('conflicts') || window.location.hash === '#overview' || window.location.hash === '') {
                if (typeof updateConflictsTable === 'function') updateConflictsTable();
                if (typeof updateOverviewData === 'function') updateOverviewData();
            }
        }
    });
}

function initSSE() {
    connectSSE();

    // Cleanup on page unload
    window.addEventListener('beforeunload', function() {
        if (sseSource) {
            sseSource.close();
        }
        if (sseReconnectTimeout) {
            clearTimeout(sseReconnectTimeout);
        }
        stopFallbackPolling();
    });
}
