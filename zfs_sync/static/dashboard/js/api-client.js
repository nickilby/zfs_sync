const API_BASE_URL = '/api/v1';

async function fetchJSON(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            const errorText = await response.text();
            let errorMessage = `HTTP error! status: ${response.status}`;
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage = errorJson.detail || errorMessage;
            } catch {
                errorMessage = errorText || errorMessage;
            }
            throw new Error(errorMessage);
        }
        return await response.json();
    } catch (error) {
        console.error(`Fetch error for ${url}:`, error);
        throw error;
    }
}

const api = {
    getSystems: async () => {
        try {
            return await fetchJSON(`${API_BASE_URL}/systems`);
        } catch (error) {
            console.error('Failed to fetch systems:', error);
            return [];
        }
    },
    getSystem: async (id) => {
        try {
            return await fetchJSON(`${API_BASE_URL}/systems/${id}`);
        } catch (error) {
            console.error(`Failed to fetch system ${id}:`, error);
            throw error;
        }
    },
    getSystemHealthAll: async () => {
        try {
            const response = await fetchJSON(`${API_BASE_URL}/systems/health/all`);
            // Handle wrapped response format: {"systems": [...], "count": N}
            return response.systems || response || [];
        } catch (error) {
            console.error('Failed to fetch system health:', error);
            return [];
        }
    },
    getSyncGroups: async () => {
        try {
            return await fetchJSON(`${API_BASE_URL}/sync-groups`);
        } catch (error) {
            console.error('Failed to fetch sync groups:', error);
            return [];
        }
    },
    getSyncGroupStatus: async (id) => {
        try {
            return await fetchJSON(`${API_BASE_URL}/sync/groups/${id}/status`);
        } catch (error) {
            console.error(`Failed to fetch sync group status ${id}:`, error);
            throw error;
        }
    },
    getConflictsSummaryAll: async () => {
        try {
            const groups = await api.getSyncGroups();
            if (!groups || groups.length === 0) {
                return [];
            }
            const results = await Promise.allSettled(
                groups.map(g => fetchJSON(`${API_BASE_URL}/conflicts/summary/${g.id}`))
            );
            return results
                .filter(r => r.status === 'fulfilled')
                .map(r => r.value);
        } catch (error) {
            console.error('Failed to fetch conflicts summary:', error);
            return [];
        }
    },
    getConflictsAll: async () => {
        try {
            const groups = await api.getSyncGroups();
            if (!groups || groups.length === 0) {
                return [];
            }
            const results = await Promise.allSettled(
                groups.map(async g => {
                    const conflicts = await fetchJSON(`${API_BASE_URL}/conflicts/sync-group/${g.id}`);
                    return (conflicts || []).map(c => ({ ...c, sync_group_name: g.name }));
                })
            );
            return results
                .filter(r => r.status === 'fulfilled')
                .map(r => r.value)
                .flat();
        } catch (error) {
            console.error('Failed to fetch conflicts:', error);
            return [];
        }
    },
    getSnapshotStatsAll: async () => {
        try {
            const systems = await api.getSystems();
            if (!systems || systems.length === 0) {
                return [];
            }
            const results = await Promise.allSettled(
                systems.map(s => fetchJSON(`${API_BASE_URL}/snapshots/statistics/${s.id}`))
            );
            return results
                .filter(r => r.status === 'fulfilled')
                .map(r => r.value);
        } catch (error) {
            console.error('Failed to fetch snapshot stats:', error);
            return [];
        }
    },
};
