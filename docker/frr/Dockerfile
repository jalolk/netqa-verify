FROM quay.io/frrouting/frr:10.7.1

RUN apk add --no-cache openssh-server bash \
    && adduser -D -s /bin/bash admin \
    && echo 'admin:admin' | chpasswd \
    && addgroup admin frr \
    && addgroup admin frrvty \
    && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
CMD ["/usr/local/bin/entrypoint.sh"]
