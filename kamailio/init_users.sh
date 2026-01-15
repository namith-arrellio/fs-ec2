#!/bin/bash
# Initialize default users in Kamailio
# Run this after database is initialized

set -e

# Wait for MySQL
echo "Waiting for MySQL..."
until mysql -h 127.0.0.1 -u kamailio -pkamailiorw -e "SELECT 1" > /dev/null 2>&1; do
    echo "MySQL is unavailable - sleeping"
    sleep 2
done

echo "Adding users to Kamailio..."

# Store 1 users
for ext in 1000 1001 1002 1003 1004 1005; do
    mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio <<EOF
INSERT INTO subscriber (username, domain, password, ha1, ha1b) VALUES (
    '$ext',
    'store1.local',
    '1234',
    MD5('$ext:store1.local:1234'),
    MD5('$ext@store1.local:store1.local:1234')
) ON DUPLICATE KEY UPDATE password = '1234';
EOF
    echo "Added $ext@store1.local"
done

# Store 2 users
for ext in 1000 1001 1002 1003 1004 1005; do
    mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio <<EOF
INSERT INTO subscriber (username, domain, password, ha1, ha1b) VALUES (
    '$ext',
    'store2.local',
    '1234',
    MD5('$ext:store2.local:1234'),
    MD5('$ext@store2.local:store2.local:1234')
) ON DUPLICATE KEY UPDATE password = '1234';
EOF
    echo "Added $ext@store2.local"
done

echo "User initialization complete!"
