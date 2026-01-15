FROM kamailio/kamailio:5.7.3-bullseye

# Install additional modules
RUN apt-get update && apt-get install -y \
    kamailio-mysql-modules \
    kamailio-presence-modules \
    kamailio-extra-modules \
    kamailio-utils-modules \
    default-mysql-client \
    netcat \
    && rm -rf /var/lib/apt/lists/*

# Create run directory
RUN mkdir -p /var/run/kamailio && chown kamailio:kamailio /var/run/kamailio

# Copy configuration
COPY kamailio.cfg /etc/kamailio/kamailio.cfg
COPY kamctlrc /etc/kamailio/kamctlrc

# Wait script for MySQL
COPY wait-for-mysql.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/wait-for-mysql.sh

# Entrypoint
COPY entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 5060/udp 5060/tcp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["kamailio", "-DD", "-E", "-e"]

