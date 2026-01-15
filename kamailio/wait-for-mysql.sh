#!/bin/bash
# Wait for MySQL to be ready

set -e

host="${1:-127.0.0.1}"

echo "Waiting for MySQL at $host..."

until mysql -h "$host" -u root -proot -e "SELECT 1" > /dev/null 2>&1; do
  echo "MySQL is unavailable - sleeping"
  sleep 2
done

echo "MySQL is up!"
