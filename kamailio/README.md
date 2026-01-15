# Kamailio SIP Proxy

## Architecture Overview

Kamailio serves as the central SIP signaling hub for the VoIP system:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SYSTEM ARCHITECTURE                         │
└─────────────────────────────────────────────────────────────────────┘

  Yealink Phones ─────► Kamailio (5060) ◄───── SIP Trunks (Telnyx)
        ▲                     │ ▲                    
        │                     │ │                    
        │                     ▼ │                    
        │               FreeSWITCH (5070)            
        │               (Media/IVR/PBX)              
        │                     │                      
        └─────────────────────┘                      
```

### Components

| Component | Port | Role |
|-----------|------|------|
| **Kamailio** | 5060 | SIP registrar, proxy, trunk gateway |
| **FreeSWITCH** | 5070 | Media server (IVR, voicemail, conferencing, parking) |
| **MariaDB** | 3306 | User database, presence, dispatcher |

### Kamailio Responsibilities

1. **SIP Registration**: Phones register to Kamailio
2. **Presence/BLF**: Handles SUBSCRIBE/PUBLISH for BLF
3. **Trunk Gateway**: Entry point for SIP trunk connections
4. **Routing**: Decides where to route each call
5. **NAT Handling**: Manages NAT traversal for phones

### FreeSWITCH Responsibilities

1. **Media Handling**: RTP processing, codec transcoding
2. **IVR/Auto-Attendant**: Interactive voice menus
3. **Voicemail**: Message recording and retrieval
4. **Conferencing**: Multi-party calls
5. **Call Parking**: Valet parking with BLF
6. **Call Recording**: Optional call recording

## Call Flows

### 1. Yealink Phone to Another Extension

```
Phone A                Kamailio                FreeSWITCH              Phone B
   │                      │                        │                      │
   │──INVITE (1001)──────►│                        │                      │
   │                      │──INVITE──────────────►│                      │
   │                      │  (X-Internal-Call)    │                      │
   │                      │                        │──(processing)───────►│
   │                      │◄──INVITE──────────────│                      │
   │                      │  (to registered user) │                      │
   │                      │───────────────────────────INVITE────────────►│
   │◄─────────────────────────────────────────────────────180 Ringing────│
   │◄─────────────────────────────────────────────────────200 OK─────────│
   │──ACK────────────────────────────────────────────────────────────────►│
   │◄═══════════════════════════RTP (via FreeSWITCH)═════════════════════►│
```

### 2. Outbound Call (Phone to External Number)

```
Phone                  Kamailio                FreeSWITCH              Telnyx
   │                      │                        │                      │
   │──INVITE──────────────►                        │                      │
   │  (+15551234567)      │                        │                      │
   │                      │──INVITE──────────────►│                      │
   │                      │  (X-Outbound-Call)    │                      │
   │                      │◄──INVITE──────────────│                      │
   │                      │  (X-Route-To-Trunk)   │                      │
   │                      │──────────────────────────INVITE─────────────►│
   │◄─────────────────────────────────────────────────────180 Ringing────│
   │◄─────────────────────────────────────────────────────200 OK─────────│
   │◄═══════════════════════════════RTP══════════════════════════════════►│
```

### 3. Inbound Call from SIP Trunk

```
Telnyx                 Kamailio                FreeSWITCH              Phone
   │                      │                        │                      │
   │──INVITE──────────────►                        │                      │
   │  (+17577828734)      │                        │                      │
   │                      │──INVITE──────────────►│                      │
   │                      │  (X-Inbound-Trunk)    │                      │
   │                      │  (X-Store-Domain)     │──(IVR/Ring Group)───►│
   │                      │                        │                      │
   │                      │◄──INVITE──────────────│                      │
   │                      │  (to registered user) │                      │
   │                      │───────────────────────────INVITE────────────►│
   │◄─────────────────────────────────────────────────────180 Ringing────│
   │◄─────────────────────────────────────────────────────200 OK─────────│
   │◄═══════════════════════════════RTP══════════════════════════════════►│
```

## Configuration

### Custom Headers (Kamailio → FreeSWITCH)

| Header | Description |
|--------|-------------|
| `X-Store-Domain` | The store domain (store1.local, store2.local) |
| `X-Inbound-Trunk` | Set to "true" for calls from SIP trunk |
| `X-Outbound-Call` | Set to "true" for outbound calls from phones |
| `X-Internal-Call` | Set to "true" for extension-to-extension calls |
| `X-Park-Call` | Set to "true" for park slot calls |
| `X-Original-DID` | The original DID number for inbound calls |

### Custom Headers (FreeSWITCH → Kamailio)

| Header | Description |
|--------|-------------|
| `X-Route-To-Trunk` | Request Kamailio to route to SIP trunk |
| `X-Store-Domain` | The store domain for caller ID selection |

### DID to Store Mapping

| DID | Store Domain | Description |
|-----|--------------|-------------|
| 7577828734 | store1.local | Store 1 |
| 7372449688 | store2.local | Store 2 |

### SIP Trunk Configuration

Trunks are configured in the `dispatcher` table:

```sql
-- Dispatcher Group 1: Telnyx SIP Trunk
INSERT INTO dispatcher (setid, destination, flags, priority, attrs, description) VALUES
(1, 'sip:sip.telnyx.com:5060', 0, 0, 'weight=50', 'Telnyx Primary'),
(1, 'sip:sip2.telnyx.com:5060', 0, 1, 'weight=50', 'Telnyx Secondary');
```

## User Management

### Add a new SIP user

```bash
docker exec -it kamailio /usr/local/bin/add_user.sh 1000 password123 store1.local
```

### Initialize default users

```bash
docker exec -it kamailio /usr/local/bin/init_users.sh
```

### List registered users

```bash
docker exec -it kamailio kamctl ul show
```

## Troubleshooting

### Check Kamailio status

```bash
docker exec -it kamailio kamctl stats
```

### View SIP traffic

```bash
docker exec -it kamailio sngrep
```

### Check dispatcher status

```bash
docker exec -it kamailio kamctl dispatcher show
```

### Reload dispatcher

```bash
docker exec -it kamailio kamctl dispatcher reload
```

### View logs

```bash
docker logs -f kamailio
```

## Database Tables

| Table | Purpose |
|-------|---------|
| `subscriber` | SIP user accounts |
| `location` | Active registrations |
| `domain` | SIP domains |
| `dispatcher` | SIP trunk endpoints |
| `dialog` | Active call dialogs |
| `presentity` | Presence state |
| `active_watchers` | Presence subscriptions |

## Security

- Pike module for flood detection
- IP-based blocking for repeat offenders
- User-agent filtering for known scanners
- ACL-based trunk authentication
- Credential-based phone authentication

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ADVERTISED_IP` | Public IP for SIP/SDP | Auto-detected |
