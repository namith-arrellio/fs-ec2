#!/bin/bash
# Add a user to Kamailio
# Usage: ./add_user.sh <username> <password> <domain>

if [ $# -lt 3 ]; then
    echo "Usage: $0 <username> <password> <domain>"
    echo "Example: $0 1000 1234 store1.local"
    exit 1
fi

USERNAME=$1
PASSWORD=$2
DOMAIN=$3

# Add user to subscriber table
mysql -h 127.0.0.1 -u kamailio -pkamailiorw kamailio <<EOF
INSERT INTO subscriber (username, domain, password, ha1, ha1b) VALUES (
    '$USERNAME',
    '$DOMAIN',
    '$PASSWORD',
    MD5('$USERNAME:$DOMAIN:$PASSWORD'),
    MD5('$USERNAME@$DOMAIN:$DOMAIN:$PASSWORD')
) ON DUPLICATE KEY UPDATE
    password = '$PASSWORD',
    ha1 = MD5('$USERNAME:$DOMAIN:$PASSWORD'),
    ha1b = MD5('$USERNAME@$DOMAIN:$DOMAIN:$PASSWORD');
EOF

echo "User $USERNAME@$DOMAIN added/updated."

