# ZFS Sync Dashboard Guide

A guide to using the ZFS Sync web dashboard for monitoring and managing your sync environment.

## Table of Contents

1. [Accessing the Dashboard](#accessing-the-dashboard)
2. [Dashboard Overview](#dashboard-overview)
3. [View Descriptions](#view-descriptions)
4. [Real-time Updates](#real-time-updates)
5. [Common Tasks](#common-tasks)
6. [Dashboard Limitations](#dashboard-limitations)

---

## Accessing the Dashboard

### URL

The dashboard is available at the root URL of your ZFS Sync server:

```
http://your-server-ip:8000/
```

Or if running locally:

```
http://localhost:8000/
```

### Requirements

- Modern web browser (Chrome, Firefox, Safari, Edge)
- JavaScript enabled
- Network connectivity to ZFS Sync server

### Authentication

Currently, the dashboard does not require authentication. Access control should be handled at the network level (firewall, reverse proxy, etc.).

**Security Note**: For production deployments, consider:
- Using a reverse proxy with authentication (nginx, Traefik)
- Restricting network access to the dashboard
- Implementing authentication in future versions

---

## Dashboard Overview

### Layout

The dashboard consists of:

1. **Navigation Bar** (top)
   - Links to different views
   - SSE connection status indicator
   - Last updated timestamp

2. **Header** (below navigation)
   - Current view title

3. **Main Content Area**
   - View-specific content
   - Cards, tables, charts, and lists

### Navigation

The dashboard has five main views:

- **Overview** - System status summary and recent activity
- **Systems** - Registered systems and health status
- **Sync Groups** - Sync group configuration and status
- **Conflicts** - Detected conflicts and resolution options
- **Statistics** - Charts, trends, and historical data

Click on any navigation link to switch views. The active view is highlighted in the navigation bar.

---

## View Descriptions

### Overview

The Overview view provides a high-level summary of your ZFS Sync environment.

#### Summary Cards

Four summary cards at the top show:

1. **Total Systems**
   - Total number of registered systems
   - Breakdown: Online / Offline

2. **Total Sync Groups**
   - Total number of sync groups
   - Breakdown: Enabled / Disabled

3. **Active Conflicts**
   - Total number of active conflicts across all sync groups
   - Click to navigate to Conflicts view

4. **Total Snapshots**
   - Total number of snapshots tracked across all systems

#### Charts

Two charts display:

1. **System Status Chart**
   - Pie or bar chart showing distribution of system health status
   - Online vs Offline systems

2. **Sync Health Chart**
   - Visualization of sync status across sync groups
   - In-sync vs Out-of-sync states

#### Recent Activity Feed

A list of recent activities, such as:
- System registrations
- Snapshot reports
- Sync operations
- Conflict detections

**Note**: Activity feed updates in real-time via Server-Sent Events (SSE).

### Systems

The Systems view lists all registered ZFS systems.

#### System List

For each system, the dashboard displays:

- **Hostname** - System hostname
- **Platform** - Operating system platform (linux, freebsd, etc.)
- **Status** - Health status (Online/Offline/Unknown)
- **Last Seen** - Timestamp of last heartbeat
- **SSH Configuration** - SSH hostname, user, and port (if configured)

#### System Details

Click on a system (if supported) or use the API to view:
- System UUID
- Registration timestamp
- Connectivity history
- Associated sync groups

#### Filtering and Sorting

- Systems are displayed in a table format
- Can be sorted by hostname, status, or last seen
- Filter by status (Online/Offline) if supported

### Sync Groups

The Sync Groups view shows all configured sync groups.

#### Sync Group List

For each sync group, the dashboard displays:

- **Name** - Sync group name
- **Description** - Human-readable description
- **Status** - Enabled or Disabled
- **Mode** - Bidirectional or Directional (hub-and-spoke)
- **Hub System** - Hub system for directional sync groups
- **Systems** - List of systems in the group
- **Sync Interval** - How often sync is checked (in seconds)

#### Sync Status

For each sync group, you can view:
- Number of systems in sync
- Number of out-of-sync snapshots
- Recent sync activity
- Sync state summary

#### Sync Group Details

Click on a sync group to see:
- Complete configuration
- All systems in the group
- Sync states for each dataset
- Recent sync history

### Conflicts

The Conflicts view displays detected conflicts across all sync groups.

#### Conflict List

For each conflict, the dashboard shows:

- **Sync Group** - Which sync group has the conflict
- **Dataset** - Affected dataset
- **Conflict Type** - Type of conflict (diverged, orphaned, missing, etc.)
- **Systems Involved** - Which systems have conflicting snapshots
- **Details** - Specific information about the conflict

#### Conflict Types

Common conflict types:

1. **Diverged** - Snapshots with the same name but different timestamps
2. **Orphaned** - Snapshot exists but no common ancestor
3. **Missing** - Snapshot missing on one or more systems
4. **Size Mismatch** - Snapshots with same name but different sizes

#### Resolution

Currently, conflicts must be resolved via the API. The dashboard shows conflicts for monitoring purposes.

**To resolve conflicts**, use the API:

```bash
curl -X POST "http://your-server:8000/api/v1/conflicts/{conflict_id}/resolve" \
  -H "X-API-Key: api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "resolution_strategy": "use_newest"
  }'
```

### Statistics

The Statistics view provides charts and trends.

#### Available Statistics

1. **Snapshot Count Over Time**
   - Line chart showing snapshot creation trends
   - Can filter by system or sync group

2. **Sync Success Rate**
   - Percentage of successful syncs
   - Can view by sync group or system

3. **Dataset Coverage**
   - Which datasets are synced across which systems
   - Visualization of sync coverage

4. **System Activity**
   - Heartbeat frequency
   - Snapshot reporting frequency
   - Sync execution frequency

#### Time Ranges

Statistics can typically be viewed for:
- Last 24 hours
- Last 7 days
- Last 30 days
- Custom date range (if supported)

---

## Real-time Updates

### Server-Sent Events (SSE)

The dashboard uses Server-Sent Events (SSE) to receive real-time updates from the ZFS Sync server.

#### Connection Status Indicator

In the top-right corner of the navigation bar, you'll see a connection status indicator:

- **Green/Connected** - SSE connection is active, updates are being received
- **Yellow/Connecting** - Connection is being established
- **Red/Disconnected** - Connection is lost, dashboard may show stale data

#### Automatic Updates

When SSE is connected, the dashboard automatically updates:
- System health status
- Sync group status
- Conflict counts
- Recent activity feed
- Statistics (periodically)

#### Manual Refresh

If SSE is disconnected, you can:
- Refresh the page (F5 or Ctrl+R)
- Hard refresh (Ctrl+F5 or Cmd+Shift+R) to clear cache
- Check server logs for SSE connection issues

### Update Frequency

- **System Health**: Updates every 5-10 seconds
- **Sync Status**: Updates when sync operations complete
- **Conflicts**: Updates when conflicts are detected
- **Statistics**: Updates every 30-60 seconds

---

## Common Tasks

### Checking System Health

1. Navigate to **Systems** view
2. Review the status column for each system
3. Check "Last Seen" timestamp to verify recent heartbeats
4. Look for any systems marked as "Offline"

**Via API**:
```bash
curl http://your-server:8000/api/v1/systems/health/all
```

### Monitoring Sync Progress

1. Navigate to **Sync Groups** view
2. Click on a sync group to see detailed status
3. Review sync states for each dataset
4. Check for any "Out of Sync" states

**Via API**:
```bash
curl http://your-server:8000/api/v1/sync/groups/{group_id}/status
```

### Identifying Conflicts

1. Navigate to **Conflicts** view
2. Review the conflict list
3. Click on a conflict to see details
4. Note which systems are involved

**Via API**:
```bash
curl http://your-server:8000/api/v1/conflicts/{sync_group_id}
```

### Viewing Sync History

1. Navigate to **Statistics** view
2. Review sync success rate charts
3. Check activity trends over time

**Via API**:
```bash
curl "http://your-server:8000/api/v1/snapshots/history/{system_id}?days=30"
```

### Checking Recent Activity

1. Navigate to **Overview** view
2. Scroll to "Recent Activity" section
3. Review the activity feed for recent events

---

## Dashboard Limitations

### Read-Only Operations

**Currently, the dashboard is read-only.** You cannot:

- Create new systems
- Register systems
- Create or edit sync groups
- Resolve conflicts
- Trigger manual syncs
- Update system configuration

**To perform these operations**, use:
- The REST API directly
- The interactive API documentation at `http://your-server:8000/docs`
- Command-line tools (curl, HTTPie, etc.)

### Browser Compatibility

The dashboard works best with:
- Chrome/Chromium (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

Older browsers may have limited functionality, especially for SSE support.

### Performance Considerations

- The dashboard loads all systems and sync groups on initial page load
- For large deployments (100+ systems), initial load may be slow
- Consider using the API for programmatic access in large environments

### Data Freshness

- Dashboard data is updated via SSE in real-time
- If SSE is disconnected, data may become stale
- Always check the "Last Updated" timestamp in the navigation bar
- Refresh the page if data seems outdated

### Mobile Support

The dashboard is designed for desktop use. Mobile browsers may have:
- Limited screen space
- Reduced functionality
- Performance issues with large datasets

---

## Tips and Best Practices

### Regular Monitoring

- Check the dashboard daily to monitor system health
- Review conflicts regularly and resolve them promptly
- Monitor sync success rates to identify issues early

### Using with API

- Use the dashboard for visual monitoring
- Use the API for automation and scripting
- Combine both for comprehensive management

### Troubleshooting Dashboard Issues

If the dashboard isn't working:

1. **Check SSE connection** - Look for connection status indicator
2. **Check browser console** - Open developer tools (F12) and look for errors
3. **Verify API access** - Test API endpoints directly with curl
4. **Check server logs** - Review ZFS Sync server logs for errors
5. **Hard refresh** - Clear browser cache and refresh

**See [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md) for detailed troubleshooting steps.**

---

## Related Documentation

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Initial setup including dashboard access
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - Daily operations and monitoring
- [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md) - Dashboard troubleshooting
- [HOW_TO_USE.md](../HOW_TO_USE.md) - API usage examples

---

## Future Enhancements

Planned dashboard improvements (see [IMPROVEMENTS_ROADMAP.md](IMPROVEMENTS_ROADMAP.md)):

- Write operations (create/edit systems and sync groups via UI)
- Manual sync trigger button
- Log viewer
- In-dashboard notifications/alerts
- Conflict resolution via UI
- Export functionality (CSV, JSON)
