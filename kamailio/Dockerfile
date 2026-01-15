FROM ghcr.io/kamailio/kamailio-ci:latest-alpine

# Install additional packages (Alpine uses apk, not apt-get)
RUN apk add --no-cache \
    mysql-client \
    netcat-openbsd \
    bash

# Create kamailio user and run directory
RUN addgroup -S kamailio && adduser -S -G kamailio kamailio && \
    mkdir -p /var/run/kamailio && \
    chown kamailio:kamailio /var/run/kamailio

# Copy configuration
COPY kamailio.cfg /etc/kamailio/kamailio.cfg
COPY kamctlrc /etc/kamailio/kamctlrc

# Copy scripts
COPY wait-for-mysql.sh /usr/local/bin/
COPY entrypoint.sh /usr/local/bin/
COPY init_users.sh /usr/local/bin/
COPY add_user.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh

EXPOSE 5060/udp 5060/tcp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["kamailio", "-DD", "-E", "-e"]
