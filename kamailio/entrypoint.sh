#!/bin/bash
set -e

# Wait for MySQL/MariaDB
echo "Waiting for MySQL..."
/usr/local/bin/wait-for-mysql.sh 127.0.0.1

# Set environment for kamdbctl
export DBENGINE=MYSQL
export DBHOST=127.0.0.1
export DBNAME=kamailio
export DBRWUSER=kamailio
export DBRWPW=kamailiorw
export DBROUSER=kamailioro
export DBROPW=kamailioro
export DBROOTUSER=root
export DBROOTPW=root
export CHARSET=utf8
export INSTALL_EXTRA_TABLES=yes
export INSTALL_PRESENCE_TABLES=yes

# Check if database schema is initialized
TABLES_EXIST=$(mysql -h 127.0.0.1 -u root -proot -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='kamailio'" 2>/dev/null || echo "0")

if [ "$TABLES_EXIST" = "0" ] || [ -z "$TABLES_EXIST" ]; then
    echo "Initializing Kamailio database..."
    
    # Let kamdbctl create everything
    echo "y" | kamdbctl create
    
    # Create kamailio users for remote access
    echo "Setting up database users..."
    mysql -h 127.0.0.1 -u root -proot <<EOF
CREATE USER IF NOT EXISTS 'kamailio'@'127.0.0.1' IDENTIFIED BY 'kamailiorw';
GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'127.0.0.1';
FLUSH PRIVILEGES;
EOF

    # Create default domains
    echo "Creating domains..."
    mysql -h 127.0.0.1 -u root -proot kamailio -e "INSERT IGNORE INTO domain (domain) VALUES ('store1.local'), ('store2.local');"

    # Create dispatcher entries for SIP trunks
    echo "Creating dispatcher entries for SIP trunks..."
    mysql -h 127.0.0.1 -u root -proot kamailio <<EOF
-- Dispatcher Group 1: Telnyx SIP Trunk
INSERT IGNORE INTO dispatcher (setid, destination, flags, priority, attrs, description) VALUES
(1, 'sip:sip.telnyx.com:5060', 0, 0, 'weight=100', 'Telnyx Primary');
EOF

    echo "Database initialized successfully!"
else
    echo "Database already initialized (found $TABLES_EXIST tables)."
    
    # Ensure dispatcher entries exist (idempotent)
    echo "Ensuring dispatcher entries exist..."
    mysql -h 127.0.0.1 -u root -proot kamailio <<EOF
-- Remove old invalid entry if exists
DELETE FROM dispatcher WHERE destination LIKE '%sip2.telnyx%';
-- Add primary trunk
INSERT IGNORE INTO dispatcher (setid, destination, flags, priority, attrs, description) VALUES
(1, 'sip:sip.telnyx.com:5060', 0, 0, 'weight=100', 'Telnyx Primary');
EOF
fi

# Replace advertised IP in config
if [ -n "$ADVERTISED_IP" ]; then
    echo "Setting advertised IP to: $ADVERTISED_IP"
    sed -i "s/ADVERTISED_IP/$ADVERTISED_IP/g" /etc/kamailio/kamailio.cfg
else
    # Default to local IP
    LOCAL_IP=$(hostname -i 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
    echo "Setting advertised IP to: $LOCAL_IP"
    sed -i "s/ADVERTISED_IP/$LOCAL_IP/g" /etc/kamailio/kamailio.cfg
fi

# Run Kamailio
echo "Starting Kamailio..."
exec "$@"
