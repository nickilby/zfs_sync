let charts = {};

function createOrUpdateChart(chartId, chartConfig) {
    const ctx = document.getElementById(chartId);
    if (!ctx) {
        console.warn(`Chart canvas element '${chartId}' not found`);
        return;
    }

    try {
        // Validate chart config
        if (!chartConfig || !chartConfig.data) {
            console.warn(`Invalid chart config for '${chartId}'`);
            return;
        }

        if (charts[chartId]) {
            charts[chartId].data = chartConfig.data;
            charts[chartId].update();
        } else {
            charts[chartId] = new Chart(ctx, chartConfig);
        }
    } catch (error) {
        console.error(`Error creating/updating chart '${chartId}':`, error);
    }
}

function updateSystemStatusChart(healthData) {
    if (!healthData || !Array.isArray(healthData) || healthData.length === 0) {
        const ctx = document.getElementById('system-status-chart');
        if (ctx) {
            ctx.parentElement.innerHTML = '<p class="text-gray-500 text-center py-4">No data available</p>';
        }
        return;
    }

    const online = healthData.filter(s => s.status === 'online').length;
    const offline = healthData.length - online;

    const chartConfig = {
        type: 'doughnut',
        data: {
            labels: ['Online', 'Offline'],
            datasets: [{
                data: [online, offline],
                backgroundColor: ['#10B981', '#EF4444'],
                borderColor: ['#F9FAFB', '#F9FAFB'],
                borderWidth: 2,
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'top',
                },
                title: {
                    display: true,
                    text: 'System Status'
                }
            }
        }
    };
    createOrUpdateChart('system-status-chart', chartConfig);
}

function updateSyncHealthChart(syncStatusData) {
    if (!syncStatusData || !Array.isArray(syncStatusData) || syncStatusData.length === 0) {
        const ctx = document.getElementById('sync-health-chart');
        if (ctx) {
            ctx.parentElement.innerHTML = '<p class="text-gray-500 text-center py-4">No data available</p>';
        }
        return;
    }

    const statusCounts = {
        in_sync: 0,
        out_of_sync: 0,
        syncing: 0,
        error: 0,
        conflict: 0,
    };

    syncStatusData.forEach(status => {
        if (status) {
            statusCounts.in_sync += (status.in_sync_count || 0);
            statusCounts.out_of_sync += (status.out_of_sync_count || 0);
            statusCounts.syncing += (status.syncing_count || 0);
            statusCounts.error += (status.error_count || 0);
        }
    });

    const chartConfig = {
        type: 'bar',
        data: {
            labels: ['In Sync', 'Out of Sync', 'Syncing', 'Error'],
            datasets: [{
                label: 'Sync Health',
                data: [
                    statusCounts.in_sync,
                    statusCounts.out_of_sync,
                    statusCounts.syncing,
                    statusCounts.error
                ],
                backgroundColor: [
                    '#10B981', // Green
                    '#F59E0B', // Yellow
                    '#3B82F6', // Blue
                    '#EF4444'  // Red
                ],
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    display: false,
                },
                title: {
                    display: true,
                    text: 'Sync Health Status'
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    };
    createOrUpdateChart('sync-health-chart', chartConfig);
}

function updateSnapshotGrowthChart(historyData) {
    if (!historyData || !historyData.labels || !historyData.data ||
        !Array.isArray(historyData.labels) || !Array.isArray(historyData.data) ||
        historyData.labels.length === 0) {
        const ctx = document.getElementById('snapshot-growth-chart');
        if (ctx) {
            ctx.parentElement.innerHTML = '<p class="text-gray-500 text-center py-4">No data available</p>';
        }
        return;
    }

    const chartConfig = {
        type: 'line',
        data: {
            labels: historyData.labels,
            datasets: [{
                label: 'Total Snapshots',
                data: historyData.data,
                fill: false,
                borderColor: '#3B82F6',
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: false
                }
            }
        }
    };
    createOrUpdateChart('snapshot-growth-chart', chartConfig);
}

function updateTopPoolsChart(poolData) {
    if (!poolData || !Array.isArray(poolData) || poolData.length === 0) {
        const ctx = document.getElementById('top-pools-chart');
        if (ctx) {
            ctx.parentElement.innerHTML = '<p class="text-gray-500 text-center py-4">No data available</p>';
        }
        return;
    }

    const chartConfig = {
        type: 'bar',
        data: {
            labels: poolData.map(p => p.name || 'Unknown'),
            datasets: [{
                label: 'Snapshot Count',
                data: poolData.map(p => p.count || 0),
                backgroundColor: '#3B82F6',
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    };
    createOrUpdateChart('top-pools-chart', chartConfig);
}
