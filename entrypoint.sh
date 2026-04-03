#!/bin/bash
# entrypoint.sh

LOG_PREFIX="[entrypoint]"

echo "$LOG_PREFIX ========== STARTUP =========="
echo "$LOG_PREFIX Args: $@"
echo "$LOG_PREFIX CLAUDE_CODE_SSE_PORT=${CLAUDE_CODE_SSE_PORT:-<not set>}"
echo "$LOG_PREFIX ENABLE_IDE_INTEGRATION=${ENABLE_IDE_INTEGRATION:-<not set>}"
echo "$LOG_PREFIX CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR:-<not set>}"
echo "$LOG_PREFIX USER=$(whoami), HOME=$HOME, PWD=$PWD"
echo "$LOG_PREFIX IDE dir contents at startup:"
ls -la ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/ide/ 2>/dev/null || echo "$LOG_PREFIX IDE dir not found"

# Forward PyCharm's WebSocket port to host via socat
if [ -n "$CLAUDE_CODE_SSE_PORT" ]; then
  echo "$LOG_PREFIX Starting socat: localhost:${CLAUDE_CODE_SSE_PORT} -> host.docker.internal:${CLAUDE_CODE_SSE_PORT}"

  socat -v TCP-LISTEN:${CLAUDE_CODE_SSE_PORT},fork,reuseaddr \
        TCP:host.docker.internal:${CLAUDE_CODE_SSE_PORT} \
        2>${CLAUDE_CONFIG_DIR:-$HOME/.claude}/socat.log &

  SOCAT_PID=$!

  # Poll briefly instead of a fixed sleep to catch fast failures reliably
  for i in 1 2 3 4 5; do
    sleep 0.1
    kill -0 $SOCAT_PID 2>/dev/null || break
  done

  if kill -0 $SOCAT_PID 2>/dev/null; then
    echo "$LOG_PREFIX socat started successfully (PID=$SOCAT_PID)"
  else
    echo "$LOG_PREFIX ERROR: socat failed to start"
  fi
else
  echo "$LOG_PREFIX Skipping socat (CLAUDE_CODE_SSE_PORT not set)"
fi

# Lock file guardian - backs up all lock files and restores them if deleted,
# but only if the IDE WebSocket port is still reachable on the host
(
  IDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/ide"
  BACKUP_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/ide-backups"
  mkdir -p "$IDE_DIR" "$BACKUP_DIR"

  while true; do
    # Back up any new lock files
    for f in "$IDE_DIR"/*.lock; do
      [ -f "$f" ] || continue
      fname=$(basename "$f")
      backup="$BACKUP_DIR/$fname"
      if [ ! -f "$backup" ]; then
        cp "$f" "$backup"
        echo "$LOG_PREFIX Backed up lock file: $fname"
      fi
    done

    # Check each backup and restore if deleted, but only if port is still alive
    for backup in "$BACKUP_DIR"/*.lock; do
      [ -f "$backup" ] || continue
      fname=$(basename "$backup")
      original="$IDE_DIR/$fname"

      ALIVE_PIDS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.alive_pids"
      LOCK_PID=$(grep -o '"pid":[0-9]*' "$backup" | grep -o '[0-9]*')
      if [ -n "$LOCK_PID" ] && [ -f "$ALIVE_PIDS" ] && ! grep -qw "$LOCK_PID" "$ALIVE_PIDS"; then
        rm "$backup"
        echo "$LOG_PREFIX IDE PID $LOCK_PID no longer alive, removing backup: $fname"
        continue
      fi

      # Port alive but lock file missing - restore it
      if [ ! -f "$original" ]; then
        cp "$backup" "$original"
        echo "$LOG_PREFIX Restored lock file: $fname"
      fi
    done

    sleep 0.3
  done
) &
echo "$LOG_PREFIX Lock file guardian started (PID=$!)"

echo "$LOG_PREFIX ============================="
echo "$LOG_PREFIX socat log: ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/socat.log"
echo "$LOG_PREFIX Launching: claude $@"

exec claude "$@"