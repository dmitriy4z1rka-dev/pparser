#!/bin/sh
set -eu
cd /var/www/html
php command.php clear-cache
php command.php rebuild
php command.php leadgen-setup
chown -R www-data:www-data data custom client/custom
