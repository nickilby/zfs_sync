document.addEventListener('DOMContentLoaded', () => {
    const views = {
        overview: document.getElementById('overview'),
        systems: document.getElementById('systems'),
        'sync-groups': document.getElementById('sync-groups'),
        conflicts: document.getElementById('conflicts'),
        statistics: document.getElementById('statistics'),
    };

    const navLinks = document.querySelectorAll('.nav-link');
    const viewTitle = document.getElementById('view-title');

    function showView(viewName) {
        Object.values(views).forEach(view => view.classList.add('hidden'));
        if (views[viewName]) {
            views[viewName].classList.remove('hidden');
        }
        viewTitle.textContent = viewName.charAt(0).toUpperCase() + viewName.slice(1).replace('-', ' ');

        navLinks.forEach(link => {
            if (link.getAttribute('href') === `#${viewName}`) {
                link.classList.add('bg-gray-900', 'text-white');
                link.classList.remove('text-gray-300', 'hover:bg-gray-700', 'hover:text-white');
            } else {
                link.classList.remove('bg-gray-900', 'text-white');
                link.classList.add('text-gray-300', 'hover:bg-gray-700', 'hover:text-white');
            }
        });
    }

    function handleHashChange() {
        const hash = window.location.hash.substring(1) || 'overview';
        showView(hash);
    }

    window.addEventListener('hashchange', handleHashChange);
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            const viewName = e.target.getAttribute('href').substring(1);
            window.location.hash = viewName;
        });
    });

    // Initial load
    handleHashChange();
    loadOverview();
    loadSystems();
    loadSyncGroups();
    loadConflicts();
    loadStatistics();

    // Initialize SSE
    initSSE();
});

async function loadOverview() {
    const overviewView = document.getElementById('overview');
    overviewView.innerHTML = `
        <div class="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <div id="total-systems-card" class="card"></div>
            <div id="total-sync-groups-card" class="card"></div>
            <div id="active-conflicts-card" class="card"></div>
            <div id="total-snapshots-card" class="card"></div>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-5">
            <div class="card"><canvas id="system-status-chart"></canvas></div>
            <div class="card"><canvas id="sync-health-chart"></canvas></div>
        </div>
        <div class="card mt-5">
            <h3 class="text-lg font-medium leading-6 text-gray-900">Recent Activity</h3>
            <ul id="recent-activity-feed" class="mt-4 space-y-2"></ul>
        </div>
    `;

    updateOverviewData();
}

async function updateOverviewData() {
    try {
        const [systems, syncGroups, health, conflicts, snapshots] = await Promise.all([
            api.getSystems(),
            api.getSyncGroups(),
            api.getSystemHealthAll(),
            api.getConflictsSummaryAll(),
            api.getSnapshotStatsAll()
        ]);

        // Total Systems
        const onlineSystems = health.filter(s => s.status === 'online').length;
        document.getElementById('total-systems-card').innerHTML = `
            <h3 class="text-base font-semibold text-gray-500">Total Systems</h3>
            <p class="text-3xl font-bold text-gray-900">${systems.length}</p>
            <p class="text-sm text-gray-500">${onlineSystems} Online / ${systems.length - onlineSystems} Offline</p>
        `;

        // Total Sync Groups
        const enabledGroups = syncGroups.filter(g => g.enabled).length;
        document.getElementById('total-sync-groups-card').innerHTML = `
            <h3 class="text-base font-semibold text-gray-500">Total Sync Groups</h3>
            <p class="text-3xl font-bold text-gray-900">${syncGroups.length}</p>
            <p class="text-sm text-gray-500">${enabledGroups} Enabled / ${syncGroups.length - enabledGroups} Disabled</p>
        `;

        // Active Conflicts
        const totalConflicts = conflicts.reduce((sum, c) => sum + c.total_conflicts, 0);
        document.getElementById('active-conflicts-card').innerHTML = `
            <h3 class="text-base font-semibold text-gray-500">Active Conflicts</h3>
            <p class="text-3xl font-bold text-red-600">${totalConflicts}</p>
            <p class="text-sm text-gray-500">Across all groups</p>
        `;

        // Total Snapshots
        const totalSnapshots = snapshots.reduce((sum, s) => sum + s.total_snapshots, 0);
        document.getElementById('total-snapshots-card').innerHTML = `
            <h3 class="text-base font-semibold text-gray-500">Total Snapshots</h3>
            <p class="text-3xl font-bold text-gray-900">${formatNumber(totalSnapshots)}</p>
            <p class="text-sm text-gray-500">Across all systems</p>
        `;

        // Charts
        updateSystemStatusChart(health);
        
        const allStatus = await Promise.all(syncGroups.map(g => api.getSyncGroupStatus(g.id)));
        updateSyncHealthChart(allStatus);

    } catch (error) {
        console.error('Failed to load overview data:', error);
    }
}


