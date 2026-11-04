#!/bin/sh
set -eu
mkdir -p /var/www/html/custom/Espo/Custom
cp -R /opt/leadgen/custom/. /var/www/html/custom/Espo/Custom/
mkdir -p /var/www/html/client/custom
cp -R /opt/leadgen/client-custom/. /var/www/html/client/custom/
exec docker-entrypoint.sh "$@"
