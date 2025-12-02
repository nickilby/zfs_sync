function initSSE() {
    const sseStatus = document.getElementById('sse-status');
    const source = new EventSource('/api/v1/dashboard/events');

    source.onopen = function() {
        sseStatus.classList.remove('bg-gray-500', 'bg-red-500');
        sseStatus.classList.add('bg-green-500');
        sseStatus.title = 'Connected';
        addActivity('Real-time connection established.', 'info');
    };

    source.onerror = function() {
        sseStatus.classList.remove('bg-green-500', 'bg-gray-500');
        sseStatus.classList.add('bg-red-500');
        sseStatus.title = 'Connection error';
        addActivity('Real-time connection lost. Will attempt to reconnect.', 'error');
    };

    source.addEventListener('system_heartbeat', function(event) {
        const data = JSON.parse(event.data);
        addActivity(`System heartbeat from ${data.system_hostname}.`, 'heartbeat');
        updateLastUpdated();
        // Potentially update system status on the systems page
        if (window.location.hash === '#systems' || window.location.hash === '#overview' || window.location.hash === '') {
            updateSystemsTable();
            updateOverviewData();
        }
    });

    source.addEventListener('sync_state_changed', function(event) {
        const data = JSON.parse(event.data);
        addActivity(`Sync state changed for ${data.dataset} on ${data.system_hostname} to ${data.state}.`, 'sync');
        updateLastUpdated();
        if (window.location.hash.includes('sync-groups') || window.location.hash === '#overview' || window.location.hash === '') {
            updateSyncGroupsGrid();
            updateOverviewData();
        }
    });

    source.addEventListener('conflict_detected', function(event) {
        const data = JSON.parse(event.data);
        addActivity(`New conflict detected: ${data.conflict_type} on ${data.pool}/${data.dataset}.`, 'conflict');
        updateLastUpdated();
        if (window.location.hash.includes('conflicts') || window.location.hash === '#overview' || window.location.hash === '') {
            updateConflictsTable();
            updateOverviewData();
        }
    });
    
    function updateLastUpdated() {
        const lastUpdated = document.getElementById('last-updated');
        if(lastUpdated) {
            lastUpdated.textContent = `Last update: ${new Date().toLocaleTimeString()}`;
        }
    }
}
