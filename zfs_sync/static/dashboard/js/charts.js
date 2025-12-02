let charts = {};

function createOrUpdateChart(chartId, chartConfig) {
    const ctx = document.getElementById(chartId);
    if (!ctx) return;

    if (charts[chartId]) {
        charts[chartId].data = chartConfig.data;
        charts[chartId].update();
    } else {
        charts[chartId] = new Chart(ctx, chartConfig);
    }
}

function updateSystemStatusChart(healthData) {
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
    const statusCounts = {
        in_sync: 0,
        out_of_sync: 0,
        syncing: 0,
        error: 0,
        conflict: 0,
    };

    syncStatusData.forEach(status => {
        statusCounts.in_sync += status.in_sync_count;
        statusCounts.out_of_sync += status.out_of_sync_count;
        statusCounts.syncing += status.syncing_count;
        statusCounts.error += status.error_count;
        // Assuming conflicts are tracked separately or implied
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
    const chartConfig = {
        type: 'bar',
        data: {
            labels: poolData.map(p => p.name),
            datasets: [{
                label: 'Snapshot Count',
                data: poolData.map(p => p.count),
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