function loadSystems() {
    const systemsView = document.getElementById('systems');
    systemsView.innerHTML = `
        <div class="card">
            <div class="flex justify-between items-center mb-4">
                <h2 class="text-xl font-semibold">Systems</h2>
                <input type="text" id="system-search" placeholder="Search by hostname..." class="block w-1/3 rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm sm:leading-6">
            </div>
            <div class="table-responsive">
                <table class="min-w-full divide-y divide-gray-300">
                    <thead class="bg-gray-50">
                        <tr>
                            <th scope="col" class="py-3.5 pl-4 pr-3 text-left text-sm font-semibold text-gray-900 sm:pl-6">Hostname</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Platform</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Status</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Last Seen</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Snapshots</th>
                        </tr>
                    </thead>
                    <tbody id="systems-table-body" class="divide-y divide-gray-200 bg-white">
                    </tbody>
                </table>
            </div>
        </div>
    `;
    updateSystemsTable();
}

async function updateSystemsTable() {
    try {
        const [systems, health, stats] = await Promise.all([
            api.getSystems(),
            api.getSystemHealthAll(),
            api.getSnapshotStatsAll()
        ]);

        const healthMap = new Map(health.map(h => [h.system_id, h]));
        const statsMap = new Map(stats.map(s => [s.system_id, s]));

        const tableBody = document.getElementById('systems-table-body');
        tableBody.innerHTML = systems.map(system => {
            const systemHealth = healthMap.get(system.id) || {};
            const systemStats = statsMap.get(system.id) || { total_snapshots: 0 };
            const isOnline = systemHealth.status === 'online';
            return `
                <tr>
                    <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 sm:pl-6">${system.hostname}</td>
                    <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">${system.platform}</td>
                    <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">
                        <span class="status-dot ${isOnline ? 'status-online' : 'status-offline'}"></span>
                        ${isOnline ? 'Online' : 'Offline'}
                    </td>
                    <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">${formatDate(systemHealth.last_seen)}</td>
                    <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">${formatNumber(systemStats.total_snapshots)}</td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('Failed to update systems table:', error);
    }
}

function loadSyncGroups() {
    const syncGroupsView = document.getElementById('sync-groups');
    syncGroupsView.innerHTML = `
        <div id="sync-groups-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <!-- Sync group cards will be inserted here -->
        </div>
    `;
    updateSyncGroupsGrid();
}

async function updateSyncGroupsGrid() {
    try {
        const syncGroups = await api.getSyncGroups();
        const grid = document.getElementById('sync-groups-grid');
        
        const cardPromises = syncGroups.map(async group => {
            const status = await api.getSyncGroupStatus(group.id);
            const systems = await Promise.all(group.systems.map(id => api.getSystem(id)));
            const systemNames = systems.map(s => s.hostname).join(', ');

            return `
                <div class="card">
                    <div class="flex justify-between items-start">
                        <div>
                            <h3 class="text-lg font-semibold text-gray-800">${group.name}</h3>
                            <p class="text-sm text-gray-500">${group.description}</p>
                        </div>
                        <span class="px-2 py-1 text-xs font-semibold rounded-full ${group.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}">
                            ${group.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                    </div>
                    <div class="mt-4">
                        <p class="text-sm font-medium text-gray-600">Systems:</p>
                        <p class="text-sm text-gray-800">${systemNames}</p>
                    </div>
                    <div class="mt-4">
                        <p class="text-sm font-medium text-gray-600">Sync Status:</p>
                        <div class="flex space-x-2 mt-1">
                            <span class="text-sm text-green-600">${status.in_sync_count} In Sync</span>
                            <span class="text-sm text-yellow-600">${status.out_of_sync_count} Out of Sync</span>
                            <span class="text-sm text-blue-600">${status.syncing_count} Syncing</span>
                            <span class="text-sm text-red-600">${status.error_count} Error</span>
                        </div>
                    </div>
                </div>
            `;
        });

        grid.innerHTML = (await Promise.all(cardPromises)).join('');

    } catch (error) {
        console.error('Failed to update sync groups grid:', error);
    }
}

function loadConflicts() {
    const conflictsView = document.getElementById('conflicts');
    conflictsView.innerHTML = `
        <div class="card">
            <h2 class="text-xl font-semibold mb-4">Conflicts</h2>
            <div id="conflicts-table-container"></div>
        </div>
    `;
    updateConflictsTable();
}

async function updateConflictsTable() {
    try {
        const conflicts = await api.getConflictsAll();
        const container = document.getElementById('conflicts-table-container');

        if (conflicts.length === 0) {
            container.innerHTML = '<p class="text-gray-500">No active conflicts.</p>';
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="min-w-full divide-y divide-gray-300">
                    <thead class="bg-gray-50">
                        <tr>
                            <th scope="col" class="py-3.5 pl-4 pr-3 text-left text-sm font-semibold text-gray-900 sm:pl-6">Sync Group</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Dataset</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Snapshot</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Type</th>
                            <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Severity</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-200 bg-white">
                        ${conflicts.map(c => `
                            <tr>
                                <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm text-gray-900 sm:pl-6">${c.sync_group_name}</td>
                                <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">${c.pool}/${c.dataset}</td>
                                <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 font-mono">${c.snapshot_name}</td>
                                <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">${c.conflict_type}</td>
                                <td class="whitespace-nowrap px-3 py-4 text-sm font-medium severity-${c.severity.toLowerCase()}">${c.severity}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    } catch (error) {
        console.error('Failed to update conflicts table:', error);
    }
}

function loadStatistics() {
    const statisticsView = document.getElementById('statistics');
    statisticsView.innerHTML = `
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div class="card">
                <h3 class="text-lg font-medium">Snapshot Growth (Last 30 Days)</h3>
                <canvas id="snapshot-growth-chart"></canvas>
            </div>
            <div class="card">
                <h3 class="text-lg font-medium">Top 5 Pools by Snapshot Count</h3>
                <canvas id="top-pools-chart"></canvas>
            </div>
        </div>
    `;
    updateStatisticsCharts();
}

async function updateStatisticsCharts() {
    try {
        const stats = await api.getSnapshotStatsAll();
        
        // This is a placeholder for real historical data
        const snapshotHistory = {
            labels: Array.from({length: 30}, (_, i) => new Date(Date.now() - (29-i) * 86400000).toLocaleDateString()),
            data: Array.from({length: 30}, (_, i) => Math.floor(Math.random() * 1000 + 5000 + i * 50))
        };
        updateSnapshotGrowthChart(snapshotHistory);

        const poolData = stats.flatMap(s => s.pool_stats.map(p => ({name: p.pool_name, count: p.snapshot_count})))
            .reduce((acc, curr) => {
                const existing = acc.find(item => item.name === curr.name);
                if (existing) {
                    existing.count += curr.count;
                } else {
                    acc.push(curr);
                }
                return acc;
            }, [])
            .sort((a, b) => b.count - a.count)
            .slice(0, 5);
        
        updateTopPoolsChart(poolData);

    } catch (error) {
        console.error('Failed to update statistics charts:', error);
    }
}

function addActivity(message, type = 'info') {
    const feed = document.getElementById('recent-activity-feed');
    if (!feed) return;

    const item = document.createElement('li');
    item.className = 'flex items-center space-x-3';
    
    const icon = {
        info: '<svg class="h-5 w-5 text-gray-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" /></svg>',
        heartbeat: '<svg class="h-5 w-5 text-green-500" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3.172 5.172a4 4 0 015.656 0L10 6.343l1.172-1.171a4 4 0 115.656 5.656L10 17.657l-6.828-6.829a4 4 0 010-5.656z" clip-rule="evenodd" /></svg>',
        conflict: '<svg class="h-5 w-5 text-red-500" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 3.011-1.742 3.011H4.42c-1.53 0-2.493-1.677-1.743-3.011l5.58-9.92zM10 13a1 1 0 110-2 1 1 0 010 2zm-1-8a1 1 0 00-1 1v3a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" /></svg>',
        sync: '<svg class="h-5 w-5 text-blue-500" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path d="M10 3a.75.75 0 01.75.75v1.5a.75.75 0 01-1.5 0v-1.5A.75.75 0 0110 3zM12.5 5.031a.75.75 0 01.64.995l-1.1 3.85a.75.75 0 01-1.48-.424l1.1-3.85a.75.75 0 01.84-.571zM6.86 6.026a.75.75 0 01.84.571l1.1 3.85a.75.75 0 01-1.48.424l-1.1-3.85a.75.75 0 01.64-.995zM10 17a.75.75 0 01-.75-.75v-1.5a.75.75 0 011.5 0v1.5A.75.75 0 0110 17zM7.5 14.969a.75.75 0 01-.64-.995l1.1-3.85a.75.75 0 011.48.424l-1.1 3.85a.75.75 0 01-.84.571zM13.14 13.974a.75.75 0 01-.84-.571l-1.1-3.85a.75.75 0 111.48-.424l1.1 3.85a.75.75 0 01-.64.995z" /></svg>'
    }[type] || icon.info;

    item.innerHTML = `
        <div>${icon}</div>
        <div class="flex-1">
            <p class="text-sm text-gray-700">${message}</p>
            <p class="text-xs text-gray-500">${new Date().toLocaleTimeString()}</p>
        </div>
    `;

    feed.prepend(item);
    if (feed.children.length > 20) {
        feed.lastChild.remove();
    }
}
