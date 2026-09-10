#!/bin/sh
set -e
ssh-keygen -A
/usr/sbin/sshd
exec /usr/lib/frr/docker-start
