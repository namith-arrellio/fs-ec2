#!/bin/bash
set -e

# Wait for MySQL
echo "Waiting for MySQL..."
/usr/local/bin/wait-for-mysql.sh 127.0.0.1

# Check if database is initialized
DB_EXISTS=$(mysql -h 127.0.0.1 -u root -proot -N -e "SHOW DATABASES LIKE 'kamailio'" 2>/dev/null | grep kamailio || true)

if [ -z "$DB_EXISTS" ]; then
    echo "Creating Kamailio database..."
    
    # Create database and user
    mysql -h 127.0.0.1 -u root -proot <<EOF
CREATE DATABASE IF NOT EXISTS kamailio;
CREATE USER IF NOT EXISTS 'kamailio'@'%' IDENTIFIED BY 'kamailiorw';
CREATE USER IF NOT EXISTS 'kamailio'@'localhost' IDENTIFIED BY 'kamailiorw';
CREATE USER IF NOT EXISTS 'kamailioro'@'%' IDENTIFIED BY 'kamailioro';
GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'%';
GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'localhost';
GRANT SELECT ON kamailio.* TO 'kamailioro'@'%';
FLUSH PRIVILEGES;
EOF

    # Initialize database schema using kamdbctl
    echo "Initializing database schema..."
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

    echo "Database initialized."
else
    echo "Database already exists."
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
