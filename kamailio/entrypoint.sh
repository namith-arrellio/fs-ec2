#!/bin/bash
set -e

# Wait for MySQL
echo "Waiting for MySQL..."
/usr/local/bin/wait-for-mysql.sh 127.0.0.1 echo "MySQL ready"

# Check if database is initialized
DB_EXISTS=$(mysql -h 127.0.0.1 -u root -proot -e "SHOW DATABASES LIKE 'kamailio'" | grep kamailio || true)

if [ -z "$DB_EXISTS" ]; then
    echo "Creating Kamailio database..."
    
    # Create database and user
    mysql -h 127.0.0.1 -u root -proot <<EOF
CREATE DATABASE kamailio;
CREATE USER IF NOT EXISTS 'kamailio'@'%' IDENTIFIED BY 'kamailiorw';
CREATE USER IF NOT EXISTS 'kamailioro'@'%' IDENTIFIED BY 'kamailioro';
GRANT ALL PRIVILEGES ON kamailio.* TO 'kamailio'@'%';
GRANT SELECT ON kamailio.* TO 'kamailioro'@'%';
FLUSH PRIVILEGES;
EOF

    # Initialize database schema
    echo "Initializing database schema..."
    kamdbctl create

    # Create default domains
    echo "Creating domains..."
    mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio <<EOF
INSERT INTO domain (domain) VALUES ('store1.local');
INSERT INTO domain (domain) VALUES ('store2.local');
EOF

    echo "Database initialized."
else
    echo "Database already exists."
fi

# Replace advertised IP in config
if [ -n "$ADVERTISED_IP" ]; then
    sed -i "s/ADVERTISED_IP/$ADVERTISED_IP/g" /etc/kamailio/kamailio.cfg
else
    # Default to local IP
    LOCAL_IP=$(hostname -i | awk '{print $1}')
    sed -i "s/ADVERTISED_IP/$LOCAL_IP/g" /etc/kamailio/kamailio.cfg
fi

# Run Kamailio
exec "$@"

