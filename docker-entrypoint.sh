#!/bin/sh
# Ensure the log directory is writable by appuser (UID 1000)
# This handles the case where a host volume mount overrides
# the directory ownership set during docker build.
mkdir -p /app/output/logs /app/output/dashboards
chown -R appuser:appuser /app/output

# Drop privileges and exec the main process as appuser
exec gosu appuser "$@"
