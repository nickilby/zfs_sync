# Custom Dashboard Implementation Plan

## Overview

This document outlines the complete plan for building a modern, real-time web dashboard for monitoring and managing ZFS snapshot synchronization across systems. The dashboard will be served directly by the FastAPI application, use existing API endpoints for data, and provide real-time updates without authentication (internal use only).

## Technology Stack

### Frontend
- **HTML5/CSS3**: Semantic HTML with modern CSS
- **JavaScript (ES6+)**: Vanilla JavaScript (no framework dependencies)
- **Chart.js** (v4.x): Lightweight charting library for visualizations
- **CSS Framework**: Tailwind CSS (via CDN) for rapid, responsive styling
- **Real-time Updates**: Server-Sent Events (SSE) for push updates from server

### Backend Integration
- **FastAPI Static Files**: Serve dashboard HTML/CSS/JS as static files
- **FastAPI SSE Endpoint**: New endpoint for real-time data streaming
- **Existing REST APIs**: Leverage all existing `/api/v1/*` endpoints

### Why This Stack?
- **No build step**: Direct HTML/CSS/JS files, easy to maintain
- **Lightweight**: Minimal dependencies, fast loading
- **Real-time**: SSE is simpler than WebSockets for one-way updates
- **Modern**: Uses modern browser APIs and CSS features
- **Self-contained**: Dashboard served by the same FastAPI app

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Application                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Static Files (HTML/CSS/JS)                     │   │
│  │  Route: GET /dashboard                          │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  REST API Endpoints (existing)                  │   │
│  │  - /api/v1/systems                              │   │
│  │  - /api/v1/sync-groups                          │   │
│  │  - /api/v1/sync/groups/{id}/status              │   │
│  │  - /api/v1/conflicts/summary/{id}               │   │
│  │  - /api/v1/systems/health/all                   │   │
│  │  - /api/v1/snapshots/statistics/{id}            │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  SSE Endpoint (new)                              │   │
│  │  Route: GET /api/v1/dashboard/events            │   │
│  │  Streams: system updates, sync status changes    │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    Browser Client                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Dashboard HTML (Single Page Application)        │   │
│  │  - Fetches initial data via REST APIs            │   │
│  │  - Connects to SSE for real-time updates          │   │
│  │  - Updates UI when events received                │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Dashboard Views

### 1. Overview Dashboard (Main Page)

**Layout**: Grid of cards and charts

**Components**:
- **Header**: Application name, version, last update time
- **Summary Cards** (4 cards in a row):
  - Total Systems (with online/offline breakdown)
  - Total Sync Groups (with enabled/disabled count)
  - Active Conflicts (with severity breakdown)
  - Total Snapshots (across all systems)
- **System Status Chart**: Pie/Donut chart showing online vs offline systems
- **Sync Health Chart**: Bar chart showing sync status breakdown (in_sync, out_of_sync, syncing, error, conflict)
- **Recent Activity Feed**: Scrollable list of recent events (system heartbeats, sync operations, conflicts)

**API Endpoints Used**:
- `GET /api/v1/systems/health/all` - System health data
- `GET /api/v1/sync-groups` - Sync groups list
- `GET /api/v1/sync/groups/{id}/status` - Sync status for each group
- `GET /api/v1/conflicts/summary/{id}` - Conflict summaries
- `GET /api/v1/systems` - System list for counts

### 2. Systems View

**Layout**: Table with filters and detail panels

**Components**:
- **Systems Table**:
  - Columns: Hostname, Platform, Status (online/offline), Last Seen, Snapshot Count, Actions
  - Sortable columns
  - Filter by status (online/offline/all)
  - Search by hostname
- **System Detail Panel** (expandable row or modal):
  - System metadata (hostname, platform, SSH details)
  - Health timeline (connectivity over last 24 hours)
  - Snapshot statistics (total, by pool, by dataset)
  - Recent snapshots list

**API Endpoints Used**:
- `GET /api/v1/systems` - List all systems
- `GET /api/v1/systems/{id}/health` - System health details
- `GET /api/v1/snapshots/statistics/{id}` - Snapshot statistics
- `GET /api/v1/snapshots/system/{id}` - Recent snapshots

### 3. Sync Groups View

**Layout**: Cards for each sync group with status indicators

**Components**:
- **Sync Group Cards**:
  - Group name and description
  - Enabled/disabled status badge
  - Systems in group (list of hostnames)
  - Sync status breakdown (in_sync, out_of_sync, syncing, error, conflict counts)
  - Last sync timestamp
  - Progress indicator (if syncing)
  - Actions: View details, Trigger sync check
- **Sync Group Detail View** (click to expand):
  - Detailed status breakdown
  - List of out-of-sync snapshots
  - Sync actions needed
  - Conflict list

