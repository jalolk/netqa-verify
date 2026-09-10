#!/bin/sh
set -e
ssh-keygen -A
/usr/sbin/sshd
exec sleep infinity
