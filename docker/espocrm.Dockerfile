FROM espocrm/espocrm:10.0.11
COPY vendor/crm-custom/Espo/Custom /opt/leadgen/custom
COPY vendor/crm-client-custom /opt/leadgen/client-custom
COPY docker/espocrm-entrypoint.sh /usr/local/bin/leadgen-entrypoint.sh
COPY docker/setup-crm.sh /opt/leadgen/setup-crm.sh
ENTRYPOINT ["/bin/sh", "/usr/local/bin/leadgen-entrypoint.sh"]
CMD ["apache2-foreground"]
