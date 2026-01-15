#!/bin/bash
set -e

# Wait for MySQL/MariaDB
echo "Waiting for MySQL..."
/usr/local/bin/wait-for-mysql.sh 127.0.0.1

# Always ensure kamailio user exists
echo "Ensuring kamailio user exists..."
mysql -h 127.0.0.1 -u root -proot <<EOF
CREATE DATABASE IF NOT EXISTS kamailio;
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
TABLES_EXIST=$(mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio -N -e "SHOW TABLES LIKE 'version'" 2>/dev/null | grep version || true)

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
    
    # Drop and recreate database to ensure clean state
    echo "Dropping and recreating database..."
    mysql -h 127.0.0.1 -u root -proot -e "DROP DATABASE IF EXISTS kamailio; CREATE DATABASE kamailio;"
    mysql -h 127.0.0.1 -u root -proot -e "GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'%'; FLUSH PRIVILEGES;"
    
    # Create tables (answer yes to prompts)
    echo "Creating Kamailio tables..."
    echo "y" | kamdbctl create
    
    if [ $? -ne 0 ]; then
        echo "kamdbctl create failed, trying reinit..."
        echo "y" | kamdbctl reinit || true
    fi

    echo "Database schema initialized."
else
    echo "Database schema already exists."
fi

# Create default domains (ignore errors if they exist)
echo "Ensuring domains exist..."
mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio -e "INSERT IGNORE INTO domain (domain) VALUES ('store1.local');" 2>/dev/null || true
mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio -e "INSERT IGNORE INTO domain (domain) VALUES ('store2.local');" 2>/dev/null || true

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