**API Endpoints Used**:
- `GET /api/v1/sync-groups` - List all sync groups
- `GET /api/v1/sync/groups/{id}/status` - Sync status summary
- `GET /api/v1/sync/groups/{id}/states` - Detailed sync states
- `GET /api/v1/sync/groups/{id}/actions` - Pending sync actions
- `GET /api/v1/conflicts/sync-group/{id}` - Conflicts for group

### 4. Conflicts View

**Layout**: List of conflicts with resolution options

**Components**:
- **Conflicts Table**:
  - Columns: Sync Group, Pool/Dataset, Snapshot Name, Type, Severity, Affected Systems, Actions
  - Filter by type (diverged, orphaned, missing)
  - Filter by severity (low, medium, high)
  - Sort by severity or date
- **Conflict Detail Panel**:
  - Conflict details and affected systems
  - Recommended resolution strategy
  - Resolution action buttons (if applicable)

**API Endpoints Used**:
- `GET /api/v1/conflicts/sync-group/{id}` - Conflicts for sync group
- `GET /api/v1/conflicts/summary/{id}` - Conflict summary
- `POST /api/v1/conflicts/resolve` - Resolve conflict (if implemented)

### 5. Statistics View

**Layout**: Charts and metrics

**Components**:
- **Snapshot Growth Chart**: Line chart showing snapshot count over time (last 30 days)
- **Sync Success Rate Chart**: Line chart showing sync success/failure rates
- **System Uptime Chart**: Bar chart showing uptime percentage per system
- **Top Pools by Snapshot Count**: Horizontal bar chart
- **Data Volume Chart**: Stacked area chart showing snapshot sizes over time

**API Endpoints Used**:
- `GET /api/v1/snapshots/statistics/{id}` - Per-system statistics
- `GET /api/v1/snapshots/history/{id}` - Snapshot history
- `GET /api/v1/systems/health/all` - System health data

## Real-Time Updates

### Server-Sent Events (SSE) Implementation

**New Endpoint**: `GET /api/v1/dashboard/events`

**Event Types**:
1. **system_heartbeat**: System sent heartbeat (updates last_seen)
2. **system_offline**: System went offline (heartbeat timeout)
3. **snapshot_reported**: New snapshot reported
4. **sync_state_changed**: Sync state changed (in_sync → out_of_sync, etc.)
5. **conflict_detected**: New conflict detected
6. **conflict_resolved**: Conflict resolved

**Event Format**:
```json
{
  "event": "system_heartbeat",
  "timestamp": "2025-11-27T12:00:00Z",
  "data": {
    "system_id": "uuid",
    "system_hostname": "server1",
    "last_seen": "2025-11-27T12:00:00Z"
  }
}
```

**Client Implementation**:
- Connect to SSE endpoint on page load
- Parse incoming events
- Update relevant UI components based on event type
- Debounce rapid updates to prevent UI flicker

**Update Frequency**:
- Initial data load: All endpoints called on page load
- Real-time updates: Via SSE (push-based)
- Fallback polling: If SSE connection lost, fall back to polling every 30 seconds

## File Structure

```
zfs_sync/
├── api/
│   ├── routes/
│   │   └── dashboard.py          # New: Dashboard routes (HTML, SSE)
│   └── ...
├── static/                       # New: Static files directory
│   ├── dashboard/
│   │   ├── index.html            # Main dashboard page
│   │   ├── css/
│   │   │   └── dashboard.css     # Custom styles
│   │   └── js/
│   │       ├── dashboard.js       # Main dashboard logic
│   │       ├── api-client.js     # API wrapper functions
│   │       ├── sse-client.js     # SSE connection handler
│   │       ├── charts.js          # Chart initialization/updates
│   │       └── utils.js           # Utility functions
│   └── ...
└── ...
```

## Implementation Steps

### Phase 1: Basic Dashboard Structure
1. Create `zfs_sync/api/routes/dashboard.py` with route to serve HTML
2. Create `zfs_sync/static/dashboard/index.html` with basic layout
3. Add static file mounting in `zfs_sync/api/app.py`
4. Test dashboard is accessible at `/dashboard`

### Phase 2: API Integration
1. Create `static/dashboard/js/api-client.js` with functions to call all needed endpoints
2. Create `static/dashboard/js/utils.js` for formatting, date handling, etc.
3. Implement Overview Dashboard view with summary cards
4. Fetch and display real data from APIs

### Phase 3: Charts and Visualizations
1. Add Chart.js library (via CDN)
2. Create `static/dashboard/js/charts.js` for chart initialization
3. Implement System Status pie chart
4. Implement Sync Health bar chart
5. Add other charts as needed

### Phase 4: Additional Views
1. Implement Systems View with table
2. Implement Sync Groups View with cards
3. Implement Conflicts View with table
4. Implement Statistics View with charts

### Phase 5: Real-Time Updates
1. Create SSE endpoint in `dashboard.py`
2. Create `static/dashboard/js/sse-client.js` for SSE connection
3. Integrate SSE client into main dashboard
4. Update UI components when events received
5. Add connection status indicator
6. Implement fallback polling

