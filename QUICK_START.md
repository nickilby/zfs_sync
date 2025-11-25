# Quick Start Guide

## For Linux Systems (Debian/Ubuntu)

### Step 1: Install Python and Dependencies

```bash
# Install Python and venv support
sudo apt update
sudo apt install python3 python3-venv python3-pip

# Clone the repository (if not already done)
git clone <repository-url>
cd zfs_sync
```

### Step 2: Set Up Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

### Step 3: Configure (Optional)

```bash
# Copy example config
cp config/zfs_sync.yaml.example config/zfs_sync.yaml

# Edit if needed
nano config/zfs_sync.yaml
```

### Step 4: Start the Server

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Start the server
python -m zfs_sync
```

The server will start on `http://0.0.0.0:8000` and will be accessible via:
- Local: `http://localhost:8000`
- Network: `http://your-server-ip:8000`
- DNS: `http://your-dns-name:8000`

### Step 5: Access the API

Open your browser and go to:
- API Documentation: `http://your-dns-name:8000/docs`
- Health Check: `http://your-dns-name:8000/api/v1/health`

## Using the Setup Script

Alternatively, use the provided setup script:

```bash
chmod +x setup.sh
./setup.sh
source venv/bin/activate
python -m zfs_sync
```

## Running as a Service (systemd)

Create `/etc/systemd/system/zfs-sync.service`:

```ini
[Unit]
Description=ZFS Sync Witness Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/zfs_sync
Environment="PATH=/path/to/zfs_sync/venv/bin"
ExecStart=/path/to/zfs_sync/venv/bin/python -m zfs_sync
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable zfs-sync
sudo systemctl start zfs-sync
sudo systemctl status zfs-sync
```

## Troubleshooting

**Problem:** "externally-managed-environment" error
**Solution:** Always use a virtual environment (venv) - never install packages system-wide

**Problem:** Port 8000 already in use
**Solution:** Change the port in `config/zfs_sync.yaml` or set `ZFS_SYNC_PORT=8080`

**Problem:** Can't access from other machines
**Solution:** 
- Verify firewall allows port 8000: `sudo ufw allow 8000`
- Check server is bound to 0.0.0.0 (default, should work)
- Verify DNS/network connectivity



