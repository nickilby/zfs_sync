const API_BASE_URL = '/api/v1';

async function fetchJSON(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`Fetch error for ${url}:`, error);
        throw error;
    }
}

const api = {
    getSystems: () => fetchJSON(`${API_BASE_URL}/systems`),
    getSystem: (id) => fetchJSON(`${API_BASE_URL}/systems/${id}`),
    getSystemHealthAll: () => fetchJSON(`${API_BASE_URL}/systems/health/all`),
    getSyncGroups: () => fetchJSON(`${API_BASE_URL}/sync-groups`),
    getSyncGroupStatus: (id) => fetchJSON(`${API_BASE_URL}/sync/groups/${id}/status`),
    getConflictsSummaryAll: async () => {
        const groups = await api.getSyncGroups();
        return Promise.all(groups.map(g => fetchJSON(`${API_BASE_URL}/conflicts/summary/${g.id}`)));
    },
    getConflictsAll: async () => {
        const groups = await api.getSyncGroups();
        const allConflicts = await Promise.all(groups.map(async g => {
            const conflicts = await fetchJSON(`${API_BASE_URL}/conflicts/sync-group/${g.id}`);
            return conflicts.map(c => ({ ...c, sync_group_name: g.name }));
        }));
        return allConflicts.flat();
    },
    getSnapshotStatsAll: async () => {
        const systems = await api.getSystems();
        return Promise.all(systems.map(s => fetchJSON(`${API_BASE_URL}/snapshots/statistics/${s.id}`)));
    },
};
