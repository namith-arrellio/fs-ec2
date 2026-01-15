# Kamailio + FreeSWITCH Integration

This setup uses Kamailio as a SIP proxy in front of FreeSWITCH to handle:
- **SIP Registration**: Phones register to Kamailio (port 5060)
- **Presence/BLF**: Kamailio handles SUBSCRIBE/NOTIFY for BLF buttons
- **Call Routing**: Kamailio forwards calls to FreeSWITCH for media handling

## Architecture

```
                                    ┌─────────────────┐
                                    │   Telnyx PSTN   │
                                    │  (Inbound DIDs) │
                                    └────────┬────────┘
                                             │ Port 5080
                                             ▼
┌───────────┐     Port 5060      ┌───────────────────┐     Port 5070      ┌─────────────────┐
│  Yealink  │◄──────────────────►│     Kamailio      │◄──────────────────►│   FreeSWITCH    │
│   Phones  │   REGISTER/INVITE  │  (SIP Proxy)      │   INVITE (media)   │ (Media Server)  │
│           │   SUBSCRIBE/NOTIFY │                   │                    │                 │
└───────────┘                    └─────────┬─────────┘                    └────────┬────────┘
                                           │                                       │
                                           │ SIP PUBLISH                           │
                                           │ (presence)                            │
                                           │                                       │
                                           └───────────────┬───────────────────────┘
                                                           │
                                                           ▼
                                              ┌─────────────────────────┐
                                              │   ESL Call Router       │
                                              │ (Inbound ESL + Outbound │
                                              │  ESL + Presence Pub)    │
                                              └─────────────────────────┘
```

## Components

| Component | Port | Description |
|-----------|------|-------------|
| Kamailio | 5060 | SIP Proxy - handles phone registrations and presence |
| FreeSWITCH Internal | 5070 | Media server - receives calls from Kamailio |
| FreeSWITCH External | 5080 | Telnyx gateway connections |
| MySQL | 3306 | Kamailio database for registrations/presence |
| ESL Call Router | 5002 | Call routing + presence publishing (integrated) |

## Deployment Steps

### 1. Set Environment Variables

```bash
# Set your public IP (for NAT traversal)
export ADVERTISED_IP=your.public.ip

# Or create a .env file
echo "ADVERTISED_IP=your.public.ip" > .env
```

### 2. Build and Start Services

```bash
# Build all containers
docker-compose build

# Start MySQL first
docker-compose up -d mysql

# Wait for MySQL to be healthy (check logs)
docker-compose logs -f mysql
# Look for "ready for connections"

# Start remaining services
docker-compose up -d
```

### 3. Initialize Users

After Kamailio starts and initializes the database:

```bash
# Add default users
docker exec kamailio /usr/local/bin/init_users.sh

# Or add individual users
docker exec kamailio /usr/local/bin/add_user.sh 1000 1234 store1.local
```

### 4. Verify Services

```bash
# Check all services
docker-compose ps

# Check Kamailio
docker exec kamailio kamcmd ul.dump

# Check FreeSWITCH
docker exec freeswitch-dev fs_cli -x "sofia status"
```

### 5. Configure Phones

Point your SIP phones to:
- **SIP Server**: `<your-server-ip>` (port 5060)
- **Domain**: `store1.local` or `store2.local`
- **Username**: Extension number (e.g., `1000`)
- **Password**: `1234`

**BLF Buttons:**
- **Type**: BLF
- **Value**: `700` (for park slot 700)
- **Line**: 1

## How BLF Works

1. Phone sends `SUBSCRIBE sip:700@store1.local` to Kamailio
2. Kamailio stores the subscription
3. When a call is parked in slot 700:
   - FreeSWITCH fires a valet_park event via ESL
   - ESL Call Router receives the event
   - ESL Call Router sends `PUBLISH sip:700@store1.local` to Kamailio
   - Kamailio sends `NOTIFY` to all subscribed phones
   - Phone BLF light turns red/blinking

## Troubleshooting

### Check Kamailio registrations
```bash
docker exec kamailio kamcmd ul.dump
```

### Check Kamailio presence
```bash
docker exec kamailio kamcmd pres.phtable_list
```

### Check FreeSWITCH
```bash
docker exec freeswitch-dev fs_cli -x "sofia status"
docker exec freeswitch-dev fs_cli -x "valet_info"
```

### View logs
```bash
docker-compose logs -f kamailio
docker-compose logs -f esl
docker-compose logs -f freeswitch
```

### SIP trace
```bash
# FreeSWITCH
docker exec -it freeswitch-dev fs_cli
> sofia global siptrace on

# Kamailio (increase debug level)
docker exec kamailio kamcmd corex.debug 2
```

## Files

- `kamailio.cfg` - Main Kamailio configuration
- `entrypoint.sh` - Kamailio startup script (creates database)
- `init_users.sh` - Script to add default users
- `add_user.sh` - Script to add individual users
- `../esl/call_router.py` - Call routing + presence publishing (integrated)

## Port Reference

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Kamailio | 5060 | UDP/TCP | Phone registration, presence |
| FreeSWITCH Internal | 5070 | UDP | Calls from Kamailio |
| FreeSWITCH External | 5080 | UDP | Telnyx gateway |
| FreeSWITCH ESL | 8021 | TCP | Event Socket (internal) |
| ESL Router | 5002 | TCP | Outbound ESL for call routing |
| MySQL | 3306 | TCP | Kamailio database |
| RTP | 10000-20000 | UDP | Media streams |
