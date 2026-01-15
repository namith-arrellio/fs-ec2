#!/bin/bash
set -e

# Wait for MySQL/MariaDB
echo "Waiting for MySQL..."
/usr/local/bin/wait-for-mysql.sh 127.0.0.1

# Always ensure kamailio user exists
echo "Ensuring kamailio user exists..."
mysql -h 127.0.0.1 -u root -proot <<EOF
CREATE USER IF NOT EXISTS 'kamailio'@'%' IDENTIFIED BY 'kamailiorw';
CREATE USER IF NOT EXISTS 'kamailio'@'localhost' IDENTIFIED BY 'kamailiorw';
CREATE USER IF NOT EXISTS 'kamailio'@'127.0.0.1' IDENTIFIED BY 'kamailiorw';
CREATE USER IF NOT EXISTS 'kamailioro'@'%' IDENTIFIED BY 'kamailioro';
GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'%';
GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'localhost';
GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'127.0.0.1';
GRANT SELECT ON kamailio.* TO 'kamailioro'@'%';
FLUSH PRIVILEGES;
EOF

# Check if database schema is initialized (check for a known table)
TABLES_EXIST=$(mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio -N -e "SHOW TABLES LIKE 'subscriber'" 2>/dev/null | grep subscriber || true)

if [ -z "$TABLES_EXIST" ]; then
    echo "Initializing Kamailio database schema..."
    
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
    
    # Create tables (answer yes to prompts)
    echo "y" | kamdbctl create || echo "Database tables may already exist"

    # Create default domains
    echo "Creating domains..."
    mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio <<EOF
INSERT IGNORE INTO domain (domain) VALUES ('store1.local');
INSERT IGNORE INTO domain (domain) VALUES ('store2.local');
EOF

    echo "Database schema initialized."
else
    echo "Database schema already exists."
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