### Phase 6: Polish and UX
1. Add loading states and spinners
2. Add error handling and user-friendly error messages
3. Add responsive design for mobile/tablet
4. Add smooth transitions and animations
5. Add tooltips and help text
6. Test across browsers

## UI/UX Design Guidelines

### Color Scheme
- **Primary**: Blue (#3B82F6) for primary actions and headers
- **Success**: Green (#10B981) for online status, in_sync
- **Warning**: Yellow (#F59E0B) for out_of_sync, medium severity
- **Error**: Red (#EF4444) for offline, errors, high severity conflicts
- **Neutral**: Gray (#6B7280) for disabled, unknown status
- **Background**: Light gray (#F9FAFB) for page background
- **Cards**: White (#FFFFFF) with subtle shadow

### Typography
- **Headings**: System font stack (sans-serif)
- **Body**: System font stack
- **Monospace**: For system hostnames, IDs, timestamps

### Spacing
- Use consistent spacing scale (4px, 8px, 16px, 24px, 32px)
- Card padding: 24px
- Section margins: 32px

### Components
- **Cards**: White background, rounded corners (8px), subtle shadow
- **Badges**: Small rounded pills for status indicators
- **Tables**: Clean borders, alternating row colors
- **Buttons**: Rounded corners, clear hover states
- **Charts**: Clean, minimal styling, readable labels

### Responsive Design
- **Desktop**: Multi-column layout, side-by-side charts
- **Tablet**: 2-column layout, stacked on smaller screens
- **Mobile**: Single column, stacked cards

## API Endpoints Summary

### Existing Endpoints to Use
- `GET /api/v1/systems` - List systems
- `GET /api/v1/systems/{id}` - System details
- `GET /api/v1/systems/health/all` - All system health
- `GET /api/v1/systems/health/online` - Online systems
- `GET /api/v1/systems/health/offline` - Offline systems
- `GET /api/v1/sync-groups` - List sync groups
- `GET /api/v1/sync/groups/{id}/status` - Sync status summary
- `GET /api/v1/sync/groups/{id}/states` - Sync states
- `GET /api/v1/conflicts/sync-group/{id}` - Conflicts
- `GET /api/v1/conflicts/summary/{id}` - Conflict summary
- `GET /api/v1/snapshots/statistics/{id}` - Snapshot statistics
- `GET /api/v1/snapshots/history/{id}` - Snapshot history

### New Endpoints to Create
- `GET /dashboard` - Serve dashboard HTML
- `GET /api/v1/dashboard/events` - SSE stream for real-time updates

## Security Considerations

- **No Authentication**: Dashboard is internal-only, not publicly accessible
- **CORS**: Not needed (same origin)
- **Rate Limiting**: Consider rate limiting on SSE endpoint if needed
- **Input Validation**: All API calls use existing validated endpoints

## Performance Considerations

- **Caching**: Cache API responses client-side for 5-10 seconds
- **Debouncing**: Debounce rapid SSE events to prevent UI thrashing
- **Lazy Loading**: Load detailed views on demand
- **Pagination**: Use pagination for large lists (systems, snapshots)
- **Chart Optimization**: Limit data points in time-series charts (sample if needed)

## Testing Strategy

1. **Manual Testing**: Test each view and real-time updates
2. **Browser Testing**: Test in Chrome, Firefox, Safari, Edge
3. **Responsive Testing**: Test on different screen sizes
4. **Performance Testing**: Test with many systems/snapshots
5. **SSE Testing**: Test SSE connection stability and reconnection

## Documentation Requirements

- **README Section**: Add dashboard section to main README
- **API Documentation**: Document new SSE endpoint in API docs
- **Code Comments**: Comment complex JavaScript logic
- **User Guide**: Simple guide for using the dashboard (optional)

## Example Code Structure

### dashboard.py (Backend Route)
```python
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML page."""
    with open("zfs_sync/static/dashboard/index.html", "r") as f:
        return HTMLResponse(content=f.read())

@router.get("/api/v1/dashboard/events")
async def dashboard_events():
    """SSE endpoint for real-time dashboard updates."""
    async def event_generator():
        # Implementation for SSE streaming
        # Monitor database changes, emit events
        pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

### index.html (Main Dashboard)
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZFS Sync Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <link rel="stylesheet" href="/static/dashboard/css/dashboard.css">
</head>
<body>
    <div id="app">
        <!-- Dashboard content -->
    </div>
    <script src="/static/dashboard/js/utils.js"></script>
    <script src="/static/dashboard/js/api-client.js"></script>
    <script src="/static/dashboard/js/sse-client.js"></script>
    <script src="/static/dashboard/js/charts.js"></script>
    <script src="/static/dashboard/js/dashboard.js"></script>
</body>
</html>
```

## Future Enhancements (Not in Initial Implementation)

- Export data (CSV, JSON)
- Filtering and search across all views
- Customizable dashboard layouts
- Dark mode
- Historical data views (beyond 30 days)
- Alert configuration UI
- System management actions from dashboard

