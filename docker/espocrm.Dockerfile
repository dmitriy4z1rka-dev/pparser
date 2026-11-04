FROM espocrm/espocrm:10.0.11
COPY espocrm/custom/Espo/Custom /opt/leadgen/custom
COPY espocrm/client/custom /opt/leadgen/client-custom
COPY docker/espocrm-entrypoint.sh /usr/local/bin/leadgen-entrypoint.sh
COPY docker/setup-crm.sh /opt/leadgen/setup-crm.sh
ENTRYPOINT ["/bin/sh", "/usr/local/bin/leadgen-entrypoint.sh"]
CMD ["apache2-foreground"]
